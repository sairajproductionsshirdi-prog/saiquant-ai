"""
kite_broker.py — REAL-MONEY execution via Zerodha Kite Connect. GATED.

Requirements before this works:
  1. Kite Connect subscription (₹2,000/month) at developers.kite.trade
  2. KITE_API_KEY and KITE_API_SECRET in .env
  3. live_trading: true in config.yaml  (keep false until paper results prove)
  4. Daily login:  python run.py --kite-login
  5. SEBI retail-algo compliance: static IP mapped to the API key, < 10
     orders/second. Orders are tagged SAIQUANT for auditability.

The gate: live orders are refused unless live_trading is true AND you type
the exact confirmation phrase at order time. The paper journal must show at
least 15 closed trades, otherwise an extra warning is shown.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

TOKEN_FILE = Path(__file__).resolve().parent.parent / "kite_token.json"
CONFIRM_PHRASE = "I ACCEPT THE RISK"


class LiveTradingBlocked(Exception):
    pass


def _kite():
    from kiteconnect import KiteConnect
    api_key = os.environ.get("KITE_API_KEY", "")
    if not api_key:
        raise LiveTradingBlocked("KITE_API_KEY missing in .env")
    return KiteConnect(api_key=api_key)


def kite_login() -> None:
    from kiteconnect import KiteConnect  # noqa: F401 — fail early if missing
    kite = _kite()
    print("\nOpen this URL, log in with Zerodha + 2FA:\n")
    print(f"  {kite.login_url()}\n")
    request_token = input("Paste the request_token from the redirect URL: ").strip()
    session = kite.generate_session(
        request_token, api_secret=os.environ["KITE_API_SECRET"])
    TOKEN_FILE.write_text(json.dumps(
        {"date": date.today().isoformat(),
         "access_token": session["access_token"]}))
    print("✅ Kite session saved (valid today only). Om Sai Ram.")


def get_session():
    if not TOKEN_FILE.exists():
        raise LiveTradingBlocked("No Kite session. Run: python run.py --kite-login")
    payload = json.loads(TOKEN_FILE.read_text())
    if payload.get("date") != date.today().isoformat():
        raise LiveTradingBlocked("Kite session expired (tokens die daily). "
                                 "Run: python run.py --kite-login")
    kite = _kite()
    kite.set_access_token(payload["access_token"])
    return kite


def check_gate(cfg: dict, paper_trade_count: int) -> list[str]:
    """Return list of warnings; raise if hard-blocked."""
    if not cfg.get("live_trading"):
        raise LiveTradingBlocked(
            "live_trading is false in config.yaml. This is your safety gate — "
            "it stays off until your paper results earn the switch.")
    warnings = []
    if paper_trade_count < 15:
        warnings.append(
            f"⚠️  Only {paper_trade_count} closed paper trades (<15). The "
            "agreed discipline is 15+ trades over ~4 weeks before live money.")
    return warnings


def place_live_order(symbol: str, side: str, qty: int,
                     intraday: bool = True) -> str:
    kite = get_session()
    order_id = kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=kite.EXCHANGE_NSE,
        tradingsymbol=symbol.upper(),
        transaction_type=(kite.TRANSACTION_TYPE_BUY if side == "BUY"
                          else kite.TRANSACTION_TYPE_SELL),
        quantity=qty,
        product=(kite.PRODUCT_MIS if intraday else kite.PRODUCT_CNC),
        order_type=kite.ORDER_TYPE_MARKET,
        tag="SAIQUANT",
    )
    return order_id
