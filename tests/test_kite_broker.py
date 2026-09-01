import unittest

from trading_strategy.kite_broker import round_to_tick


class TickRoundingTests(unittest.TestCase):
    def test_buy_limit_rounds_up_and_sell_limit_rounds_down(self):
        self.assertEqual(round_to_tick(100.021, 0.05, "BUY"), 100.05)
        self.assertEqual(round_to_tick(100.029, 0.05, "SELL"), 100.0)


if __name__ == "__main__":
    unittest.main()
