from datetime import date
import unittest

from trading_strategy.models import Signal
from trading_strategy.planner import RiskLimitError, choose_holdings, plan_rebalance


def make_signals(count=60):
    return [
        Signal(
            signal_date=date(2026, 8, 31),
            model="momentum_12_1",
            universe_kind="proxy",
            rank=rank,
            symbol=f"S{rank:03}",
            score=float(count - rank),
            target_weight=1 / 30 if rank <= 30 else 0.0,
        )
        for rank in range(1, count + 1)
    ]


class PlannerTests(unittest.TestCase):
    def test_buffer_keeps_managed_name_inside_keep_zone(self):
        selected = choose_holdings(make_signals(), {"S040"}, n_hold=30, buffer=0.5)
        self.assertIn("S040", selected)
        self.assertEqual(len(selected), 30)

    def test_initial_rebalance_respects_turnover_and_ignores_unmanaged_holdings(self):
        signals = make_signals()
        prices = {signal.symbol: 100.0 for signal in signals[:30]}
        selected, intents = plan_rebalance(
            signals,
            current_quantities={"PERSONAL": 999},
            managed_symbols=set(),
            prices=prices,
            capital=300_000,
            n_hold=30,
            max_turnover=0.20,
            min_trade_value=0,
        )
        self.assertEqual(len(selected), 30)
        self.assertTrue(all(intent.side == "BUY" for intent in intents))
        self.assertTrue(all(intent.symbol != "PERSONAL" for intent in intents))
        self.assertLessEqual(
            sum(intent.estimated_value for intent in intents) / 300_000, 0.20
        )

    def test_only_managed_positions_can_be_sold(self):
        signals = make_signals()
        current = {"S060": 10, "PERSONAL": 100}
        prices = {signal.symbol: 100.0 for signal in signals[:30]}
        prices["S060"] = 100.0
        _, intents = plan_rebalance(
            signals,
            current_quantities=current,
            managed_symbols={"S060"},
            prices=prices,
            capital=100_000,
            n_hold=30,
            max_turnover=2.0,
            min_trade_value=0,
        )
        sells = {intent.symbol for intent in intents if intent.side == "SELL"}
        self.assertEqual(sells, {"S060"})
        self.assertNotIn("PERSONAL", {intent.symbol for intent in intents})

    def test_bootstrap_turnover_deploys_almost_all_capital(self):
        signals = make_signals()
        prices = {signal.symbol: 100.0 + signal.rank for signal in signals[:30]}
        _, intents = plan_rebalance(
            signals,
            current_quantities={},
            managed_symbols=set(),
            prices=prices,
            capital=100_000,
            n_hold=30,
            max_turnover=1.0,
            min_trade_value=0,
        )
        spent = sum(intent.estimated_value for intent in intents)
        self.assertTrue(all(intent.side == "BUY" for intent in intents))
        self.assertLessEqual(spent, 100_000 + 1e-6)
        self.assertGreater(spent, 0.97 * 100_000)

    def test_top_up_still_respects_monthly_turnover_cap(self):
        signals = make_signals()
        prices = {signal.symbol: 100.0 + signal.rank for signal in signals[:30]}
        _, intents = plan_rebalance(
            signals,
            current_quantities={},
            managed_symbols=set(),
            prices=prices,
            capital=100_000,
            n_hold=30,
            max_turnover=0.20,
            min_trade_value=0,
        )
        spent = sum(intent.estimated_value for intent in intents)
        self.assertLessEqual(spent / 100_000, 0.20 + 1e-9)

    def test_top_up_respects_per_name_weight_ceiling(self):
        signals = make_signals()
        prices = {signal.symbol: 100.0 for signal in signals[:30]}
        _, intents = plan_rebalance(
            signals,
            current_quantities={},
            managed_symbols=set(),
            prices=prices,
            capital=100_000,
            n_hold=30,
            max_turnover=1.0,
            min_trade_value=0,
            max_weight=0.05,
        )
        by_symbol = {intent.symbol: intent.estimated_value for intent in intents}
        self.assertTrue(all(value <= 0.05 * 100_000 + 1e-9 for value in by_symbol.values()))

    def test_bootstrap_buys_names_priced_above_equal_weight_budget(self):
        signals = make_signals()
        prices = {signal.symbol: 100.0 for signal in signals[:30]}
        prices["S001"] = 4_000.0  # above capital / n_hold = 3333, but under the 10% ceiling
        _, intents = plan_rebalance(
            signals,
            current_quantities={},
            managed_symbols=set(),
            prices=prices,
            capital=100_000,
            n_hold=30,
            max_turnover=1.0,
            min_trade_value=0,
        )
        self.assertIn("S001", {intent.symbol for intent in intents})

    def test_order_value_limit_fails_closed(self):
        signals = make_signals()
        prices = {signal.symbol: 100.0 for signal in signals[:30]}
        with self.assertRaises(RiskLimitError):
            plan_rebalance(
                signals,
                current_quantities={},
                managed_symbols=set(),
                prices=prices,
                capital=3_000_000,
                max_turnover=1.0,
                min_trade_value=0,
                max_order_value=50_000,
            )


if __name__ == "__main__":
    unittest.main()
