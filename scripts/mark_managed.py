"""Reconcile the local state file after placing orders by hand.

When you buy strategy names manually (e.g. the Kite API is unavailable), the
rebalancer's state file does not know those positions belong to the bot. Run
this once afterwards so the next automated rebalance treats them as managed
holdings it may trim or sell, instead of ignoring them as personal stock.

Usage:
    .venv/bin/python scripts/mark_managed.py --model momentum SYMBOL [SYMBOL ...]
    .venv/bin/python scripts/mark_managed.py --model momentum --from-signals

--from-signals adds every name in the model's committed signal artifact (the
full target list). Passing symbols explicitly is safer if you skipped some.
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from trading_strategy.state import load_state, save_state  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="momentum", choices=["momentum", "ridge"])
    parser.add_argument("--state-file")
    parser.add_argument(
        "--from-signals",
        action="store_true",
        help="Add every symbol in the committed signal artifact",
    )
    parser.add_argument("symbols", nargs="*", help="Explicit NSE trading symbols")
    args = parser.parse_args(argv)

    # Matches the path run_local_rebalance.sh passes as --state-file.
    state_path = Path(args.state_file or f".trading_state/{args.model}.json")

    symbols = {s.strip().upper() for s in args.symbols if s.strip()}
    if args.from_signals:
        signal_file = Path("artifacts") / f"signals_{args.model}.csv"
        with signal_file.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if float(row["target_weight"]) > 0:
                    symbols.add(row["symbol"].strip().upper().removesuffix(".NS"))

    if not symbols:
        parser.error("pass at least one symbol or --from-signals")

    state = load_state(state_path)
    before = set(state["managed_symbols"])
    state["managed_symbols"] = sorted(before | symbols)
    save_state(state_path, state)

    added = sorted(symbols - before)
    print(f"state file: {state_path}")
    print(f"added {len(added)} symbol(s): {', '.join(added) or '(none new)'}")
    print(f"managed_symbols is now {len(state['managed_symbols'])} names")
    print(
        "\nNote: this does not tell the bot how many shares you hold; it reads live "
        "quantities from Kite at the next run. It only marks these names as bot-owned."
    )


if __name__ == "__main__":
    main()
