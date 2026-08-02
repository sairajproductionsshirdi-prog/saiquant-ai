"""
livepaper.py — Continuous LIVE-MARKET paper trading.

    py run.py --live-paper

Runs a loop from market open to close, polling prices every few minutes:
  • enters at the price seen at decision time (not yesterday's close)
  • monitors open positions continuously — stops and targets can trigger
    intraday, not just once a day
  • trails stops as positions move up
  • squares off every position at 15:15, like a real MIS/intraday trader
  • halts on abnormal volatility or repeated data failures

Still PAPER: no broker, no order, no money. It simulates what would have
happened had you traded these signals live.

TWO HONEST LIMITATIONS — read before trusting the numbers:

1. DATA DELAY. Free Yahoo NSE data lags roughly 15 minutes. So a "fill" here
   is at a price that was true a quarter hour earlier. In fast moves your
   simulated fill will be better or worse than reality could have given you.
   Only a paid live broker feed (Kite Connect) removes this.

2. NO SLIPPAGE ON STOPS. When a stop triggers, this books the exact stop
   price. Real stops slip, especially on gaps and in small caps. Round-trip
   costs (~0.25%) are deducted, but expect live results to be somewhat worse
   than what this prints.

Neither limitation makes the exercise useless — it makes it optimistic.
Read the results as a ceiling, not a forecast.
"""

from __future__ import annotations

import time
from datetime import date, datetime, time as dtime

import yfinance as yf

from .ai_gate import review as ai_review
from .autotrader import CampaignStore, evaluate
from .indicators import ema
from .riskengine import RiskConfig, RiskEngine
from .universe import groups, resolve

MARKET_OPEN = dtime(9, 15)
SQUARE_OFF = dtime(15, 15)
MARKET_CLOSE = dtime(15, 30)
COST_PCT_PER_SIDE = 0.125


def intraday_history(symbol: str, period: str = "5d",
                     interval: str = "15m"):
    df = yf.Ticker(resolve(symbol)).history(period=period, interval=interval)
    if df is None or len(df) < 30:
        raise ValueError("insufficient intraday data")
    return df


def last_price(symbol: str) -> float:
    df = yf.Ticker(resolve(symbol)).history(period="1d", interval="5m")
    if df is None or df.empty:
        raise ValueError("no price")
    return float(df["Close"].iloc[-1])


def index_change_pct() -> float | None:
    try:
        h = yf.Ticker("^NSEI").history(period="5d", interval="1d")
        return round((float(h["Close"].iloc[-1]) /
                      float(h["Close"].iloc[-2]) - 1) * 100, 2)
    except Exception:
        return None


def in_market_hours(now: datetime | None = None) -> bool:
    t = (now or datetime.now()).time()
    return MARKET_OPEN <= t <= MARKET_CLOSE


def _monitor(store: CampaignStore, risk: RiskEngine, emit,
             price_fn, intraday_fn, force_square_off: bool = False) -> None:
    """Check every open position against the current price."""
    for pos in store.open_positions():
        try:
            price = price_fn(pos["symbol"])
            risk.note_data_success()
        except Exception as e:
            risk.note_data_failure()
            emit(f"⚠️  {pos['symbol']}: price unavailable ({str(e)[:40]})")
            continue

        high = max(pos["highest"], price)
        new_stop, moved = risk.update_trailing_stop(pos["entry"], pos["stop"],
                                                    high)
        if moved:
            store.update_position(pos["id"], highest=high, stop=new_stop)
            store.log(pos["symbol"], "TRAIL",
                      f"stop {pos['stop']} → {new_stop} (high {high:.2f})")
            emit(f"↗  {pos['symbol']} stop trailed to ₹{new_stop}")
        else:
            store.update_position(pos["id"], highest=high)

        exit_px, why = None, ""
        if force_square_off:
            exit_px, why = price, "square-off 15:15"
        elif price <= new_stop:
            exit_px, why = new_stop, "stop-loss hit intraday"
        elif price >= pos["target"]:
            exit_px, why = pos["target"], "target hit intraday"
        else:
            try:
                df = intraday_fn(pos["symbol"])
                e9, e21 = ema(df["Close"], 9), ema(df["Close"], 21)
                if e9.iloc[-1] < e21.iloc[-1]:
                    exit_px, why = price, "signal reversal (15m EMA)"
            except Exception:
                pass

        if exit_px is not None:
            gross = (exit_px - pos["entry"]) * pos["qty"]
            costs = (exit_px + pos["entry"]) * pos["qty"] * COST_PCT_PER_SIDE / 100
            pnl = round(gross - costs, 2)
            store.close_position(pos["id"], round(exit_px, 2), why, pnl)
            risk.record_realised(pnl)
            store.log(pos["symbol"], "EXIT",
                      f"{why} @ ₹{exit_px:.2f} | P&L ₹{pnl:,.0f}")
            emit(f"{'✅' if pnl >= 0 else '🔻'} closed {pos['symbol']}: "
                 f"{why}, P&L ₹{pnl:,.0f}")


