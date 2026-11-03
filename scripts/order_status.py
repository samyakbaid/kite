"""Show today's Kite orders and whether they filled.  .venv/bin/python scripts/order_status.py

'Submitted' is not 'filled' - this is the check that tells you what actually happened.
"""
from _envutil import load_env

load_env()

from trading_strategy.kite_broker import KiteBroker  # noqa: E402


def main():
    orders = KiteBroker().client.orders()
    if not orders:
        print("No orders today.")
        return 0
    print("TIME      SIDE  SYMBOL          QTY  FILLED  AVG_PRICE  STATUS")
    counts = {}
    for order in sorted(orders, key=lambda o: str(o.get("order_timestamp"))):
        status = order.get("status", "?")
        counts[status] = counts.get(status, 0) + 1
        stamp = str(order.get("order_timestamp", ""))[-8:]
        print(
            f"{stamp:9} {order.get('transaction_type', '?'):4}  "
            f"{order.get('tradingsymbol', '?'):14} {order.get('quantity', 0):4d} "
            f"{order.get('filled_quantity', 0):6d} {order.get('average_price', 0.0):10.2f}  {status}"
            + (f"  <- {order.get('status_message')}" if status == "REJECTED" else "")
        )
    print("\n" + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
    open_orders = counts.get("OPEN", 0) + counts.get("TRIGGER PENDING", 0)
    if open_orders:
        print(f"{open_orders} order(s) still OPEN - they expire at the close (Day validity).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
