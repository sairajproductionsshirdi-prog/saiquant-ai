"""
paperbook.py — Paper-trading journal (SQLite).

You log the trades you *would* have taken after reading the AI analysis:

    python run.py --buy RELIANCE 2845 3 "AI: strong setup, SL 2790"
    python run.py --sell RELIANCE 2892
    python run.py --report

Open positions are marked to the latest close so you always see honest P&L.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "paper_journal.db"


class PaperBook:
    def __init__(self):
        self.conn = sqlite3.connect(DB)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opened TEXT, closed TEXT,
                symbol TEXT, qty INTEGER,
                entry REAL, exit REAL, pnl REAL,
                note TEXT, status TEXT DEFAULT 'OPEN')"""
        )
        self.conn.commit()

    def buy(self, symbol: str, price: float, qty: int, note: str = "") -> None:
        self.conn.execute(
            "INSERT INTO trades (opened,symbol,qty,entry,note) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(timespec="minutes"), symbol.upper(),
             qty, price, note))
        self.conn.commit()

    def sell(self, symbol: str, price: float) -> float | None:
        row = self.conn.execute(
            "SELECT id, qty, entry FROM trades "
            "WHERE symbol=? AND status='OPEN' ORDER BY id LIMIT 1",
            (symbol.upper(),)).fetchone()
        if not row:
            return None
        tid, qty, entry = row
        pnl = (price - entry) * qty
        self.conn.execute(
            "UPDATE trades SET closed=?, exit=?, pnl=?, status='CLOSED' WHERE id=?",
            (datetime.now().isoformat(timespec="minutes"), price, pnl, tid))
        self.conn.commit()
        return pnl

    def open_positions(self) -> list[tuple]:
        return self.conn.execute(
            "SELECT symbol, qty, entry, opened, note FROM trades "
            "WHERE status='OPEN'").fetchall()

    def closed_trades(self) -> list[tuple]:
        return self.conn.execute(
            "SELECT symbol, qty, entry, exit, pnl, opened, closed, note "
            "FROM trades WHERE status='CLOSED' ORDER BY closed DESC").fetchall()

    def stats(self) -> dict:
        rows = self.conn.execute(
            "SELECT pnl FROM trades WHERE status='CLOSED'").fetchall()
        pnls = [r[0] for r in rows]
        wins = [p for p in pnls if p > 0]
        return {
            "trades": len(pnls),
            "wins": len(wins),
            "win_rate": round(100 * len(wins) / len(pnls), 1) if pnls else 0.0,
            "total_pnl": round(sum(pnls), 2),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(p for p in pnls if p <= 0) /
                              max(1, len(pnls) - len(wins)), 2),
        }
