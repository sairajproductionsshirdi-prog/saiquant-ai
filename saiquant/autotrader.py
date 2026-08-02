"""
autotrader.py — The autonomous paper-trading campaign engine.

    py run.py --auto           # one daily cycle: monitor, then scan for entries
    py run.py --campaign       # campaign status
    py run.py --final-report   # the 15-day verdict

Each cycle:
  1. Roll the day; check volatility halt (Nifty move) and API health.
  2. MONITOR open positions: mark to market, trail stops, exit on stop /
     target / signal reversal / max holding days.
  3. SCAN for new entries using the mechanical rules; size each candidate to
     1% capital risk; pass through the risk engine; simulate the fill.
  4. Log every decision with its reason, and snapshot daily equity.

PAPER ONLY. There is no code path here that can place a real order.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

from .indicators import ema, rsi
from .ai_gate import review as ai_review
from .riskengine import RiskConfig, RiskEngine, RiskState
from .universe import groups, resolve

MAX_HOLDING_DAYS = 20
COST_PCT_PER_SIDE = 0.125


# ── storage (SQLite locally, Postgres when DATABASE_URL is set) ─────────
from .db import Database, init_schema


class CampaignStore:
    def __init__(self, db: Database | None = None):
        self.db = db or Database()
        init_schema(self.db)

    def backend(self) -> str:
        return self.db.backend_name()

    def meta_get(self, k, default=None):
        r = self.db.fetchone("SELECT v FROM meta WHERE k=?", (k,))
        return r[0] if r else default

    def meta_set(self, k, v):
        self.db.upsert("meta", "k", k, "v", str(v))

    def log(self, symbol, action, detail):
        self.db.execute("INSERT INTO decisions VALUES (?,?,?,?)",
                        (datetime.now().isoformat(timespec="seconds"),
                         symbol, action, detail))

    def open_positions(self) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT id,symbol,grp,qty,entry,stop,target,highest,opened,reason,"
            "confidence FROM positions WHERE status='OPEN' ORDER BY id")
        cols = ["id", "symbol", "group", "qty", "entry", "stop", "target",
                "highest", "opened", "reason", "confidence"]
        return [dict(zip(cols, r)) for r in rows]

    def closed_trades(self) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT symbol,grp,qty,entry,exit,pnl,opened,closed,exit_reason,"
            "reason,confidence FROM positions WHERE status='CLOSED' "
            "ORDER BY closed")
        cols = ["symbol", "group", "qty", "entry", "exit", "pnl", "opened",
                "closed", "exit_reason", "reason", "confidence"]
        return [dict(zip(cols, r)) for r in rows]

    def add_position(self, **kw):
        self.db.execute(
            "INSERT INTO positions (symbol,grp,qty,entry,stop,target,highest,"
            "opened,reason,confidence) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (kw["symbol"], kw["group"], kw["qty"], kw["entry"], kw["stop"],
             kw["target"], kw["entry"], date.today().isoformat(),
             kw["reason"], kw["confidence"]))

    def update_position(self, pid, **kw):
        sets = ", ".join(f"{k}=?" for k in kw)
        self.db.execute(f"UPDATE positions SET {sets} WHERE id=?",
                        (*kw.values(), pid))

    def close_position(self, pid, exit_px, reason, pnl):
        self.update_position(pid, status="CLOSED", exit=exit_px,
                             closed=date.today().isoformat(),
                             exit_reason=reason, pnl=pnl)

    def snapshot_equity(self, value: float):
        self.db.upsert("equity", "day", date.today().isoformat(),
                       "value", round(value, 2))

    def equity_series(self) -> list[tuple[str, float]]:
        return self.db.fetchall("SELECT day, value FROM equity ORDER BY day")

    def recent_decisions(self, n: int = 20) -> list[tuple]:
        return self.db.fetchall(
            "SELECT ts,symbol,action,detail FROM decisions "
            "ORDER BY ts DESC LIMIT ?", (n,))

    def save_risk_state(self, st: RiskState):
        self.meta_set("risk_state", json.dumps(st.__dict__))

    def load_risk_state(self) -> RiskState:
        raw = self.meta_get("risk_state")
        if not raw:
            return RiskState()
        try:
            return RiskState(**json.loads(raw))
        except Exception:
            return RiskState()


# ── market data ──────────────────────────────────────────────────────────
def daily_history(symbol: str, period: str = "6mo") -> pd.DataFrame:
    df = yf.Ticker(resolve(symbol)).history(period=period, interval="1d")
    if df is None or len(df) < 60:
        raise ValueError("insufficient data")
    return df


def index_change_pct() -> float | None:
    try:
        h = yf.Ticker("^NSEI").history(period="5d", interval="1d")
        return round((float(h["Close"].iloc[-1]) / float(h["Close"].iloc[-2]) - 1)
                     * 100, 2)
    except Exception:
        return None


# ── signal generation (mechanical, testable, no look-ahead) ──────────────
def evaluate(symbol: str, df: pd.DataFrame) -> dict | None:
    close, vol = df["Close"], df["Volume"]
    e9, e21, e50 = ema(close, 9), ema(close, 21), ema(close, 50)
    r = rsi(close)
    vol_avg = vol.rolling(20).mean()

    last = float(close.iloc[-1])
    cross = (e9.iloc[-2] <= e21.iloc[-2]) and (e9.iloc[-1] > e21.iloc[-1])
    vol_ok = bool((vol.iloc[-3:] >= 1.5 * (vol_avg.iloc[-1] or 1)).any())
    above_50 = e21.iloc[-1] > e50.iloc[-1]
    rsi_v = float(r.iloc[-1])

    if not cross:
        return None
    reasons, score = [], 4
    reasons.append("EMA9 crossed above EMA21")
    if vol_ok:
        score += 2
        reasons.append("volume surge confirms")
    else:
        reasons.append("volume weak (no confirmation)")
    if above_50:
        score += 2
        reasons.append("EMA21 above EMA50 (uptrend intact)")
    else:
        reasons.append("below EMA50 (counter-trend)")
    if rsi_v < 65:
        score += 1
        reasons.append(f"RSI {rsi_v:.0f} not overbought")
    else:
        score -= 1
        reasons.append(f"RSI {rsi_v:.0f} overbought — chasing risk")

    stop = float(df["Low"].tail(20).min())
    if stop >= last:
        return None
    # cap stop distance at 10% so 1% risk sizing stays sensible
    if (last - stop) / last > 0.10:
        stop = last * 0.90
    target = last + 2.5 * (last - stop)   # >= 1:2 risk-reward by construction

    return {"symbol": symbol, "price": round(last, 2),
            "stop": round(stop, 2), "target": round(target, 2),
            "confidence": max(1, min(10, score)),
            "reason": "; ".join(reasons)}


# ── the daily cycle ──────────────────────────────────────────────────────
def run_cycle(capital: float = 100_000.0, min_confidence: int = 7,
              fetch=daily_history, index_fn=index_change_pct,
              progress=None, use_ai: bool = True,
              ai_reviewer=ai_review, max_ai_reviews: int = 8) -> dict:
    store = CampaignStore()
    if not store.meta_get("start_date"):
        store.meta_set("start_date", date.today().isoformat())
        store.meta_set("capital", capital)
    capital = float(store.meta_get("capital", capital))

    state = store.load_risk_state()
    state.roll_day()
    risk = RiskEngine(RiskConfig(capital=capital), state)

    events: list[str] = []
    ai_reviews_used = 0

    # 1. volatility halt
    chg = index_fn()
    risk.check_volatility(chg)
    if risk.state.halted:
        store.log("SYSTEM", "HALT", risk.state.halt_reason)
        events.append(f"⛔ {risk.state.halt_reason}")

    # 2. monitor open positions
    for pos in store.open_positions():
        try:
            df = fetch(pos["symbol"], "3mo")
            risk.note_data_success()
        except Exception as e:
            risk.note_data_failure()
            store.log(pos["symbol"], "DATA_FAIL", str(e)[:80])
            events.append(f"⚠️ data failure on {pos['symbol']}")
            continue

        price = float(df["Close"].iloc[-1])
        high = max(pos["highest"], float(df["High"].iloc[-1]))
        new_stop, moved = risk.update_trailing_stop(pos["entry"], pos["stop"], high)
        if moved:
            store.log(pos["symbol"], "TRAIL",
                      f"stop {pos['stop']} → {new_stop} (high {high:.2f})")
            events.append(f"↗ trailed {pos['symbol']} stop to ₹{new_stop}")
        store.update_position(pos["id"], highest=high, stop=new_stop)

        held = (date.today() - date.fromisoformat(pos["opened"])).days
        exit_px, why = None, ""
        if price <= new_stop:
            exit_px, why = new_stop, "stop-loss"
        elif price >= pos["target"]:
            exit_px, why = pos["target"], "target reached"
        elif held >= MAX_HOLDING_DAYS:
            exit_px, why = price, f"time exit ({held}d)"
        else:
            e9, e21 = ema(df["Close"], 9), ema(df["Close"], 21)
            if e9.iloc[-1] < e21.iloc[-1]:
                exit_px, why = price, "signal reversal (EMA9 below EMA21)"

        if exit_px is not None:
            gross = (exit_px - pos["entry"]) * pos["qty"]
            costs = (exit_px + pos["entry"]) * pos["qty"] * COST_PCT_PER_SIDE / 100
            pnl = round(gross - costs, 2)
            store.close_position(pos["id"], round(exit_px, 2), why, pnl)
            risk.record_realised(pnl)
            store.log(pos["symbol"], "EXIT",
                      f"{why} @ ₹{exit_px:.2f}, P&L ₹{pnl:,.0f}")
            events.append(f"✅ closed {pos['symbol']}: {why}, P&L ₹{pnl:,.0f}")

    # 3. scan for entries
    scanned = 0
    if not risk.state.halted:
        gmap = groups()
        for gname, syms in gmap.items():
            for sym in syms:
                scanned += 1
                if progress:
                    progress(scanned, sum(len(v) for v in gmap.values()), sym)
                open_pos = store.open_positions()
                if any(p["symbol"] == sym for p in open_pos):
                    continue
                try:
                    df = fetch(sym, "6mo")
                    risk.note_data_success()
                except Exception:
                    risk.note_data_failure()
                    if risk.state.halted:
                        events.append(f"⛔ {risk.state.halt_reason}")
                        break
                    continue

                sig = evaluate(sym, df)
                if not sig:
                    continue
                if sig["confidence"] < min_confidence:
                    store.log(sym, "SKIP",
                              f"confidence {sig['confidence']}/10 below "
                              f"threshold — {sig['reason']}")
                    continue

                # ── AI six-lens review before any capital is committed ──
                ai_note = ""
                if use_ai:
                    if ai_reviews_used >= max_ai_reviews:
                        store.log(sym, "SKIP",
                                  f"daily AI review budget ({max_ai_reviews}) "
                                  f"exhausted — candidate deferred")
                        continue
                    if progress:
                        progress(scanned, sum(len(v) for v in gmap.values()),
                                 f"{sym} (AI review)")
                    verdict = ai_reviewer(sig, gname)
                    ai_reviews_used += 1
                    if not verdict["approved"]:
                        store.log(sym, "AI_REJECT",
                                  f"sentiment {verdict['sentiment']} | "
                                  f"{verdict['reason']}")
                        events.append(f"🚫 AI vetoed {sym}: {verdict['reason'][:90]}")
                        continue
                    if verdict["confidence"] < min_confidence:
                        store.log(sym, "AI_DOWNGRADE",
                                  f"AI lowered confidence to "
                                  f"{verdict['confidence']}/10 — below threshold | "
                                  f"{verdict['reason']}")
                        events.append(f"🔻 AI downgraded {sym} to "
                                      f"{verdict['confidence']}/10")
                        continue
                    sig["confidence"] = verdict["confidence"]
                    ai_note = (f" | AI: {verdict['sentiment']}, "
                               f"{verdict['reason']} | risk: {verdict['risk_note']}")

                qty, size_note = risk.position_size(sig["price"], sig["stop"])
                ok, verdict = risk.approve_entry(open_pos, gname,
                                                 sig["price"], qty)
                if not ok:
                    store.log(sym, "BLOCKED", f"{verdict} — {sig['reason']}")
                    continue

                store.add_position(symbol=sym, group=gname, qty=qty,
                                   entry=sig["price"], stop=sig["stop"],
                                   target=sig["target"],
                                   confidence=sig["confidence"],
                                   reason=f"{sig['reason']} | {size_note}{ai_note}")
                store.log(sym, "ENTRY",
                          f"{qty} @ ₹{sig['price']} | stop ₹{sig['stop']} | "
                          f"target ₹{sig['target']} | conf {sig['confidence']}/10 "
                          f"| {sig['reason']}{ai_note}")
                events.append(f"🟢 entered {sym}: {qty} @ ₹{sig['price']} "
                              f"(conf {sig['confidence']}/10)")

    # 4. snapshot equity
    realised = sum(t["pnl"] for t in store.closed_trades())
    unreal = 0.0
    for pos in store.open_positions():
        try:
            px = float(fetch(pos["symbol"], "1mo")["Close"].iloc[-1])
            unreal += (px - pos["entry"]) * pos["qty"]
        except Exception:
            pass
    equity = capital + realised + unreal
    store.snapshot_equity(equity)
    store.save_risk_state(risk.state)

    day_no = (date.today() - date.fromisoformat(store.meta_get("start_date"))).days + 1
    return {"day": day_no, "equity": round(equity, 2),
            "realised": round(realised, 2), "unrealised": round(unreal, 2),
            "open": len(store.open_positions()),
            "closed": len(store.closed_trades()),
            "ai_reviews": ai_reviews_used,
            "halted": risk.state.halted, "halt_reason": risk.state.halt_reason,
            "index_change": chg, "events": events}
