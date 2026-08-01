import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from saiquant.models import Candle, Decision, Signal
from saiquant.risk import RiskConfig, RiskRejected, calculate_quantity, pre_execution_checks
from saiquant.service import TradingService
from saiquant.store import Store
from saiquant.strategy import evaluate_sma_volume, sample_bullish_candles


def signal(price=1500, stop=1480):
    return Signal("RELIANCE", "NSE", Decision.BUY_CANDIDATE, price, stop, 1540, 1490, 1470, 1.4, ("ok",))


class RiskTests(unittest.TestCase):
    def test_demo_data_creates_candidate(self):
        result = evaluate_sma_volume("RELIANCE", "NSE", sample_bullish_candles())
        self.assertEqual(result.decision, Decision.BUY_CANDIDATE)

    def test_quantity_uses_lower_limit(self):
        qty, value, risk = calculate_quantity(signal(), RiskConfig())
        self.assertEqual(qty, 3)
        self.assertEqual(value, 4500)
        self.assertEqual(risk, 60)

    def test_kill_switch_rejects(self):
        with self.assertRaisesRegex(RiskRejected, "Kill switch"):
            pre_execution_checks(current_price=100, approved_max_price=101, open_positions=0, daily_pnl=0, killed=True, config=RiskConfig())

    def test_price_slippage_rejects(self):
        with self.assertRaisesRegex(RiskRejected, "price"):
            pre_execution_checks(current_price=102, approved_max_price=101, open_positions=0, daily_pnl=0, killed=False, config=RiskConfig())

    def test_manual_approval_required(self):
        with tempfile.TemporaryDirectory() as d:
            service = TradingService(Store(f"{d}/test.db"))
            p = service.propose(signal())
            with self.assertRaisesRegex(RiskRejected, "approval"):
                service.simulate_fill(p.id, 1500)

    def test_approved_paper_fill(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(f"{d}/test.db")
            service = TradingService(store)
            p = service.propose(signal())
            service.approve(p.id)
            service.simulate_fill(p.id, 1500)
            self.assertEqual(store.get(p.id)["status"], "EXECUTED")


if __name__ == "__main__":
    unittest.main()
