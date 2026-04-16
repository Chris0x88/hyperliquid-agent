"""ManagedOrderBook -- holds active managed orders, processes them each tick."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Union

from common.models import MarketSnapshot, StrategyDecision
from exchange.order_types import BracketOrder, ConditionalOrder, PeggedOrder

log = logging.getLogger("order_book")

ManagedOrder = Union[BracketOrder, ConditionalOrder, PeggedOrder]


class ManagedOrderBook:
    """Holds bracket, conditional, and pegged orders. Evaluated each engine tick."""

    def __init__(self):
        self._orders: Dict[str, ManagedOrder] = {}

    def add(self, order: ManagedOrder) -> None:
        self._orders[order.order_id] = order
        log.info(
            "Added %s order %s for %s",
            type(order).__name__, order.order_id, order.instrument,
        )

    def remove(self, order_id: str) -> None:
        self._orders.pop(order_id, None)

    def on_tick(self, snapshot: MarketSnapshot) -> List[StrategyDecision]:
        """Process all managed orders against current snapshot. Return triggered decisions."""
        decisions: List[StrategyDecision] = []
        to_remove: List[str] = []

        for oid, order in self._orders.items():
            result = order.on_tick(snapshot)
            if result is not None:
                decisions.append(result)
            # Clean up completed/triggered/expired orders
            if order.status not in ("active", "pending"):
                to_remove.append(oid)

        for oid in to_remove:
            del self._orders[oid]

        return decisions

    @property
    def count(self) -> int:
        return len(self._orders)

    @property
    def active_orders(self) -> Dict[str, ManagedOrder]:
        return dict(self._orders)

    def get(self, order_id: str) -> Optional[ManagedOrder]:
        return self._orders.get(order_id)
