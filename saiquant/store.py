from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .models import Proposal, ProposalStatus


class Store:
    def __init__(self, path: str | Path = "saiquant.db") -> None:
        self.path = str(path)
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS proposals (
              id TEXT PRIMARY KEY, symbol TEXT NOT NULL, exchange TEXT NOT NULL,
              status TEXT NOT NULL, quantity INTEGER NOT NULL, entry REAL NOT NULL,
              stop_loss REAL NOT NULL, target REAL NOT NULL, value REAL NOT NULL,
              risk REAL NOT NULL, max_price REAL NOT NULL, reasons TEXT NOT NULL,
              created_at TEXT NOT NULL, approved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO settings(key,value) VALUES('killed','0');
            """)

    def save_proposal(self, p: Proposal) -> None:
        with self.connect() as db:
            db.execute("""INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                p.id, p.signal.symbol, p.signal.exchange, p.status.value, p.quantity,
                p.signal.price, p.signal.stop_loss, p.signal.target, p.estimated_value,
                p.planned_risk, p.max_acceptable_price, json.dumps(p.signal.reasons),
                p.created_at.isoformat(), p.approved_at.isoformat() if p.approved_at else None,
            ))

    def set_status(self, proposal_id: str, status: ProposalStatus) -> None:
        approved = datetime.now(timezone.utc).isoformat() if status is ProposalStatus.APPROVED else None
        with self.connect() as db:
            cur = db.execute(
                "UPDATE proposals SET status=?, approved_at=COALESCE(?,approved_at) WHERE id=?",
                (status.value, approved, proposal_id),
            )
            if cur.rowcount != 1:
                raise KeyError("Proposal not found")

    def list_proposals(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM proposals ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def get(self, proposal_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        if row is None:
            raise KeyError("Proposal not found")
        return dict(row)

    def set_killed(self, killed: bool) -> None:
        with self.connect() as db:
            db.execute("UPDATE settings SET value=? WHERE key='killed'", ("1" if killed else "0",))

    def is_killed(self) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='killed'").fetchone()
        return bool(row and row[0] == "1")
