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


@app.route("/api/action/analyse", methods=["POST"])
def action_analyse():
    if not _check_password():
        return _deny()
    body = request.json or {}
    group = body.get("group", "bluechip")
    intraday = bool(body.get("intraday"))

    from .universe import groups, all_symbols
    from .snapshot import build_snapshot
    from .ai_analyst import analyse, AIAnalystError

    try:
        syms = all_symbols() if group == "all" else groups()[group]
    except KeyError:
        return jsonify({"error": f"unknown group {group}"}), 400

    try:
        text = build_snapshot(syms, interval=("15m" if intraday else "1d"),
                              label=group.upper())
        report = analyse(text, intraday=intraday)
    except AIAnalystError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        return jsonify({"error": f"snapshot/data error: {e}"}), 502

    try:
        SNAP_DIR.mkdir(exist_ok=True)
        (SNAP_DIR / f"analysis_{date.today().isoformat()}.txt").write_text(
            report, encoding="utf-8")
    except OSError:
        pass  # ephemeral disk hiccup — still return the report

    return jsonify({"report": report})


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
