from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Decision(str, Enum):
    BUY_CANDIDATE = "BUY_CANDIDATE"
    NO_TRADE = "NO_TRADE"


class ProposalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    symbol: str
    exchange: str
    decision: Decision
    price: float
    stop_loss: float
    target: float
    sma20: float
    sma50: float
    volume_ratio: float
    reasons: tuple[str, ...]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Proposal:
    id: str
    signal: Signal
    quantity: int
    estimated_value: float
    planned_risk: float
    max_acceptable_price: float
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: datetime | None = None
