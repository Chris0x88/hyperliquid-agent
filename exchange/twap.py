"""TWAP execution algorithm — slices a parent order across N ticks."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional

from common.models import MarketSnapshot
from exchange.parent_order import ParentOrder


@dataclass
class ChildSlice:
    """A single child order slice to be placed this tick."""

    parent_order_id: str
    instrument: str
    side: str
    size: float
    price: float


class TWAPExecutor:
    """TWAP execution algorithm — slices a parent order across N ticks."""

    def __init__(self):
        self._active_orders: Dict[str, ParentOrder] = {}

    def submit(self, order: ParentOrder) -> None:
        """Register a new parent order for TWAP execution."""
        self._active_orders[order.order_id] = order

    def on_tick(self, snapshot: MarketSnapshot) -> List[ChildSlice]:
        """Called each tick. Returns child slices to execute this tick."""
        slices: List[ChildSlice] = []
        completed: List[str] = []

        for oid, order in self._active_orders.items():
            if order.is_complete:
                completed.append(oid)
                continue

            order.ticks_elapsed += 1
            slice_result = self._compute_slice(order, snapshot)
            if slice_result:
                slices.append(slice_result)

        for oid in completed:
            del self._active_orders[oid]

        return slices

    def record_fill(self, order_id: str, qty: float, price: float, ts: int) -> None:
        """Record a fill for a child slice."""
        order = self._active_orders.get(order_id)
        if order:
            order.record_fill(qty, price, ts)

    def _compute_slice(self, order: ParentOrder, snapshot: MarketSnapshot) -> Optional[ChildSlice]:
        """Compute the child slice for this tick."""
        remaining_ticks = max(order.duration_ticks - order.ticks_elapsed, 1)

        # Base slice: remaining_qty / remaining_ticks
        base_slice = order.remaining_qty / remaining_ticks

        # Urgency adjustment: higher urgency = front-load more
        urgency_factor = 1.0 + order.urgency * 0.5
        slice_qty = base_slice * urgency_factor

        # Cap at remaining
        slice_qty = min(slice_qty, order.remaining_qty)

        # Skip probability for randomization (lower urgency = more skips)
        skip_prob = max(0, 0.2 * (1 - order.urgency))
        if random.random() < skip_prob:
            return None

        # Size jitter (+/- 15%)
        jitter = 1.0 + random.uniform(-0.15, 0.15)
        slice_qty = min(slice_qty * jitter, order.remaining_qty)

        if slice_qty <= 0:
            return None

        # Price: use mid from snapshot with small slippage allowance
        if order.side == "buy":
            price = snapshot.ask if snapshot.ask > 0 else snapshot.mid_price
        else:
            price = snapshot.bid if snapshot.bid > 0 else snapshot.mid_price

        return ChildSlice(
            parent_order_id=order.order_id,
            instrument=order.instrument,
            side=order.side,
            size=round(slice_qty, 6),
            price=price,
        )

    @property
    def active_count(self) -> int:
        return len(self._active_orders)

    @property
    def active_orders(self) -> Dict[str, ParentOrder]:
        return dict(self._active_orders)
