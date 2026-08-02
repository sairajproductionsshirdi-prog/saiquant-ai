"""
riskengine.py — Capital protection layer for the autonomous paper trader.

Every rule here is a HARD constraint the strategy cannot override:
  • Max 1% of capital risked per trade (position size derived from stop distance)
  • Daily loss limit (default 3% of capital) → halts new entries for the day
  • Max open positions and max exposure per sector/group (diversification)
  • Trailing stop-loss once a position moves in favour
  • Automatic halt on abnormal volatility (index move beyond threshold)
  • Automatic halt on data/API failure (stale or missing prices)

Nothing here promises profit. It exists to bound losses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class RiskConfig:
    capital: float = 100_000.0
    risk_per_trade_pct: float = 1.0        # max % of capital lost if stop hits
    daily_loss_limit_pct: float = 3.0
    max_open_positions: int = 6
    max_group_positions: int = 3           # diversification across groups
    max_position_pct: float = 20.0         # cap exposure per single stock
    trail_activate_pct: float = 6.0        # start trailing after +6%
    trail_distance_pct: float = 4.0        # trail 4% below the high
    volatility_halt_pct: float = 2.5       # index move beyond this = halt
    max_data_failures: int = 3             # consecutive failures = halt


@dataclass
class RiskState:
    day: str = field(default_factory=lambda: date.today().isoformat())
    realised_today: float = 0.0
    halted: bool = False
    halt_reason: str = ""
    data_failures: int = 0

    def roll_day(self) -> None:
        today = date.today().isoformat()
        if self.day != today:
            self.day = today
            self.realised_today = 0.0
            self.halted = False
            self.halt_reason = ""
            self.data_failures = 0


class RiskEngine:
    def __init__(self, cfg: RiskConfig, state: RiskState | None = None):
        self.cfg = cfg
        self.state = state or RiskState()

    # ── sizing ──────────────────────────────────────────────────────────
    def position_size(self, entry: float, stop: float) -> tuple[int, str]:
        """Quantity such that (entry - stop) * qty <= 1% of capital."""
        risk_per_share = entry - stop
        if risk_per_share <= 0:
            return 0, "invalid stop (must be below entry for a long)"
        budget = self.cfg.capital * self.cfg.risk_per_trade_pct / 100
        qty = int(budget // risk_per_share)
        if qty <= 0:
            return 0, "stop too wide for 1% risk budget"
        # exposure cap
        max_expo = self.cfg.capital * self.cfg.max_position_pct / 100
        if entry * qty > max_expo:
            qty = int(max_expo // entry)
            if qty <= 0:
                return 0, "price exceeds per-position exposure cap"
            return qty, f"size capped by {self.cfg.max_position_pct}% exposure limit"
        return qty, f"risking {self.cfg.risk_per_trade_pct}% of capital"

    # ── halts ───────────────────────────────────────────────────────────
    def check_volatility(self, index_change_pct: float | None) -> None:
        if index_change_pct is None:
            return
        if abs(index_change_pct) >= self.cfg.volatility_halt_pct:
            self.halt(f"abnormal volatility: index moved {index_change_pct:+.2f}%")

    def note_data_failure(self) -> None:
        self.state.data_failures += 1
        if self.state.data_failures >= self.cfg.max_data_failures:
            self.halt(f"{self.state.data_failures} consecutive data/API failures")

    def note_data_success(self) -> None:
        self.state.data_failures = 0

    def halt(self, reason: str) -> None:
        self.state.halted = True
        self.state.halt_reason = reason

    # ── entry gate ──────────────────────────────────────────────────────
    def approve_entry(self, open_positions: list, group: str,
                      entry: float, qty: int) -> tuple[bool, str]:
        self.state.roll_day()
        if self.state.halted:
            return False, f"HALTED: {self.state.halt_reason}"

        loss_limit = -self.cfg.capital * self.cfg.daily_loss_limit_pct / 100
        if self.state.realised_today <= loss_limit:
            self.halt(f"daily loss limit hit (₹{self.state.realised_today:,.0f})")
            return False, self.state.halt_reason

        if len(open_positions) >= self.cfg.max_open_positions:
            return False, f"max {self.cfg.max_open_positions} open positions"

        same_group = sum(1 for p in open_positions if p.get("group") == group)
        if same_group >= self.cfg.max_group_positions:
            return False, (f"diversification: already {same_group} positions "
                           f"in {group}")

        if qty <= 0:
            return False, "zero quantity after sizing"

        return True, "approved"

    # ── trailing stop ───────────────────────────────────────────────────
    def update_trailing_stop(self, entry: float, current_stop: float,
                             highest: float) -> tuple[float, bool]:
        """Returns (new_stop, moved). Trails only upward, never loosens."""
        gain_pct = (highest - entry) / entry * 100
        if gain_pct < self.cfg.trail_activate_pct:
            return current_stop, False
        candidate = highest * (1 - self.cfg.trail_distance_pct / 100)
        if candidate > current_stop:
            return round(candidate, 2), True
        return current_stop, False

    def record_realised(self, pnl: float) -> None:
        self.state.roll_day()
        self.state.realised_today += pnl
