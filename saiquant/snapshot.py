"""
snapshot.py — Build the daily paste-ready market snapshot.

Data source: Yahoo Finance (free). NSE symbols use the ".NS" suffix.
Daily candles are reliable and free; that's what this workflow uses.
"""

from __future__ import annotations

from datetime import date

import yfinance as yf

from .indicators import analyse_symbol
from .research import research_block

HEADER = """SAIQUANT AI — DAILY SNAPSHOT ({d})
Data: NSE daily candles (Yahoo Finance, free). All prices in ₹.
Paste this snapshot together with ANALYST_PROMPT.md into Claude/ChatGPT.
"""


from .universe import resolve


def fetch_daily(symbol: str, period: str = "6mo", interval: str = "1d"):
    t = yf.Ticker(resolve(symbol))
    if interval != "1d":
        period = "1mo"
    df = t.history(period=period, interval=interval)
    if df is None or len(df) < 60:
        raise ValueError(f"not enough data for {symbol}")
    return df


def build_snapshot(watchlist: list[str], fetch=fetch_daily,
                   interval: str = "1d", label: str = "") -> str:
    lines = [HEADER.format(d=date.today().isoformat())]
    if label:
        lines.append(f"GROUP: {label} | CANDLES: "
                     f"{'15-minute (INTRADAY)' if interval != '1d' else 'daily (positional)'}\n")
    for symbol in watchlist:
        try:
            df = fetch(symbol, interval=interval)
            s = analyse_symbol(df)
        except Exception as e:
            lines.append(f"--- {symbol}: DATA ERROR ({e}) ---\n")
            continue
        lines.append(
            f"--- {symbol} ---\n"
            f"Close: ₹{s['close']}  ({s['change_pct']:+}% today)\n"
            f"EMA9: {s['ema9']} | EMA21: {s['ema21']} | EMA50: {s['ema50']}\n"
            f"Crossover state: {s['cross']}\n"
            f"RSI(14): {s['rsi14']}\n"
            f"MACD histogram: {s['macd_hist']} ({s['macd_state']})\n"
            f"Volume vs 20-day avg: {s['vol_ratio']}x\n"
            f"20-day high/low: ₹{s['high20']} / ₹{s['low20']}\n"
            f"{research_block(symbol)}\n"
        )
    return "\n".join(lines)
