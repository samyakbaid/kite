import csv
from datetime import date
from pathlib import Path
import tempfile
import unittest

from trading_strategy.signals import load_signals


FIELDS = [
    "signal_date",
    "model",
    "universe_kind",
    "rank",
    "symbol",
    "score",
    "target_weight",
]


def write_signals(path, signal_date="2026-08-31"):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for rank, symbol in enumerate(["RELIANCE", "INFY"], start=1):
            writer.writerow(
                {
                    "signal_date": signal_date,
                    "model": "ridge_lambda_25",
                    "universe_kind": "proxy",
                    "rank": rank,
                    "symbol": symbol,
                    "score": 0.1 / rank,
                    "target_weight": 0.5,
                }
            )


class SignalTests(unittest.TestCase):
    def test_loads_and_sorts_valid_signals(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "signals.csv"
            write_signals(path)
            signals = load_signals(path, today=date(2026, 9, 1))
        self.assertEqual([signal.symbol for signal in signals], ["RELIANCE", "INFY"])
        self.assertEqual(signals[0].universe_kind, "proxy")

    def test_stale_signal_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "signals.csv"
            write_signals(path, signal_date="2026-01-31")
            with self.assertRaisesRegex(ValueError, "stale"):
                load_signals(path, today=date(2026, 9, 1), max_age_days=45)


if __name__ == "__main__":
    unittest.main()
