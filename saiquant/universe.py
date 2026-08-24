"""
universe.py — watchlist groups, indices, and ticker resolution.
"""

from __future__ import annotations

from pathlib import Path

import yaml

CFG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_cfg() -> dict:
    return yaml.safe_load(open(CFG_PATH, encoding="utf-8"))


def groups() -> dict[str, list[str]]:
    return load_cfg().get("groups", {})


def indices() -> dict[str, str]:
    return load_cfg().get("indices", {})


def all_symbols() -> list[str]:
    out: list[str] = []
    for syms in groups().values():
        out.extend(s for s in syms if s not in out)
    return out


def resolve(symbol: str) -> str:
    """Yahoo ticker for a symbol: indices pass through raw (^NSEI),
    equities get the .NS suffix."""
    if symbol.startswith("^"):
        return symbol
    return f"{symbol}.NS"


def horizon() -> str:
    return str(load_cfg().get("horizon", "positional")).lower()


def is_intraday() -> bool:
    return horizon() == "intraday"


def signal_interval() -> str:
    return str(load_cfg().get("signal_interval", "1d"))


def max_holding_days() -> int:
    try:
        return int(load_cfg().get("max_holding_days", 20))
    except (TypeError, ValueError):
        return 20
