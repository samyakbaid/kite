"""Pre-run checklist. Run before every rebalance:  .venv/bin/python scripts/preflight.py

Checks: signal file (age, universe, checksum), market hours, Kite login, free cash,
this machine's public IP (must be whitelisted in the Kite developer console),
holdings vs the strategy's ranks, and what was already submitted for this signal date.
Read-only: it never places an order.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _envutil import ROOT, load_env

load_env()

from trading_strategy.signals import load_signals  # noqa: E402
from trading_strategy.state import load_state  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
results = []


def report(level, message):
    results.append(level)
    print(f"[{level:4}] {message}")


def public_ip(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.read().decode().strip()
    except Exception:
        return None


def main():
    model_name = os.environ.get("STRATEGY_MODEL", "momentum")
    capital = float(os.environ.get("STRATEGY_CAPITAL", "0") or 0)
    signal_path = ROOT / "artifacts" / f"signals_{model_name}.csv"
    n_hold = 30
    keep_rank = 45

    # 1. signals
    signals = None
    try:
        manifest = json.loads((signal_path.parent / "manifest.json").read_text())
        expected = manifest.get("files", {}).get(signal_path.name)
        signals = load_signals(signal_path, max_age_days=45, expected_sha256=expected)
        age = (datetime.now(IST).date() - signals[0].signal_date).days
        report("PASS", f"signal {signals[0].signal_date} ({age} days old), universe="
               f"{signals[0].universe_kind}, checksum OK")
        if signals[0].universe_kind != "official":
            report("FAIL", "universe is not 'official' - live orders will be blocked")
    except Exception as exc:
        report("FAIL", f"signal file problem: {exc}")

    # 2. market hours
    now = datetime.now(IST)
    minutes = now.hour * 60 + now.minute
    if now.weekday() < 5 and 9 * 60 + 15 <= minutes < 15 * 60 + 30:
        report("PASS", f"NSE hours ({now:%a %H:%M} IST)")
    else:
        report("WARN", f"NSE looks closed ({now:%a %H:%M} IST) - live orders will be refused")

    # 3. IPs
    v4, v6 = public_ip("https://api.ipify.org"), public_ip("https://api6.ipify.org")
    report("INFO", f"public IPv4: {v4 or 'none'} | IPv6: {v6 or 'none'}  "
           "<- one of these must be whitelisted in the Kite developer console")

    # 4. Kite login, cash, holdings
    try:
        from trading_strategy.kite_broker import KiteBroker

        broker = KiteBroker()
        profile = broker.client.profile()
        report("PASS", f"Kite login OK (user {profile.get('user_id', '?')})")
        cash = broker.available_cash()
        report("INFO", f"free cash: {cash:,.2f}")
        holdings = broker.holdings()
    except Exception as exc:
        report("FAIL", f"Kite problem: {exc} -> run: .venv/bin/python scripts/auth_kite.py")
        return finish()

    # 5. state
    state = load_state(ROOT / ".trading_state" / f"{model_name}.json")
    managed = set(state["managed_symbols"]) & set(holdings)
    adopt_all = os.environ.get("MANAGE_ALL_HOLDINGS") == "YES"
    unmanaged = sorted(set(holdings) - managed)
    if unmanaged and not adopt_all:
        report("WARN", f"{len(unmanaged)} holdings are not bot-managed and will be ignored: "
               f"{', '.join(unmanaged)}")
    elif adopt_all:
        report("PASS", f"MANAGE_ALL_HOLDINGS=YES: all {len(holdings)} holdings are bot-managed")
    if signals:
        date = str(signals[0].signal_date)
        phases = [s.get("phase", "all") for s in state["submissions"]
                  if s.get("model") == signals[0].model and s.get("signal_date") == date]
        report("INFO", f"already submitted for {date}: {', '.join(phases) if phases else 'nothing'}")

        # 6. holdings vs ranks
        ranks = {s.symbol: s.rank for s in signals}
        out = sorted(
            (sym for sym in holdings if ranks.get(sym, 10**9) > keep_rank),
            key=lambda sym: ranks.get(sym, 10**9),
        )
        if out:
            report("INFO", "out of rank (> %d) - the sell step will exit: %s" % (keep_rank, ", ".join(
                f"{sym}({ranks.get(sym, 'not ranked')})" for sym in out)))
        else:
            report("PASS", "no holdings are out of rank - nothing to sell")
        if capital:
            report("INFO", f"strategy capital: {capital:,.0f}")
    return finish()


def finish():
    print()
    if "FAIL" in results:
        print("PREFLIGHT: FAILED - fix the FAIL lines above before trading.")
        return 1
    print("PREFLIGHT: OK" + (" (with warnings)" if "WARN" in results else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
