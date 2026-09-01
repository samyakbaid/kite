import csv
import hashlib
import re
from datetime import date
from pathlib import Path

from .models import Signal


SYMBOL_RE = re.compile(r"^[A-Z0-9&._-]+$")
REQUIRED_COLUMNS = {
    "signal_date",
    "model",
    "universe_kind",
    "rank",
    "symbol",
    "score",
    "target_weight",
}


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_signals(path, today=None, max_age_days=45, expected_sha256=None):
    path = Path(path)
    if expected_sha256 and sha256_file(path) != expected_sha256:
        raise ValueError(f"signal checksum mismatch: {path}")

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            missing = REQUIRED_COLUMNS.difference(reader.fieldnames or [])
            raise ValueError(f"signal file is missing columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError("signal file is empty")

    signals = []
    for row in rows:
        signal_date = date.fromisoformat(row["signal_date"])
        symbol = row["symbol"].strip().upper().removesuffix(".NS")
        if not SYMBOL_RE.fullmatch(symbol):
            raise ValueError(f"invalid NSE symbol in signal file: {symbol!r}")
        signal = Signal(
            signal_date=signal_date,
            model=row["model"].strip(),
            universe_kind=row["universe_kind"].strip().lower(),
            rank=int(row["rank"]),
            symbol=symbol,
            score=float(row["score"]),
            target_weight=float(row["target_weight"]),
        )
        if signal.rank <= 0 or not 0.0 <= signal.target_weight <= 1.0:
            raise ValueError(f"invalid rank or weight for {symbol}")
        if signal.universe_kind not in {"proxy", "provided", "official"}:
            raise ValueError(f"invalid universe_kind for {symbol}")
        signals.append(signal)

    models = {signal.model for signal in signals}
    dates = {signal.signal_date for signal in signals}
    universe_kinds = {signal.universe_kind for signal in signals}
    ranks = [signal.rank for signal in signals]
    symbols = [signal.symbol for signal in signals]
    if len(models) != 1 or len(dates) != 1 or len(universe_kinds) != 1:
        raise ValueError(
            "one signal file must contain exactly one model, signal date, and universe kind"
        )
    if len(ranks) != len(set(ranks)) or len(symbols) != len(set(symbols)):
        raise ValueError("signal ranks and symbols must be unique")
    signals.sort(key=lambda signal: signal.rank)
    if ranks and [signal.rank for signal in signals] != list(range(1, len(signals) + 1)):
        raise ValueError("signal ranks must be consecutive starting at 1")

    today = today or date.today()
    age_days = (today - signals[0].signal_date).days
    if age_days < 0:
        raise ValueError("signal date is in the future")
    if max_age_days is not None and age_days > max_age_days:
        raise ValueError(
            f"signal is stale ({age_days} days old; maximum is {max_age_days})"
        )
    return signals
