import math
import os


def round_to_tick(price, tick_size, side):
    if price <= 0 or tick_size <= 0:
        raise ValueError("price and tick_size must be positive")
    units = price / tick_size
    rounded_units = math.ceil(units - 1e-12) if side == "BUY" else math.floor(units + 1e-12)
    return round(rounded_units * tick_size, 10)


class KiteBroker:
    """Small adapter around Zerodha's official pykiteconnect client."""

    def __init__(self, api_key=None, access_token=None):
        try:
            from kiteconnect import KiteConnect
        except ImportError as exc:
            raise RuntimeError("install the package with: pip install -e .") from exc

        api_key = api_key or os.environ.get("KITE_API_KEY")
        access_token = access_token or os.environ.get("KITE_ACCESS_TOKEN")
        if not api_key or not access_token:
            raise RuntimeError("KITE_API_KEY and KITE_ACCESS_TOKEN must be set")
        self.client = KiteConnect(api_key=api_key)
        self.client.set_access_token(access_token)
        self._tick_sizes = None

    def holdings(self):
        return {
            item["tradingsymbol"].upper(): max(0, int(item.get("quantity", 0)))
            for item in self.client.holdings()
            if item.get("exchange") == "NSE" and int(item.get("quantity", 0)) > 0
        }

    def last_prices(self, symbols):
        symbols = sorted(set(symbols))
        if not symbols:
            return {}
        keys = [f"NSE:{symbol}" for symbol in symbols]
        quotes = self.client.ltp(keys)
        prices = {}
        for symbol in symbols:
            key = f"NSE:{symbol}"
            if key not in quotes or float(quotes[key].get("last_price", 0)) <= 0:
                raise RuntimeError(f"Kite returned no positive LTP for {symbol}")
            prices[symbol] = float(quotes[key]["last_price"])
        return prices

    def available_cash(self):
        margins = self.client.margins("equity")
        available = margins.get("available", {})
        return float(available.get("live_balance", available.get("cash", 0.0)))

    def _load_tick_sizes(self):
        if self._tick_sizes is None:
            self._tick_sizes = {
                item["tradingsymbol"].upper(): float(item.get("tick_size") or 0.05)
                for item in self.client.instruments("NSE")
                if item.get("segment") == "NSE"
            }

    def place(self, intent, order_type="LIMIT", limit_buffer_bps=20.0, variety="regular", tag=None):
        order_type = order_type.upper()
        if order_type not in {"LIMIT", "MARKET"}:
            raise ValueError("order_type must be LIMIT or MARKET")
        kwargs = {
            "variety": variety,
            "exchange": self.client.EXCHANGE_NSE,
            "tradingsymbol": intent.symbol,
            "transaction_type": intent.side,
            "quantity": intent.quantity,
            "product": self.client.PRODUCT_CNC,
            "order_type": order_type,
            "validity": self.client.VALIDITY_DAY,
            "tag": tag,
        }
        if order_type == "LIMIT":
            self._load_tick_sizes()
            tick_size = self._tick_sizes.get(intent.symbol, 0.05)
            direction = 1.0 if intent.side == "BUY" else -1.0
            raw_price = intent.reference_price * (
                1.0 + direction * limit_buffer_bps / 10_000.0
            )
            kwargs["price"] = round_to_tick(raw_price, tick_size, intent.side)
        else:
            kwargs["market_protection"] = -1
        return self.client.place_order(**kwargs)
