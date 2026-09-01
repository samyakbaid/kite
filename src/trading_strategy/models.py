from dataclasses import asdict, dataclass
from datetime import date


@dataclass(frozen=True)
class Signal:
    signal_date: date
    model: str
    universe_kind: str
    rank: int
    symbol: str
    score: float
    target_weight: float


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: str
    quantity: int
    reference_price: float
    estimated_value: float
    reason: str

    def to_dict(self):
        return asdict(self)