def _scan(store: CampaignStore, risk: RiskEngine, emit, intraday_fn,
          use_ai: bool, ai_reviewer, min_confidence: int,
          ai_budget: list[int]) -> None:
    gmap = groups()
    for gname, syms in gmap.items():
        for sym in syms:
            if risk.state.halted:
                return
            if any(p["symbol"] == sym for p in store.open_positions()):
                continue
            try:
                df = intraday_fn(sym)
                risk.note_data_success()
            except Exception:
                risk.note_data_failure()
                continue

            sig = evaluate(sym, df)
            if not sig or sig["confidence"] < min_confidence:
                continue

            ai_note = ""
            if use_ai:
                if ai_budget[0] <= 0:
                    store.log(sym, "SKIP", "AI review budget exhausted today")
                    continue
                verdict = ai_reviewer(sig, gname)
                ai_budget[0] -= 1
                if not verdict["approved"]:
                    store.log(sym, "AI_REJECT",
                              f"{verdict['sentiment']} | {verdict['reason']}")
                    emit(f"🚫 AI vetoed {sym}: {verdict['reason'][:70]}")
                    continue
                if verdict["confidence"] < min_confidence:
                    store.log(sym, "AI_DOWNGRADE",
                              f"lowered to {verdict['confidence']}/10 | "
                              f"{verdict['reason']}")
                    continue
                sig["confidence"] = verdict["confidence"]
                ai_note = (f" | AI: {verdict['sentiment']}, {verdict['reason']}"
                           f" | risk: {verdict['risk_note']}")

            qty, size_note = risk.position_size(sig["price"], sig["stop"])
            ok, verdict_txt = risk.approve_entry(store.open_positions(), gname,
                                                 sig["price"], qty)
            if not ok:
                store.log(sym, "BLOCKED", f"{verdict_txt} — {sig['reason']}")
                continue

            store.add_position(symbol=sym, group=gname, qty=qty,
                               entry=sig["price"], stop=sig["stop"],
                               target=sig["target"],
                               confidence=sig["confidence"],
                               reason=f"{sig['reason']} | {size_note}{ai_note}")
            store.log(sym, "ENTRY",
                      f"LIVE-PAPER {qty} @ ₹{sig['price']} | stop ₹{sig['stop']} "
                      f"| target ₹{sig['target']} | conf {sig['confidence']}/10 "
                      f"| {sig['reason']}{ai_note}")
            emit(f"🟢 ENTERED {sym}: {qty} @ ₹{sig['price']} "
                 f"(stop ₹{sig['stop']}, target ₹{sig['target']}, "
                 f"conf {sig['confidence']}/10)")


def run_live(poll_minutes: int = 5, capital: float = 100_000.0,
             min_confidence: int = 7, use_ai: bool = True,
             ai_reviewer=ai_review, ai_budget_per_day: int = 8,
             price_fn=last_price, intraday_fn=intraday_history,
             index_fn=index_change_pct, emit=print,
             sleeper=time.sleep, clock=datetime.now,
             max_iterations: int | None = None) -> dict:
    """The live loop. Returns a summary when the market closes."""
    store = CampaignStore()
    if not store.meta_get("start_date"):
        store.meta_set("start_date", date.today().isoformat())
        store.meta_set("capital", capital)
    capital = float(store.meta_get("capital", capital))

    state = store.load_risk_state()
    state.roll_day()
    risk = RiskEngine(RiskConfig(capital=capital), state)
    budget = [ai_budget_per_day]

    emit(f"🕉  LIVE-MARKET PAPER TRADING — polling every {poll_minutes} min")
    emit(f"   storage: {store.backend()}")
    emit("   PAPER ONLY: no broker connected, no real orders possible.")
    emit("   Data is ~15 min delayed; treat fills as approximations.\n")

    chg = index_fn()
    risk.check_volatility(chg)
    if risk.state.halted:
        emit(f"⛔ {risk.state.halt_reason} — monitoring only, no new entries")

    iterations = 0
    while True:
        now = clock()
        t = now.time()

        if t < MARKET_OPEN:
            emit(f"⏰ {t.strftime('%H:%M')} — market opens at 09:15, waiting…")
        elif t >= MARKET_CLOSE:
            emit(f"🔔 {t.strftime('%H:%M')} — market closed. Day complete.")
            break
        else:
            square_off = t >= SQUARE_OFF
            emit(f"\n── {t.strftime('%H:%M')} ──")
            _monitor(store, risk, emit, price_fn, intraday_fn,
                     force_square_off=square_off)
            if square_off:
                emit("🔔 15:15 square-off done — no new entries after this.")
                store.save_risk_state(risk.state)
                if not store.open_positions():
                    break
            elif not risk.state.halted:
                _scan(store, risk, emit, intraday_fn, use_ai, ai_reviewer,
                      min_confidence, budget)
            else:
                emit(f"⛔ halted: {risk.state.halt_reason} (monitoring only)")

            realised = sum(x["pnl"] for x in store.closed_trades())
            emit(f"   open {len(store.open_positions())} | "
                 f"realised today ₹{risk.state.realised_today:,.0f} | "
                 f"campaign realised ₹{realised:,.0f} | "
                 f"AI budget left {budget[0]}")
            store.save_risk_state(risk.state)

        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        sleeper(poll_minutes * 60)

    realised = sum(x["pnl"] for x in store.closed_trades())
    equity = capital + realised
    store.snapshot_equity(equity)
    store.save_risk_state(risk.state)
    summary = {"equity": round(equity, 2), "realised": round(realised, 2),
               "open": len(store.open_positions()),
               "closed": len(store.closed_trades()),
               "halted": risk.state.halted,
               "ai_reviews_used": ai_budget_per_day - budget[0],
               "iterations": iterations}
    emit(f"\nDay summary: equity ₹{summary['equity']:,.0f} | "
         f"closed {summary['closed']} | open {summary['open']}")
    return summary
