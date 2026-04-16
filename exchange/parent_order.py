"""Parent order model for multi-tick execution algorithms."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ParentOrder:
    """A parent order to be executed over multiple ticks."""

    instrument: str
    side: str  # "buy" or "sell"
    target_qty: float
    algo: str = "twap"  # "twap" or "immediate"
    duration_ticks: int = 5
    urgency: float = 0.7  # 0.0 (passive) to 1.0 (aggressive)
    filled_qty: float = 0.0
    child_fills: List[Dict] = field(default_factory=list)
    status: str = "active"  # "active", "complete", "cancelled"
    ticks_elapsed: int = 0
    created_at_ms: int = 0
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def remaining_qty(self) -> float:
        return self.target_qty - self.filled_qty

    @property
    def progress(self) -> float:
        if self.target_qty <= 0:
            return 0.0
        return self.filled_qty / self.target_qty

    @property
    def is_complete(self) -> bool:
        return self.status != "active"

    def record_fill(self, qty: float, price: float, timestamp_ms: int) -> None:
        """Record a child fill and update state."""
        self.child_fills.append({
            "qty": qty,
            "price": price,
            "timestamp_ms": timestamp_ms,
        })
        self.filled_qty += qty
        if self.remaining_qty <= 0:
            self.status = "complete"
