from __future__ import annotations

from dataclasses import dataclass

from .models import Decision, Signal


@dataclass(frozen=True)
class RiskConfig:
    capital: float = 100_000.0
    risk_per_trade_pct: float = 0.0025
    max_position_pct: float = 0.05
    max_positions: int = 3
    daily_loss_pct: float = 0.01
    max_slippage_pct: float = 0.003


class RiskRejected(ValueError):
    pass


def calculate_quantity(signal: Signal, config: RiskConfig) -> tuple[int, float, float]:
    if signal.decision is not Decision.BUY_CANDIDATE:
        raise RiskRejected("Signal is not a buy candidate")
    per_share_risk = signal.price - signal.stop_loss
    if per_share_risk <= 0:
        raise RiskRejected("Stop-loss must be below entry price")
    by_risk = int((config.capital * config.risk_per_trade_pct) // per_share_risk)
    by_exposure = int((config.capital * config.max_position_pct) // signal.price)
    quantity = min(by_risk, by_exposure)
    if quantity < 1:
        raise RiskRejected("Capital/risk limits allow zero shares")
    return quantity, round(quantity * signal.price, 2), round(quantity * per_share_risk, 2)


def pre_execution_checks(
    *, current_price: float, approved_max_price: float, open_positions: int,
    daily_pnl: float, killed: bool, config: RiskConfig,
) -> None:
    if killed:
        raise RiskRejected("Kill switch is active")
    if open_positions >= config.max_positions:
        raise RiskRejected("Maximum open positions reached")
    if daily_pnl <= -(config.capital * config.daily_loss_pct):
        raise RiskRejected("Daily loss limit reached")
    if current_price <= 0 or current_price > approved_max_price:
        raise RiskRejected("Current price is outside approved limit")
