"""
metrics.py — Performance measurement for the paper-trading campaign.

Includes the number most backtests hide: the BUY-AND-HOLD BENCHMARK.
A strategy that returns less than simply holding the index has not earned
its complexity, however good its win rate looks.
"""

from __future__ import annotations

import math
from datetime import date, datetime

TRADING_DAYS = 252
RISK_FREE_ANNUAL = 0.065  # ~6.5% Indian risk-free rate; adjust if you like


def equity_curve(starting_capital: float, closed_pnls: list[float]) -> list[float]:
    eq, out = starting_capital, [starting_capital]
    for p in closed_pnls:
        eq += p
        out.append(eq)
    return out


def max_drawdown(curve: list[float]) -> float:
    peak, mdd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1)
    return round(mdd * 100, 2)


def sharpe_ratio(daily_returns: list[float]) -> float | None:
    """Annualised Sharpe from daily fractional returns. Needs >= 5 days."""
    if len(daily_returns) < 5:
        return None
    mean = sum(daily_returns) / len(daily_returns)
    var = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return None
    rf_daily = RISK_FREE_ANNUAL / TRADING_DAYS
    return round((mean - rf_daily) / sd * math.sqrt(TRADING_DAYS), 2)


def trade_stats(closed: list[dict]) -> dict:
    """closed: list of dicts with 'pnl' (₹) and optionally 'pnl_pct'."""
    if not closed:
        return {"trades": 0}
    pnls = [c["pnl"] for c in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    wr = len(wins) / len(pnls)
    return {
        "trades": len(pnls),
        "win_rate": round(wr * 100, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(wr * avg_win + (1 - wr) * avg_loss, 2),
        "profit_factor": (round(sum(wins) / abs(sum(losses)), 2)
                          if losses else None),
        "total_pnl": round(sum(pnls), 2),
        "best": round(max(pnls), 2),
        "worst": round(min(pnls), 2),
    }


def benchmark_return(start_date: str, index_ticker: str = "^NSEI") -> dict:
    """Buy-and-hold return of the index over the campaign period."""
    try:
        import yfinance as yf
        d0 = datetime.fromisoformat(start_date).date()
        days = max(5, (date.today() - d0).days + 5)
        h = yf.Ticker(index_ticker).history(period=f"{days}d", interval="1d")
        if h is None or len(h) < 2:
            return {"available": False}
        first, last = float(h["Close"].iloc[0]), float(h["Close"].iloc[-1])
        return {"available": True, "index": index_ticker,
                "return_pct": round((last - first) / first * 100, 2),
                "from": str(h.index[0].date()), "to": str(h.index[-1].date())}
    except Exception:
        return {"available": False}


def campaign_report(capital: float, closed: list[dict],
                    daily_equity: list[tuple[str, float]],
                    start_date: str, open_positions: int = 0) -> dict:
    stats = trade_stats(closed)
    curve = equity_curve(capital, [c["pnl"] for c in closed])
    final = curve[-1]

    daily_rets = []
    for i in range(1, len(daily_equity)):
        prev = daily_equity[i - 1][1]
        if prev:
            daily_rets.append((daily_equity[i][1] - prev) / prev)

    bench = benchmark_return(start_date)
    strat_pct = round((final - capital) / capital * 100, 2)

    verdict_bits = []
    if stats.get("trades", 0) < 15:
        verdict_bits.append(
            f"Only {stats.get('trades', 0)} closed trades — too few to judge. "
            "Statistical noise dominates below ~20 trades.")
    if stats.get("expectancy") is not None and stats.get("trades"):
        verdict_bits.append(
            "Expectancy per trade is "
            f"{'positive' if stats['expectancy'] > 0 else 'negative'} "
            f"(₹{stats['expectancy']:,.0f}).")
    if bench.get("available"):
        diff = strat_pct - bench["return_pct"]
        verdict_bits.append(
            f"Strategy {strat_pct:+.2f}% vs buy-and-hold Nifty "
            f"{bench['return_pct']:+.2f}% → "
            f"{'BEAT' if diff > 0 else 'UNDERPERFORMED'} benchmark by "
            f"{abs(diff):.2f} points.")

    return {
        "start_date": start_date,
        "capital": capital,
        "final_equity": round(final, 2),
        "return_pct": strat_pct,
        "open_positions": open_positions,
        "max_drawdown_pct": max_drawdown(curve),
        "sharpe": sharpe_ratio(daily_rets),
        "benchmark": bench,
        "notes": verdict_bits,
        **stats,
    }
