from __future__ import annotations

from statistics import fmean

from .models import Candle, Decision, Signal


def sample_bullish_candles() -> list[Candle]:
    """Stable sample data used only by the local demonstration dashboard."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    # A soft series followed by a fresh, volume-confirmed upward crossover.
    closes = ([100.0] * 31) + ([99.0] * 19) + [120.0]
    return [
        Candle(now - timedelta(days=50 - i), price, 1_000 if i < 50 else 1_800)
        for i, price in enumerate(closes)
    ]


def evaluate_sma_volume(
    symbol: str,
    exchange: str,
    candles: list[Candle],
    *,
    min_volume_ratio: float = 1.2,
    stop_percent: float = 0.02,
    reward_risk: float = 2.0,
) -> Signal:
    """Create a deterministic candidate from at least 51 completed candles."""
    if len(candles) < 51:
        raise ValueError("At least 51 completed candles are required")
    ordered = sorted(candles, key=lambda c: c.timestamp)
    closes = [c.close for c in ordered]
    volumes = [c.volume for c in ordered]
    if any(x <= 0 for x in closes) or any(x < 0 for x in volumes):
        raise ValueError("Candle prices must be positive and volume non-negative")

    current = closes[-1]
    sma20 = fmean(closes[-20:])
    sma50 = fmean(closes[-50:])
    prior20 = fmean(closes[-21:-1])
    prior50 = fmean(closes[-51:-1])
    average_volume = fmean(volumes[-21:-1])
    volume_ratio = volumes[-1] / average_volume if average_volume else 0.0

    crossed = prior20 <= prior50 and sma20 > sma50
    rules = {
        "20-day average crossed above 50-day average": crossed,
        "Price is above both averages": current > sma20 and current > sma50,
        "Volume confirmation is sufficient": volume_ratio >= min_volume_ratio,
    }
    passed = all(rules.values())
    stop = round(current * (1 - stop_percent), 2)
    target = round(current + (current - stop) * reward_risk, 2)
    reasons = tuple(("PASS: " if ok else "FAIL: ") + label for label, ok in rules.items())
    return Signal(
        symbol=symbol.upper(), exchange=exchange.upper(),
        decision=Decision.BUY_CANDIDATE if passed else Decision.NO_TRADE,
        price=round(current, 2), stop_loss=stop, target=target,
        sma20=round(sma20, 2), sma50=round(sma50, 2),
        volume_ratio=round(volume_ratio, 2), reasons=reasons,
        timestamp=ordered[-1].timestamp,
    )
