import math
from collections import defaultdict

from .models import OrderIntent


class RiskLimitError(ValueError):
    """Raised when a proposed rebalance exceeds an explicit safety limit."""


def choose_holdings(signals, current_symbols, n_hold=30, buffer=0.5):
    if n_hold <= 0 or buffer < 0:
        raise ValueError("n_hold must be positive and buffer cannot be negative")
    ranked_symbols = [signal.symbol for signal in signals]
    rank = {symbol: index + 1 for index, symbol in enumerate(ranked_symbols)}
    keep_rank = max(n_hold, math.ceil(n_hold * (1.0 + buffer)))
    kept = sorted(
        (symbol for symbol in current_symbols if rank.get(symbol, math.inf) <= keep_rank),
        key=rank.get,
    )[:n_hold]
    selected = list(kept)
    for symbol in ranked_symbols:
        if symbol not in selected:
            selected.append(symbol)
        if len(selected) == n_hold:
            break
    if len(selected) < n_hold:
        raise ValueError(f"only {len(selected)} valid signals for {n_hold} holdings")
    return selected


def _top_up_buys(
    intents,
    *,
    selected,
    signals,
    current,
    prices,
    capital,
    max_turnover,
    max_order_value,
    max_weight,
    min_trade_value,
):
    """Spend the leftover turnover/cash budget on whole shares, best rank first.

    The base allocation floors every target to whole shares, so a chunk of
    capital is always left unspent, and any name priced above ``capital / n_hold``
    rounds to zero and is dropped entirely. This pass tops those names up one
    share at a time, in signal-rank order, while staying inside the turnover cap,
    the per-order value cap, available cash, and a per-name weight ceiling.
    """
    rank_of = {signal.symbol: signal.rank for signal in signals}
    order_quantity = defaultdict(int)
    sides = {}
    for intent in intents:
        order_quantity[intent.symbol] = intent.quantity
        sides[intent.symbol] = intent.side

    buy_value = sum(i.estimated_value for i in intents if i.side == "BUY")
    sell_value = sum(i.estimated_value for i in intents if i.side == "SELL")
    current_invested = sum(
        quantity * prices[symbol]
        for symbol, quantity in current.items()
        if prices.get(symbol, 0) > 0
    )
    # Both budgets must hold: the turnover cap on traded value, and not spending
    # more cash than the capital envelope allows once current holdings are counted.
    headroom = min(
        capital * max_turnover - buy_value - sell_value,
        capital - current_invested - buy_value + sell_value,
    )
    max_name_value = max_weight * capital

    def projected_value(symbol):
        return (current.get(symbol, 0) + order_quantity[symbol]) * prices[symbol]

    ranked = sorted(selected, key=lambda symbol: rank_of.get(symbol, math.inf))
    added = True
    while headroom > 1e-9 and added:
        added = False
        for symbol in ranked:
            price = prices[symbol]
            if price <= 0 or price > headroom + 1e-9:
                continue
            if sides.get(symbol) == "SELL":
                continue
            if projected_value(symbol) + price > max_name_value + 1e-9:
                continue
            if (order_quantity[symbol] + 1) * price > max_order_value + 1e-9:
                continue
            order_quantity[symbol] += 1
            sides[symbol] = "BUY"
            headroom -= price
            added = True

    result = [i for i in intents if i.side == "SELL"]
    for symbol in ranked:
        if sides.get(symbol) == "SELL":
            continue
        quantity = order_quantity[symbol]
        value = quantity * prices[symbol]
        if quantity <= 0 or value < min_trade_value:
            continue
        result.append(
            OrderIntent(
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                reference_price=float(prices[symbol]),
                estimated_value=float(value),
                reason="enter_or_increase_target",
            )
        )
    return result


def plan_rebalance(
    signals,
    current_quantities,
    prices,
    capital,
    managed_symbols=None,
    n_hold=30,
    buffer=0.5,
    max_turnover=0.20,
    min_trade_value=500.0,
    max_order_value=100_000.0,
    max_orders=60,
    max_weight=0.10,
    top_up=True,
    exits_only=False,
):
    """Create capital- and turnover-capped long-only delivery order intents."""
    if capital <= 0:
        raise ValueError("capital must be positive")
    if not 0 < max_turnover <= 2:
        raise ValueError("max_turnover must be in (0, 2]")
    if min_trade_value < 0 or max_order_value <= 0 or max_orders <= 0:
        raise ValueError("trade and order limits must be positive")
    if not 0 < max_weight <= 1:
        raise ValueError("max_weight must be in (0, 1]")

    managed = set(managed_symbols or [])
    current = {
        symbol: max(0, int(quantity))
        for symbol, quantity in current_quantities.items()
        if symbol in managed and int(quantity) > 0
    }
    selected = choose_holdings(signals, current, n_hold=n_hold, buffer=buffer)
    missing_prices = sorted(
        symbol for symbol in set(selected).union(current) if prices.get(symbol, 0) <= 0
    )
    if missing_prices:
        raise ValueError(f"missing positive prices for: {missing_prices}")

    per_name_capital = capital / n_hold
    target = {
        symbol: int(math.floor(per_name_capital / prices[symbol])) for symbol in selected
    }
    target = {symbol: quantity for symbol, quantity in target.items() if quantity > 0}
    universe = sorted(set(current).union(target))
    raw_deltas = {
        symbol: target.get(symbol, 0) - current.get(symbol, 0) for symbol in universe
    }
    if exits_only:
        # Never trim a name that is still selected; only sell names that left the buffer.
        raw_deltas = {
            symbol: (0 if symbol in selected and delta < 0 else delta)
            for symbol, delta in raw_deltas.items()
        }
    full_turnover_value = sum(
        abs(quantity) * prices[symbol] for symbol, quantity in raw_deltas.items()
    )
    scale = min(1.0, capital * max_turnover / full_turnover_value) if full_turnover_value else 1.0

    intents = []
    for symbol, raw_delta in raw_deltas.items():
        if raw_delta == 0:
            continue
        quantity = int(math.floor(abs(raw_delta) * scale + 1e-12))
        if quantity <= 0:
            continue
        side = "BUY" if raw_delta > 0 else "SELL"
        estimated_value = quantity * prices[symbol]
        # Always permit cleanup sells; min_trade_value only suppresses tiny buys.
        if side == "BUY" and estimated_value < min_trade_value:
            continue
        if estimated_value > max_order_value + 1e-9:
            raise RiskLimitError(
                f"{side} {symbol} value {estimated_value:.2f} exceeds "
                f"max_order_value {max_order_value:.2f}"
            )
        reason = "enter_or_increase_target" if side == "BUY" else "reduce_or_exit"
        intents.append(
            OrderIntent(
                symbol=symbol,
                side=side,
                quantity=quantity,
                reference_price=float(prices[symbol]),
                estimated_value=float(estimated_value),
                reason=reason,
            )
        )

    if top_up:
        intents = _top_up_buys(
            intents,
            selected=selected,
            signals=signals,
            current=current,
            prices=prices,
            capital=capital,
            max_turnover=max_turnover,
            max_order_value=max_order_value,
            max_weight=max_weight,
            min_trade_value=min_trade_value,
        )

    intents.sort(key=lambda intent: (intent.side != "SELL", -intent.estimated_value, intent.symbol))
    if len(intents) > max_orders:
        raise RiskLimitError(f"planned {len(intents)} orders; maximum is {max_orders}")
    realized_turnover = sum(intent.estimated_value for intent in intents) / capital
    if realized_turnover > max_turnover + 1e-9:
        raise AssertionError("integer rounding breached turnover cap")
    return selected, intents
