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


class RecordingBroker:
    placed = []

    def holdings(self):
        return {}

    def last_prices(self, symbols):
        return {symbol: 100.0 for symbol in symbols}

    def available_cash(self):
        return 10_000_000.0

    def place(self, intent, **kwargs):
        type(self).placed.append(intent.symbol)
        return "OID" + intent.symbol


class ConfirmationTests(unittest.TestCase):
    def run_live(self, answers):
        import os
        from unittest import mock
        RecordingBroker.placed = []
        os.environ["KITE_LIVE_TRADING"] = "ENABLED"
        feed = iter(answers)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signal_path = root / "signals.csv"
            write_signal_file(signal_path)
            out = io.StringIO()
            with redirect_stdout(out), mock.patch(
                "trading_strategy.cli.sys.stdin.isatty", return_value=True, create=True
            ), mock.patch("builtins.input", lambda *_: next(feed)):
                result = main(
                    [
                        "--signals", str(signal_path),
                        "--capital", "300000",
                        "--state-file", str(root / "state.json"),
                        "--receipt-dir", str(root / "receipts"),
                        "--live", "--confirm-live", "PLACE_ORDERS",
                        "--ignore-market-hours", "--order-delay", "0", "--allow-stale",
                    ],
                    broker_factory=RecordingBroker,
                )
            state_exists = (root / "state.json").exists()
        return result, out.getvalue(), state_exists

    def test_cancel_places_nothing(self):
        result, output, state_exists = self.run_live(["n"])
        self.assertEqual(result, 0)
        self.assertEqual(RecordingBroker.placed, [])
        self.assertIn("Cancelled by user", output)
        self.assertFalse(state_exists)

    def test_yes_places_all(self):
        result, output, _ = self.run_live(["y"])
        self.assertEqual(result, 0)
        self.assertGreater(len(RecordingBroker.placed), 0)
        self.assertIn("LIVE KITE PORTFOLIO", output)

    def test_select_one_by_one(self):
        result, output, _ = self.run_live(["s", "y", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n", "n"])
        self.assertEqual(len(RecordingBroker.placed), 1)


class CashBroker:
    placed = []

    def __init__(self):
        self.cash = 30_000.0

    def holdings(self):
        return {"PERSONAL": 50}

    def last_prices(self, symbols):
        return {symbol: 100.0 for symbol in symbols}

    def available_cash(self):
        return self.cash

    def place(self, intent, **kwargs):
        type(self).placed.append(intent)
        return "OID"


class FitCashAndAdoptTests(unittest.TestCase):
    def run_cli(self, extra):
        import os
        CashBroker.placed = []
        os.environ["KITE_LIVE_TRADING"] = "ENABLED"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signal_path = root / "signals.csv"
            write_signal_file(signal_path)
            out = io.StringIO()
            with redirect_stdout(out):
                main(
                    [
                        "--signals", str(signal_path), "--capital", "300000",
                        "--state-file", str(root / "state.json"),
                        "--receipt-dir", str(root / "receipts"),
                        "--live", "--confirm-live", "PLACE_ORDERS", "--yes",
                        "--ignore-market-hours", "--order-delay", "0", "--allow-stale",
                    ] + extra,
                    broker_factory=CashBroker,
                )
        return out.getvalue()

    def test_fit_cash_keeps_buys_within_free_cash(self):
        output = self.run_cli(["--phase", "buys", "--fit-cash"])
        spent = sum(i.estimated_value for i in CashBroker.placed)
        self.assertLessEqual(spent * 1.01, 30_000.0)
        self.assertGreater(len(CashBroker.placed), 0)
        self.assertIn("FIT-CASH", output)

    def test_manage_all_holdings_adopts_and_sells_out_of_rank(self):
        output = self.run_cli(["--manage-all-holdings", "--phase", "sells", "--exits-only",
                               "--max-turnover", "1.0"])
        self.assertIn("Adopting 1 existing holdings", output)
        self.assertEqual([(i.side, i.symbol) for i in CashBroker.placed], [("SELL", "PERSONAL")])


if __name__ == "__main__":
    unittest.main()
