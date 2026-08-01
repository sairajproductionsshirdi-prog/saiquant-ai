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
from datetime import date
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
            (SNAP_DIR / f"analysis_{date.today().isoformat()}.txt").write_text(
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
