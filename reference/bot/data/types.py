from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class Position:
    symbol: str
    quantity: float
    avg_price: float
    entry_price: float
    opened_ts: float = field(default_factory=lambda: time.time())
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    stop_price: Optional[float] = None
    highest_tier_reached: int = 0
    daily_entry_price: Optional[float] = None
    daily_date: str = ""
    daily_peak_equity: Optional[float] = None  # Track peak equity per coin during the day
    original_quantity: Optional[float] = None  # Track original buy-in quantity for take-profit calculations


@dataclass
class OrderRequest:
    symbol: str
    side: str  # "buy" or "sell"
    price: float
    quantity: float


@dataclass
class OrderResult:
    id: str
    symbol: str
    side: str
    price: float
    quantity: float
    status: str  # submitted, filled, partially_filled, canceled
    ts: float




