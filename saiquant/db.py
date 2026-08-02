"""
db.py — One storage layer, two backends.

  • No DATABASE_URL set  → SQLite file on disk (your PC, as before)
  • DATABASE_URL set     → PostgreSQL (free Neon/Supabase tier, permanent)

Render's free tier has no persistent disk, so SQLite there is wiped on every
restart. Pointing DATABASE_URL at a free cloud Postgres makes the campaign
permanent and shared across every device.

The adapter smooths over the two dialects:
  - placeholders:  SQLite uses ?   Postgres uses %s
  - autoincrement: SQLite uses INTEGER PRIMARY KEY AUTOINCREMENT
                   Postgres uses SERIAL PRIMARY KEY
  - upsert:        both support ON CONFLICT ... DO UPDATE
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_SQLITE = Path(__file__).resolve().parent.parent / "campaign.db"


def database_url() -> str | None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    # Some providers hand out the legacy postgres:// scheme
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


class Database:
    """Thin wrapper: write SQL with ? placeholders, it translates if needed."""

    def __init__(self, sqlite_path: Path | None = None):
        self.url = database_url()
        self.is_postgres = self.url is not None
        if self.is_postgres:
            import psycopg
            self.conn = psycopg.connect(self.url, autocommit=True)
        else:
            path = sqlite_path or DEFAULT_SQLITE
            self.conn = sqlite3.connect(str(path), check_same_thread=False)

    # ── dialect helpers ─────────────────────────────────────────────────
    def _sql(self, sql: str) -> str:
        if self.is_postgres:
            sql = sql.replace("?", "%s")
            sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                              "SERIAL PRIMARY KEY")
            sql = sql.replace("INSERT OR REPLACE INTO", "INSERT INTO")
        return sql

    def execute(self, sql: str, params: tuple = ()):
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), params)
        if not self.is_postgres:
            self.conn.commit()
        return cur

    def fetchall(self, sql: str, params: tuple = ()) -> list[tuple]:
        cur = self.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return [tuple(r) for r in rows]

    def fetchone(self, sql: str, params: tuple = ()):
        cur = self.execute(sql, params)
        row = cur.fetchone()
        cur.close()
        return tuple(row) if row else None

    def upsert(self, table: str, key_col: str, key_val, value_col: str,
               value_val) -> None:
        """Portable INSERT ... ON CONFLICT DO UPDATE."""
        self.execute(
            f"INSERT INTO {table} ({key_col}, {value_col}) VALUES (?, ?) "
            f"ON CONFLICT ({key_col}) DO UPDATE SET {value_col} = ?",
            (key_val, value_val, value_val))

    def insert_returning_id(self, sql: str, params: tuple) -> int | None:
        """INSERT that needs the new row id (dialects differ)."""
        if self.is_postgres:
            row = self.fetchone(sql + " RETURNING id", params)
            return row[0] if row else None
        cur = self.execute(sql, params)
        return cur.lastrowid

    def backend_name(self) -> str:
        return "PostgreSQL (permanent cloud)" if self.is_postgres \
            else "SQLite (local file)"

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


SCHEMA = [
    """CREATE TABLE IF NOT EXISTS meta (
        k TEXT PRIMARY KEY, v TEXT)""",
    """CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, grp TEXT, qty INTEGER,
        entry REAL, stop REAL, target REAL, highest REAL,
        opened TEXT, reason TEXT, confidence INTEGER,
        status TEXT DEFAULT 'OPEN',
        exit REAL, closed TEXT, exit_reason TEXT, pnl REAL)""",
    """CREATE TABLE IF NOT EXISTS decisions (
        ts TEXT, symbol TEXT, action TEXT, detail TEXT)""",
    """CREATE TABLE IF NOT EXISTS equity (
        day TEXT PRIMARY KEY, value REAL)""",
]


def init_schema(db: Database) -> None:
    for stmt in SCHEMA:
        db.execute(stmt)
