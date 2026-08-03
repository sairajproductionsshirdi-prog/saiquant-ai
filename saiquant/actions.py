"""
actions.py — Web commands for SaiQuant AI: run AI analysis and log paper
trades directly from the dashboard (works on the Render deployment too).

Security: every action requires the password set in the ACTION_PASSWORD
environment variable. Without that variable set, actions are disabled and
the dashboard stays view-only (safe default for a public URL).

Cloud note: on Render's free tier the disk is ephemeral — analysis results
and journal entries survive the session but reset when the service restarts.
Your PC remains the permanent record; the cloud is your remote control.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def today_ist():
    return datetime.now(IST).date()
from pathlib import Path

from flask import jsonify, request

from .dashboard import app
from .paperbook import PaperBook

SNAP_DIR = Path(__file__).resolve().parent.parent / "snapshots"


def _check_password() -> bool:
    expected = os.environ.get("ACTION_PASSWORD", "")
    if not expected:
        return False
    supplied = (request.json or {}).get("password", "")
    return supplied == expected


def _deny():
    if not os.environ.get("ACTION_PASSWORD"):
        return jsonify({"error": "Actions disabled: ACTION_PASSWORD is not set "
                                 "in environment variables."}), 403
    return jsonify({"error": "Wrong password."}), 403


# ── background analysis jobs (avoids web timeouts on slow free tiers) ────
_JOBS: dict[str, dict] = {}


def _run_analysis_job(job_id: str, group: str, intraday: bool) -> None:
    from .universe import groups, all_symbols
    from .snapshot import build_snapshot
    from .ai_analyst import analyse, AIAnalystError
    job = _JOBS[job_id]
    try:
        syms = all_symbols() if group == "all" else groups()[group]
        def prog(i, n, sym):
            job["status"] = f"researching {sym} ({i}/{n})…"
        text = build_snapshot(syms, interval=("15m" if intraday else "1d"),
                              label=group.upper(), progress=prog)
        job["status"] = "asking the AI analyst…"
        report = analyse(text, intraday=intraday)
        try:
            SNAP_DIR.mkdir(exist_ok=True)
            (SNAP_DIR / f"analysis_{today_ist().isoformat()}.txt").write_text(
                report, encoding="utf-8")
        except OSError:
            pass
        job.update({"state": "done", "report": report})
    except AIAnalystError as e:
        job.update({"state": "error", "error": str(e)})
    except Exception as e:
        job.update({"state": "error", "error": f"data/research error: {e}"})


@app.route("/api/action/analyse", methods=["POST"])
def action_analyse():
    """Start a background analysis job; returns a job id to poll."""
    if not _check_password():
        return _deny()
    body = request.json or {}
    group = body.get("group", "bluechip")
    intraday = bool(body.get("intraday"))

    # prune old jobs
    now = time.time()
    for k in [k for k, v in _JOBS.items() if now - v["t"] > 3600]:
        _JOBS.pop(k, None)

    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {"state": "running", "status": "starting…", "t": now}
    threading.Thread(target=_run_analysis_job,
                     args=(job_id, group, intraday), daemon=True).start()
    return jsonify({"job_id": job_id})


def _run_backtest_job(job_id: str, group: str, years: int,
                      stop: float, target: float) -> None:
    from .universe import groups, all_symbols
    from .backtest import run as bt_run
    job = _JOBS[job_id]
    try:
        syms = all_symbols() if group == "all" else groups()[group]

        def prog(i, n, sym):
            job["status"] = f"backtesting {sym} ({i}/{n})…"

        trades, overall, per_sym = bt_run(syms, years=years, progress=prog,
                                          stop_pct=stop, target_pct=target)
        if not overall.get("trades"):
            job.update({"state": "done",
                        "report": "No trades triggered on this group/period. "
                                  "Try more years or another group."})
            return

        lines = [f"BACKTEST — {group.upper()} | {years}y | "
                 f"stop {stop}% / target {target}%",
                 "(mechanical rules only; AI news judgement is NOT backtestable)",
                 "", "Per stock:"]
        for sym, s in per_sym.items():
            if s.get("error"):
                lines.append(f"  {sym:<12} — {s['error']}")
            elif s.get("trades"):
                lines.append(
                    f"  {sym:<12} {s['trades']:>3} trades | win {s['win_rate']:>5}% "
                    f"| exp {s['expectancy']:+.2f}% | total {s['total_return_compounded']:+.1f}% "
                    f"| maxDD {s['max_drawdown']:.1f}%")
            else:
                lines.append(f"  {sym:<12}   no trades")
        lines += [
            "", f"OVERALL — {overall['trades']} trades",
            f"  Win rate         : {overall['win_rate']}%",
            f"  Avg win / loss   : +{overall['avg_win']}% / {overall['avg_loss']}%",
            f"  Expectancy/trade : {overall['expectancy']}%   <- the number that matters",
            f"  Profit factor    : {overall['profit_factor']}",
            f"  Max drawdown     : {overall['max_drawdown']}%",
            f"  Avg holding      : {overall['avg_holding_days']} days",
            "",
            ("VERDICT: positive expectancy — worth paper trading forward."
             if overall["expectancy"] > 0 else
             "VERDICT: negative expectancy — these rules would have LOST money. "
             "Do not trade live."),
            "",
            "Costs ~0.25% round trip included. Under ~20 trades is noise, not "
            "evidence. Past results never guarantee future ones.",
        ]
        job.update({"state": "done", "report": "\n".join(lines)})
    except Exception as e:
        job.update({"state": "error", "error": f"backtest error: {e}"})


def _run_auto_job(job_id: str) -> None:
    from .autotrader import run_cycle
    job = _JOBS[job_id]
    try:
        def prog(i, n, sym):
            job["status"] = f"scanning {sym} ({i}/{n})…"
        r = run_cycle(progress=prog)
        lines = [f"AUTONOMOUS PAPER CYCLE — day {r['day']}",
                 f"Equity ₹{r['equity']:,.0f} | realised ₹{r['realised']:,.0f} "
                 f"| unrealised ₹{r['unrealised']:,.0f}",
                 f"Open {r['open']} | Closed {r['closed']} | "
                 f"Nifty {r['index_change']}%", ""]
        if r["halted"]:
            lines.append(f"⛔ TRADING HALTED: {r['halt_reason']}")
        lines += (r["events"] or ["No actions today — patience is a position."])
        lines += ["", "PAPER MODE ONLY — no real orders were or can be placed."]
        job.update({"state": "done", "report": "\n".join(lines)})
    except Exception as e:
        job.update({"state": "error", "error": f"cycle error: {e}"})


@app.route("/api/action/auto", methods=["POST"])
def action_auto():
    if not _check_password():
        return _deny()
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {"state": "running", "status": "starting cycle…",
                     "t": time.time()}
    threading.Thread(target=_run_auto_job, args=(job_id,), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/cron/tick")
def cron_tick():
    """One live-market pass, callable by an external scheduler.

    Secured by CRON_TOKEN (set it in Render's Environment tab):
        https://your-app.onrender.com/api/cron/tick?token=YOUR_TOKEN

    Point a free scheduler (cron-job.org) at this every 5 minutes,
    Mon-Fri 09:15-15:30 IST. Each call monitors open positions, then scans
    for entries — the same work the local --live-paper loop does per tick.
    The pings also keep the free Render service awake during market hours.

    PAPER ONLY: no broker, no real orders.
    """
    expected = os.environ.get("CRON_TOKEN", "")
    if not expected:
        return jsonify({"error": "CRON_TOKEN not configured"}), 403
    if request.args.get("token", "") != expected:
        return jsonify({"error": "bad token"}), 403

    from .livepaper import in_market_hours, now_ist, run_live
    ist = now_ist()
    if not in_market_hours():
        return jsonify({"skipped": "outside market hours (09:15-15:30 IST)",
                        "ist_time": ist.strftime("%Y-%m-%d %H:%M IST")})

    events: list[str] = []
    try:
        summary = run_live(emit=events.append, max_iterations=1,
                           sleeper=lambda s: None)
    except Exception as e:
        return jsonify({"error": f"tick failed: {e}"}), 500
    return jsonify({"ok": True, "ist_time": ist.strftime("%Y-%m-%d %H:%M IST"),
                    "events": events, **summary})


@app.route("/api/activity")
def api_activity():
    """Recent bot + AI decisions, for the live activity feed."""
    from .autotrader import CampaignStore
    try:
        n = max(1, min(100, int(request.args.get("n", 30))))
    except (TypeError, ValueError):
        n = 30
    rows = CampaignStore().recent_decisions(n)
    return jsonify({"events": [
        {"ts": r[0], "symbol": r[1], "action": r[2], "detail": r[3]}
        for r in rows]})


@app.route("/api/campaign")
def api_campaign():
    from .autotrader import CampaignStore
    from .metrics import campaign_report
    store = CampaignStore()
    start = store.meta_get("start_date")
    if not start:
        return jsonify({"active": False})
    capital = float(store.meta_get("capital", 100000))
    rep = campaign_report(capital, store.closed_trades(),
                          store.equity_series(), start,
                          len(store.open_positions()))
    from datetime import date as _d
    rep["day"] = (today_ist() - _d.fromisoformat(start)).days + 1
    rep["active"] = True
    rep["storage"] = store.backend()
    rep["positions"] = store.open_positions()
    return jsonify(rep)


@app.route("/api/action/backtest", methods=["POST"])
def action_backtest():
    if not _check_password():
        return _deny()
    body = request.json or {}
    group = body.get("group", "multibagger")
    try:
        years = max(1, min(10, int(body.get("years", 3))))
        stop = float(body.get("stop", 5))
        target = float(body.get("target", 12))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid years/stop/target"}), 400

    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {"state": "running", "status": "starting backtest…",
                     "t": time.time()}
    threading.Thread(target=_run_backtest_job,
                     args=(job_id, group, years, stop, target),
                     daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/action/result/<job_id>")
def action_result(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"error": "unknown or expired job"}), 404
    if job["state"] == "running":
        return jsonify({"state": "running", "status": job["status"]})
    if job["state"] == "error":
        return jsonify({"state": "error", "error": job["error"]})
    return jsonify({"state": "done", "report": job["report"]})


@app.route("/api/action/trade", methods=["POST"])
def action_trade():
    if not _check_password():
        return _deny()
    body = request.json or {}
    side = body.get("side")
    symbol = (body.get("symbol") or "").strip().upper()
    try:
        price = float(body.get("price"))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid price"}), 400
    note = (body.get("note") or "").strip()

    if not symbol or side not in ("BUY", "SELL"):
        return jsonify({"error": "symbol and side (BUY/SELL) required"}), 400

    book = PaperBook()
    if side == "BUY":
        try:
            qty = int(body.get("qty"))
            assert qty > 0
        except (TypeError, ValueError, AssertionError):
            return jsonify({"error": "invalid qty"}), 400
        book.buy(symbol, price, qty, note)
        return jsonify({"ok": f"PAPER BUY {qty} {symbol} @ ₹{price}"})

    pnl = book.sell(symbol, price)
    if pnl is None:
        return jsonify({"error": f"no open paper position in {symbol}"}), 404
    return jsonify({"ok": f"PAPER SELL {symbol} @ ₹{price} → P&L ₹{pnl:,.0f}",
                    "pnl": pnl})
