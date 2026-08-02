#!/usr/bin/env python3
"""
migrate_to_cloud.py — Copy an existing local campaign.db into cloud Postgres.

Usage (from the project folder, with DATABASE_URL set to your cloud database):

    Windows:  set DATABASE_URL=postgresql://...   &&  py migrate_to_cloud.py
    Mac/Linux: DATABASE_URL=postgresql://... python migrate_to_cloud.py

Safe to run more than once: it refuses to overwrite a cloud campaign that
already has data, so you can never silently destroy a running campaign.
"""

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from saiquant.db import Database, init_schema  # noqa: E402

LOCAL = Path(__file__).parent / "campaign.db"


def main() -> None:
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set — nothing to migrate to.")
        return
    if not LOCAL.exists():
        print("No local campaign.db found — nothing to migrate.")
        return

    cloud = Database()
    init_schema(cloud)

    existing = cloud.fetchone("SELECT COUNT(*) FROM positions")
    if existing and existing[0]:
        print(f"Cloud database already has {existing[0]} positions. "
              "Refusing to overwrite. Delete them first if you really "
              "want a fresh migration.")
        return

    src = sqlite3.connect(str(LOCAL))
    moved = {}

    rows = src.execute("SELECT k, v FROM meta").fetchall()
    for k, v in rows:
        cloud.upsert("meta", "k", k, "v", v)
    moved["meta"] = len(rows)

    rows = src.execute(
        "SELECT symbol,grp,qty,entry,stop,target,highest,opened,reason,"
        "confidence,status,exit,closed,exit_reason,pnl FROM positions").fetchall()
    for r in rows:
        cloud.execute(
            "INSERT INTO positions (symbol,grp,qty,entry,stop,target,highest,"
            "opened,reason,confidence,status,exit,closed,exit_reason,pnl) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", r)
    moved["positions"] = len(rows)

    rows = src.execute("SELECT ts,symbol,action,detail FROM decisions").fetchall()
    for r in rows:
        cloud.execute("INSERT INTO decisions VALUES (?,?,?,?)", r)
    moved["decisions"] = len(rows)

    rows = src.execute("SELECT day, value FROM equity").fetchall()
    for day, value in rows:
        cloud.upsert("equity", "day", day, "value", value)
    moved["equity days"] = len(rows)

    src.close()
    print("Migration complete. Copied:")
    for k, v in moved.items():
        print(f"  {v:>4} {k}")
    print("\nYour campaign now lives in the cloud. Om Sai Ram. 🙏")


if __name__ == "__main__":
    main()
