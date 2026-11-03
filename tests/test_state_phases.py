import unittest

from trading_strategy.state import already_submitted, empty_state, record_submission
from trading_strategy.cli import failure_hint


class PhaseTests(unittest.TestCase):
    def test_sells_then_buys_allowed_but_all_blocks_both(self):
        state = empty_state()
        record_submission(state, "m", "2026-10-31", [], "sells")
        self.assertTrue(already_submitted(state, "m", "2026-10-31", "sells"))
        self.assertFalse(already_submitted(state, "m", "2026-10-31", "buys"))
        self.assertTrue(already_submitted(state, "m", "2026-10-31", "all"))
        record_submission(state, "m", "2026-10-31", [], "buys")
        self.assertTrue(already_submitted(state, "m", "2026-10-31", "buys"))

    def test_legacy_entries_count_as_all(self):
        state = empty_state()
        state["submissions"].append({"model": "m", "signal_date": "2026-10-31"})
        for phase in ("sells", "buys", "all"):
            self.assertTrue(already_submitted(state, "m", "2026-10-31", phase))

    def test_other_dates_unaffected(self):
        state = empty_state()
        record_submission(state, "m", "2026-09-30", [], "all")
        self.assertFalse(already_submitted(state, "m", "2026-10-31", "buys"))

    def test_failure_hints(self):
        self.assertIn("whitelist", failure_hint("IP (1.2.3.4) is not allowed to place orders"))
        self.assertIn("Authorise", failure_hint("2 shares need to be authorised at CDSL"))
        self.assertIsNone(failure_hint("something else"))
