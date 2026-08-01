from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .models import Proposal, ProposalStatus, Signal
from .risk import RiskConfig, RiskRejected, calculate_quantity, pre_execution_checks
from .store import Store


class TradingService:
    APPROVAL_TTL = timedelta(minutes=15)

    def __init__(self, store: Store, config: RiskConfig | None = None) -> None:
        self.store = store
        self.config = config or RiskConfig()

    def propose(self, signal: Signal) -> Proposal:
        if self.store.is_killed():
            raise RiskRejected("Kill switch is active")
        quantity, value, risk = calculate_quantity(signal, self.config)
        p = Proposal(
            id=uuid4().hex[:12], signal=signal, quantity=quantity,
            estimated_value=value, planned_risk=risk,
            max_acceptable_price=round(signal.price * (1 + self.config.max_slippage_pct), 2),
        )
        self.store.save_proposal(p)
        return p

    def approve(self, proposal_id: str) -> None:
        row = self.store.get(proposal_id)
        if row["status"] != ProposalStatus.PENDING.value:
            raise RiskRejected("Only pending proposals can be approved")
        self.store.set_status(proposal_id, ProposalStatus.APPROVED)

    def reject(self, proposal_id: str) -> None:
        row = self.store.get(proposal_id)
        if row["status"] not in (ProposalStatus.PENDING.value, ProposalStatus.APPROVED.value):
            raise RiskRejected("Proposal cannot be rejected")
        self.store.set_status(proposal_id, ProposalStatus.REJECTED)

    def simulate_fill(self, proposal_id: str, current_price: float) -> None:
        row = self.store.get(proposal_id)
        if row["status"] != ProposalStatus.APPROVED.value:
            raise RiskRejected("Manual approval is required")
        approved_at = datetime.fromisoformat(row["approved_at"])
        if datetime.now(timezone.utc) - approved_at > self.APPROVAL_TTL:
            self.store.set_status(proposal_id, ProposalStatus.EXPIRED)
            raise RiskRejected("Approval expired")
        executed = sum(x["status"] == ProposalStatus.EXECUTED.value for x in self.store.list_proposals())
        pre_execution_checks(
            current_price=current_price, approved_max_price=row["max_price"],
            open_positions=executed, daily_pnl=0.0, killed=self.store.is_killed(),
            config=self.config,
        )
        self.store.set_status(proposal_id, ProposalStatus.EXECUTED)
