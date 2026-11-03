"""Print EVERY Kite holding and position with all quantity fields, plus totals.
.venv/bin/python scripts/debug_holdings.py      (read-only, prints no secrets)
"""
from _envutil import load_env

load_env()

from trading_strategy.kite_broker import KiteBroker  # noqa: E402

FIELDS = ("quantity", "t1_quantity", "collateral_quantity", "used_quantity",
          "authorised_quantity", "opening_quantity", "realised_quantity")


def num(x):
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def main():
    client = KiteBroker().client
    rows = client.holdings()
    print(f"HOLDINGS ({len(rows)} rows)")
    print(f"{'SYMBOL':14}{'EXCH':5}{'QTY':>5}{'T1':>4}{'COLL':>5}{'USED':>5}{'LTP':>10}{'VALUE(all)':>12}  TYPE")
    t_bot = t_all = 0.0
    for h in sorted(rows, key=lambda r: -(num(r.get("quantity")) + num(r.get("t1_quantity")) + num(r.get("collateral_quantity"))) * float(r.get("last_price") or 0)):
        q, t1, coll = num(h.get("quantity")), num(h.get("t1_quantity")), num(h.get("collateral_quantity"))
        price = float(h.get("last_price") or 0)
        value = (q + t1 + coll) * price
        t_all += value
        if h.get("exchange") == "NSE":
            t_bot += (q + t1) * price
        print(f"{h['tradingsymbol']:14}{h.get('exchange', '?'):5}{q:5d}{t1:4d}{coll:5d}{num(h.get('used_quantity')):5d}"
              f"{price:10.2f}{value:12.2f}  {h.get('product', '')}")
    # The number the bot uses: merged NSE+BSE, plus today's CNC buys, minus excluded ETFs.
    import os

    excluded = {x.strip().upper() for x in os.environ.get("UNMANAGED_SYMBOLS", "").split(",") if x.strip()}
    broker = KiteBroker()
    broker.client = client
    owned = {s: q for s, q in broker.holdings().items() if s not in excluded}
    prices = broker.last_prices(set(owned)) if owned else {}
    bot_total = sum(q * prices[s] for s, q in owned.items())
    ex_total = sum(num(h.get("quantity")) * float(h.get("last_price") or 0)
                   for h in rows if h["tradingsymbol"].upper() in excluded)
    today_total = bot_total + ex_total - t_all
    print(f"\nKite holdings page, all exchanges (settled):      {t_all:>12,.2f}")
    print(f"+ bought today (shown under positions):           {today_total:>12,.2f}")
    print(f"- personal holdings the bot ignores ({', '.join(sorted(excluded)) or 'none'}): {-ex_total:>12,.2f}")
    print(f"= value the bot manages (matches the run table):  {bot_total:>12,.2f}")
    print("\nPOSITIONS (net, non-zero)")
    for p in client.positions().get("net", []):
        if num(p.get("quantity")) or num(p.get("buy_quantity")):
            print(f"{p['tradingsymbol']:14}{p.get('exchange', '?'):5} {p.get('product', ''):5} "
                  f"qty {num(p.get('quantity'))} buy {num(p.get('buy_quantity'))} sell {num(p.get('sell_quantity'))}")
    try:
        mf = client.mf_holdings()
        if mf:
            print(f"\nMUTUAL FUNDS (not equity, never touched by the bot): {len(mf)} holdings")
    except Exception:
        pass


if __name__ == "__main__":
    main()
