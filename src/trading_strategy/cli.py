import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .kite_broker import KiteBroker
from .planner import RiskLimitError, choose_holdings, plan_rebalance
from .signals import load_signals
from .state import already_submitted, load_state, record_submission, save_state


def slugify(value):
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Plan or submit a guarded monthly Kite CNC rebalance"
    )
    parser.add_argument("--signals", required=True, help="Dated signal CSV to execute")
    parser.add_argument("--capital", required=True, type=float, help="Hard strategy capital cap")
    parser.add_argument("--state-file", help="Local managed-symbol/idempotency state JSON")
    parser.add_argument("--receipt-dir", default="receipts")
    parser.add_argument("--n-hold", type=int, default=30)
    parser.add_argument("--buffer", type=float, default=0.5)
    parser.add_argument("--max-turnover", type=float, default=0.20)
    parser.add_argument("--min-trade-value", type=float, default=500.0)
    parser.add_argument("--max-order-value", type=float, default=100_000.0)
    parser.add_argument("--max-orders", type=int, default=60)
    parser.add_argument("--max-signal-age-days", type=int, default=45)
    parser.add_argument("--allow-stale", action="store_true")
    parser.add_argument(
        "--allow-proxy-universe",
        action="store_true",
        help="Explicitly permit live orders from non-official universe data",
    )
    parser.add_argument("--order-type", choices=["LIMIT", "MARKET"], default="LIMIT")
    parser.add_argument("--limit-buffer-bps", type=float, default=20.0)
    parser.add_argument("--variety", choices=["regular", "amo"], default="regular")
    parser.add_argument("--phase", choices=["all", "sells", "buys"], default="all")
    parser.add_argument("--live", action="store_true", help="Actually submit orders")
    parser.add_argument("--confirm-live", help="Must equal PLACE_ORDERS in live mode")
    parser.add_argument("--force", action="store_true", help="Allow a repeated signal date")
    return parser.parse_args(argv)


def write_receipt(directory, model, signal_date, mode, payload):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{slugify(model)}_{signal_date}_{timestamp}_{mode}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def print_plan(model, signal_date, selected, intents, capital):
    turnover = sum(intent.estimated_value for intent in intents) / capital
    print(f"Model: {model} | signal date: {signal_date}")
    print(f"Selected holdings: {len(selected)} | planned orders: {len(intents)}")
    print(f"Estimated one-way turnover: {turnover:.2%}")
    if not intents:
        print("No trades required.")
        return
    print("\nSIDE  SYMBOL          QTY     REF_PRICE      EST_VALUE")
    for intent in intents:
        print(
            f"{intent.side:4}  {intent.symbol:14} {intent.quantity:6d} "
            f"{intent.reference_price:13.2f} {intent.estimated_value:14.2f}"
        )


def live_gate(args):
    if not args.live:
        return
    if args.confirm_live != "PLACE_ORDERS":
        raise RuntimeError("live mode requires --confirm-live PLACE_ORDERS")
    if os.environ.get("KITE_LIVE_TRADING") != "ENABLED":
        raise RuntimeError("live mode requires KITE_LIVE_TRADING=ENABLED")


