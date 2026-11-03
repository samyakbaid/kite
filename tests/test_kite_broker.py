import unittest

from trading_strategy.kite_broker import round_to_tick


class TickRoundingTests(unittest.TestCase):
    def test_buy_limit_rounds_up_and_sell_limit_rounds_down(self):
        self.assertEqual(round_to_tick(100.021, 0.05, "BUY"), 100.05)
        self.assertEqual(round_to_tick(100.029, 0.05, "SELL"), 100.0)


class HoldingsT1Tests(unittest.TestCase):
    def make(self, holdings, orders=(), positions=()):
        from trading_strategy.kite_broker import KiteBroker

        broker = KiteBroker.__new__(KiteBroker)
        broker.client = type(
            "C", (), {"holdings": lambda self: holdings, "orders": lambda self: list(orders),
                  "positions": lambda self: {"net": list(positions)}}
        )()
        return broker

    def test_holdings_include_t1_quantity_and_pure_t1_rows(self):
        broker = self.make(
            [
                {"exchange": "NSE", "tradingsymbol": "SAKAR", "quantity": 5, "t1_quantity": 1},
                {"exchange": "NSE", "tradingsymbol": "SANSERA", "quantity": 0, "t1_quantity": 1},
                {"exchange": "NSE", "tradingsymbol": "OLD", "quantity": 0, "t1_quantity": 0},
                {"exchange": "MCX", "tradingsymbol": "X", "quantity": 9},
            ]
        )
        self.assertEqual(broker.holdings(), {"SAKAR": 6, "SANSERA": 1})

    def test_todays_orders_ignores_rejected_and_other_products(self):
        orders = [
            {"exchange": "NSE", "product": "CNC", "status": "COMPLETE",
             "transaction_type": "BUY", "tradingsymbol": "SAKAR"},
            {"exchange": "NSE", "product": "CNC", "status": "REJECTED",
             "transaction_type": "BUY", "tradingsymbol": "DEEDEV"},
            {"exchange": "NSE", "product": "MIS", "status": "COMPLETE",
             "transaction_type": "BUY", "tradingsymbol": "WELCORP"},
        ]
        self.assertEqual(self.make([], orders).todays_orders(), {("BUY", "SAKAR")})


class HoldingsMergeTests(HoldingsT1Tests):
    def test_merges_bse_and_nse_and_adds_todays_cnc_buys(self):
        holdings = [
            {"exchange": "NSE", "tradingsymbol": "SAKAR", "quantity": 5},
            {"exchange": "BSE", "tradingsymbol": "SANSERA", "quantity": 2},
            {"exchange": "NSE", "tradingsymbol": "KERNEX", "quantity": 0},
            {"exchange": "NSE", "tradingsymbol": "WELCORP", "quantity": 0},
            {"exchange": "BSE", "tradingsymbol": "WELCORP", "quantity": 1},
        ]
        positions = [
            {"exchange": "NSE", "product": "CNC", "tradingsymbol": "SAKAR", "quantity": 1},
            {"exchange": "NSE", "product": "CNC", "tradingsymbol": "SANSERA", "quantity": 1},
            {"exchange": "NSE", "product": "CNC", "tradingsymbol": "YASHO", "quantity": 1},
            {"exchange": "NSE", "product": "CNC", "tradingsymbol": "KERNEX", "quantity": -2},
            {"exchange": "NSE", "product": "MIS", "tradingsymbol": "ZZZ", "quantity": 4},
        ]
        result = self.make(holdings, positions=positions).holdings()
        self.assertEqual(
            result, {"SAKAR": 6, "SANSERA": 3, "WELCORP": 1, "YASHO": 1}
        )

    def test_t1_and_position_not_double_counted(self):
        holdings = [{"exchange": "NSE", "tradingsymbol": "A", "quantity": 1, "t1_quantity": 2}]
        positions = [{"exchange": "NSE", "product": "CNC", "tradingsymbol": "A", "quantity": 2}]
        self.assertEqual(self.make(holdings, positions=positions).holdings(), {"A": 3})


if __name__ == "__main__":
    unittest.main()

