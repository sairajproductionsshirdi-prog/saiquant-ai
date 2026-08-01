"""
indicators.py — Technical indicators computed from OHLCV DataFrames.
"""

from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    fast = ema(series, 12)
    slow = ema(series, 26)
    line = fast - slow
    signal = line.ewm(span=9, adjust=False).mean()
    return line, signal, line - signal


def analyse_symbol(df: pd.DataFrame) -> dict:
    """Compute a full indicator snapshot for one symbol's daily OHLCV data."""
    close, vol = df["Close"], df["Volume"]
    e9, e21, e50 = ema(close, 9), ema(close, 21), ema(close, 50)
    r = rsi(close)
    m_line, m_sig, m_hist = macd(close)

    last = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    high20 = float(df["High"].tail(20).max())
    low20 = float(df["Low"].tail(20).min())
    vol_ratio = float(vol.iloc[-1] / max(1, vol.tail(20).mean()))

    # simple crossover state
    diff_now = e9.iloc[-1] - e21.iloc[-1]
    diff_prev = e9.iloc[-2] - e21.iloc[-2]
    if diff_prev <= 0 < diff_now:
        cross = "FRESH BULLISH CROSS (EMA9 above EMA21 today)"
    elif diff_prev >= 0 > diff_now:
        cross = "FRESH BEARISH CROSS (EMA9 below EMA21 today)"
    else:
        cross = "EMA9 above EMA21" if diff_now > 0 else "EMA9 below EMA21"

    return {
        "close": round(last, 2),
        "change_pct": round((last - prev) / prev * 100, 2),
        "ema9": round(float(e9.iloc[-1]), 2),
        "ema21": round(float(e21.iloc[-1]), 2),
        "ema50": round(float(e50.iloc[-1]), 2),
        "rsi14": round(float(r.iloc[-1]), 1),
        "macd_hist": round(float(m_hist.iloc[-1]), 2),
        "macd_state": "bullish" if m_hist.iloc[-1] > 0 else "bearish",
        "vol_ratio": round(vol_ratio, 2),
        "high20": round(high20, 2),
        "low20": round(low20, 2),
        "cross": cross,
    }
