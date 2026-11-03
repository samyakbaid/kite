import csv
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from trading_strategy.cli import main


class FakeBroker:
    def holdings(self):
        return {"PERSONAL": 50}

    def last_prices(self, symbols):
        return {symbol: 100.0 for symbol in symbols}


def write_signal_file(path, universe_kind="official"):
    fields = [
        "signal_date",
        "model",
        "universe_kind",
        "rank",
        "symbol",
        "score",
        "target_weight",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for rank in range(1, 41):
            writer.writerow(
                {
                    "signal_date": "2026-08-31",
                    "model": "momentum_12_1",
                    "universe_kind": universe_kind,
                    "rank": rank,
                    "symbol": f"S{rank:03}",
                    "score": 41 - rank,
                    "target_weight": 1 / 30 if rank <= 30 else 0,
                }
            )


class CliTests(unittest.TestCase):
    def test_dry_run_writes_receipt_without_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signal_path = root / "signals.csv"
            write_signal_file(signal_path)
            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "--signals",
                        str(signal_path),
                        "--capital",
                        "300000",
                        "--state-file",
                        str(root / "state.json"),
                        "--receipt-dir",
                        str(root / "receipts"),
                        "--allow-stale",
                    ],
                    broker_factory=FakeBroker,
                )
            self.assertEqual(result, 0)
            self.assertEqual(len(list((root / "receipts").glob("*_dry_run.json"))), 1)
            self.assertFalse((root / "state.json").exists())

    def test_proxy_live_mode_is_blocked_before_broker_access(self):
        with tempfile.TemporaryDirectory() as directory:
            signal_path = Path(directory) / "signals.csv"
            write_signal_file(signal_path, universe_kind="proxy")
            with self.assertRaisesRegex(RuntimeError, "non-official universe"):
                main(
                    [
                        "--signals",
                        str(signal_path),
                        "--capital",
                        "300000",
                        "--allow-stale",
                        "--live",
                        "--confirm-live",
                        "PLACE_ORDERS",
                    ],
                    broker_factory=lambda: self.fail("broker must not be instantiated"),
                )


class FailingLiveBroker:
    placed = 0

    def holdings(self):
        return {}

    def last_prices(self, symbols):
        return {symbol: 100.0 for symbol in symbols}

    def available_cash(self):
        return 10_000_000.0

    def place(self, intent, **kwargs):
        type(self).placed += 1
        raise RuntimeError("IP not allowed for this app")


class LiveFailureTests(unittest.TestCase):
    def test_live_run_stops_after_repeated_errors_and_returns_nonzero(self):
        import os
        FailingLiveBroker.placed = 0
        os.environ["KITE_LIVE_TRADING"] = "ENABLED"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signal_path = root / "signals.csv"
            write_signal_file(signal_path)
            out = io.StringIO()
            with redirect_stdout(out):
                result = main(
                    [
                        "--signals", str(signal_path),
                        "--capital", "300000",
                        "--state-file", str(root / "state.json"),
                        "--receipt-dir", str(root / "receipts"),
                        "--live", "--confirm-live", "PLACE_ORDERS",
                        "--ignore-market-hours", "--order-delay", "0", "--allow-stale",
                    ],
                    broker_factory=FailingLiveBroker,
                )
            self.assertEqual(result, 1)
            self.assertEqual(FailingLiveBroker.placed, 3)
            self.assertIn("STOPPING", out.getvalue())
            self.assertIn("IP not allowed", out.getvalue())
            self.assertFalse((root / "state.json").exists() and "S001" in (root / "state.json").read_text())


if __name__ == "__main__":
    unittest.main()
