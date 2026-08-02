"""
backtest.py — Historical testing for SaiQuant AI's rule-based strategy.

    py run.py --backtest --group multibagger --years 3

What it tests: the mechanical rules (EMA crossover + volume filter, with
stop-loss and target), which is the part of SaiQuant AI that CAN be tested
honestly on history.

What it cannot test: the AI's news/sentiment/analyst-poll judgement. Historic
news snapshots aren't available, and an LLM reading today's data about a past
date would be contaminated by hindsight — that is called look-ahead bias and
it makes backtests lie. So treat these numbers as the floor: the mechanical
edge, before AI filtering.

Costs modelled (approximate Indian retail delivery/CNC costs):
  brokerage ₹0 (Zerodha delivery), STT 0.1% each side, exchange+SEBI+stamp
  ~0.012%, GST 18% on charges, and 0.05% slippage per side. Total ~0.25%
  round trip. Intraday costs differ; this models positional/CNC.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import yfinance as yf

from .indicators import ema, rsi
from .universe import resolve

COST_PER_SIDE_PCT = 0.125  # ~0.25% round trip including slippage


@dataclass
class Trade:
    symbol: str
    entry_date: str
    entry: float
    exit_date: str
    exit: float
    reason: str
    pnl_pct: float
    holding_days: int


def fetch_history(symbol: str, years: int = 3) -> pd.DataFrame:
    df = yf.Ticker(resolve(symbol)).history(period=f"{years}y", interval="1d")
    if df is None or len(df) < 120:
        raise ValueError(f"insufficient history for {symbol}")
    return df


def backtest_symbol(symbol: str, df: pd.DataFrame, fast: int = 9, slow: int = 21,
                    min_vol_ratio: float = 1.5, stop_pct: float = 5.0,
                    target_pct: float = 12.0,
                    max_holding_days: int = 40) -> list[Trade]:
    """Long-only swing test. Signals use only data available up to that bar;
    entries fill at the NEXT bar's open (no look-ahead)."""
    close, vol = df["Close"], df["Volume"]
    e_fast, e_slow = ema(close, fast), ema(close, slow)
    r = rsi(close)
    vol_avg = vol.rolling(20).mean()
    dates = df.index

    trades: list[Trade] = []
    in_pos = False
    entry_i = 0
    entry_px = 0.0

    for i in range(slow + 21, len(df) - 1):
        if not in_pos:
            cross = (e_fast.iloc[i - 1] <= e_slow.iloc[i - 1]
                     and e_fast.iloc[i] > e_slow.iloc[i])
            # volume confirmation: any of the last 3 bars shows the surge
            # (demanding it on the exact crossover bar is unrealistically strict)
            recent_vol = vol.iloc[max(0, i - 2):i + 1]
            vol_ok = (recent_vol >= min_vol_ratio * (vol_avg.iloc[i] or 1)).any()
            rsi_ok = r.iloc[i] < 70          # don't chase overbought
            if cross and vol_ok and rsi_ok:
                entry_px = float(df["Open"].iloc[i + 1])   # next-bar fill
                entry_i = i + 1
                in_pos = True
            continue

        # in position — check exits on this bar
        low, high = float(df["Low"].iloc[i]), float(df["High"].iloc[i])
        stop_px = entry_px * (1 - stop_pct / 100)
        target_px = entry_px * (1 + target_pct / 100)
        exit_px, reason = None, ""

        if low <= stop_px:                      # stop assumed hit first (conservative)
            exit_px, reason = stop_px, "stop-loss"
        elif high >= target_px:
            exit_px, reason = target_px, "target"
        elif e_fast.iloc[i] < e_slow.iloc[i]:
            exit_px, reason = float(df["Close"].iloc[i]), "EMA exit"
        elif i - entry_i >= max_holding_days:
            exit_px, reason = float(df["Close"].iloc[i]), "time exit"

        if exit_px is not None:
            gross = (exit_px - entry_px) / entry_px * 100
            net = gross - 2 * COST_PER_SIDE_PCT
            trades.append(Trade(
                symbol=symbol,
                entry_date=str(dates[entry_i].date()), entry=round(entry_px, 2),
                exit_date=str(dates[i].date()), exit=round(exit_px, 2),
                reason=reason, pnl_pct=round(net, 2),
                holding_days=int(i - entry_i)))
            in_pos = False

    return trades


def summarise(trades: list[Trade]) -> dict:
    if not trades:
        return {"trades": 0}
    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    win_rate = len(wins) / len(pnls)

    # expectancy per trade in %, and equity curve for max drawdown
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for p in pnls:
        equity *= (1 + p / 100)
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1)

    return {
        "trades": len(pnls),
        "win_rate": round(win_rate * 100, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(expectancy, 2),
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else None,
        "total_return_compounded": round((equity - 1) * 100, 1),
        "max_drawdown": round(max_dd * 100, 1),
        "avg_holding_days": round(sum(t.holding_days for t in trades) / len(trades), 1),
        "best": round(max(pnls), 2),
        "worst": round(min(pnls), 2),
    }


def run(symbols: list[str], years: int = 3, fetch=fetch_history,
        progress=None, **params) -> tuple[list[Trade], dict, dict]:
    all_trades: list[Trade] = []
    per_symbol: dict[str, dict] = {}
    for i, sym in enumerate(symbols, 1):
        if progress:
            progress(i, len(symbols), sym)
        try:
            df = fetch(sym, years)
            t = backtest_symbol(sym, df, **params)
            all_trades.extend(t)
            per_symbol[sym] = summarise(t)
        except Exception as e:
            per_symbol[sym] = {"error": str(e)[:60]}
    return all_trades, summarise(all_trades), per_symbol