def main(argv=None, broker_factory=KiteBroker):
    args = parse_args(argv)
    max_age = None if args.allow_stale else args.max_signal_age_days
    signal_path = Path(args.signals).resolve()
    manifest_path = signal_path.parent / "manifest.json"
    expected_checksum = None
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_checksum = manifest.get("files", {}).get(signal_path.name)
        if not expected_checksum:
            raise RuntimeError(f"manifest has no checksum for {signal_path.name}")
    signals = load_signals(
        signal_path, max_age_days=max_age, expected_sha256=expected_checksum
    )
    model = signals[0].model
    signal_date = signals[0].signal_date
    if (
        args.live
        and signals[0].universe_kind != "official"
        and not args.allow_proxy_universe
    ):
        raise RuntimeError(
            "live mode is blocked for a non-official universe; replace the membership "
            "data or explicitly pass --allow-proxy-universe"
        )
    state_path = Path(args.state_file or f".trading_state/{slugify(model)}.json")
    state = load_state(state_path)
    if already_submitted(state, model, signal_date) and not args.force:
        raise RuntimeError(
            "this model/signal date was already submitted; use --force only after "
            "checking the saved receipt and Kite order book"
        )

    live_gate(args)
    broker = broker_factory()
    broker_holdings = broker.holdings()
    managed_symbols = set(state["managed_symbols"]).intersection(broker_holdings)
    # Forget fully exited names so later personal purchases are never adopted by accident.
    state["managed_symbols"] = sorted(managed_symbols)
    current_quantities = {
        symbol: broker_holdings[symbol] for symbol in managed_symbols
    }

    # Fetch only the top buffer zone and existing managed names, not the whole file.
    candidates = choose_holdings(
        signals,
        current_quantities,
        n_hold=args.n_hold,
        buffer=args.buffer,
    )
    price_symbols = set(candidates).union(current_quantities)
    prices = broker.last_prices(price_symbols)
    selected, intents = plan_rebalance(
        signals,
        current_quantities=current_quantities,
        prices=prices,
        capital=args.capital,
        managed_symbols=managed_symbols,
        n_hold=args.n_hold,
        buffer=args.buffer,
        max_turnover=args.max_turnover,
        min_trade_value=args.min_trade_value,
        max_order_value=args.max_order_value,
        max_orders=args.max_orders,
    )
    if args.phase == "sells":
        intents = [intent for intent in intents if intent.side == "SELL"]
    elif args.phase == "buys":
        intents = [intent for intent in intents if intent.side == "BUY"]
    print_plan(model, signal_date, selected, intents, args.capital)

    payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "live" if args.live else "dry_run",
        "model": model,
        "signal_date": str(signal_date),
        "signal_file": str(signal_path),
        "manifest_file": str(manifest_path) if manifest_path.exists() else None,
        "capital": args.capital,
        "state_file": str(state_path),
        "selected_symbols": selected,
        "orders": [intent.to_dict() for intent in intents],
        "results": [],
    }
    if not args.live:
        receipt = write_receipt(
            args.receipt_dir, model, signal_date, "dry_run", payload
        )
        print(f"\nDRY RUN ONLY — no orders submitted. Receipt: {receipt}")
        return 0

    estimated_buys = sum(
        intent.estimated_value for intent in intents if intent.side == "BUY"
    )
    available_cash = broker.available_cash()
    payload["available_cash_before_orders"] = available_cash
    if estimated_buys * 1.01 > available_cash:
        raise RiskLimitError(
            f"planned buys plus 1% reserve ({estimated_buys * 1.01:.2f}) exceed "
            f"available cash ({available_cash:.2f}); run --phase sells first or reduce capital"
        )

    tag = f"wf_{slugify(model)[:8]}_{signal_date:%y%m}"
    sell_failed = False
    for intent in intents:
        if intent.side == "BUY" and sell_failed:
            payload["results"].append(
                {**intent.to_dict(), "status": "skipped", "error": "a sell order failed"}
            )
            continue
        try:
            order_id = broker.place(
                intent,
                order_type=args.order_type,
                limit_buffer_bps=args.limit_buffer_bps,
                variety=args.variety,
                tag=tag,
            )
            payload["results"].append(
                {**intent.to_dict(), "status": "submitted", "order_id": str(order_id)}
            )
        except Exception as exc:  # broker errors must be captured in the receipt
            payload["results"].append(
                {**intent.to_dict(), "status": "error", "error": str(exc)}
            )
            if intent.side == "SELL":
                sell_failed = True

    if not intents or any(
        result["status"] == "submitted" for result in payload["results"]
    ):
        record_submission(state, model, signal_date, payload["results"])
        save_state(state_path, state)
    receipt = write_receipt(args.receipt_dir, model, signal_date, "live", payload)
    print(
        f"\nSubmitted orders are not guaranteed fills. Check Kite order status. Receipt: {receipt}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
