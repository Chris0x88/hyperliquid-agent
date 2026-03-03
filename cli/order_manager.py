"""Order lifecycle management — place, track, cancel."""
from __future__ import annotations

import logging
from typing import Dict, List, TYPE_CHECKING

from common.models import MarketSnapshot, StrategyDecision
from parent.hl_proxy import HLFill

if TYPE_CHECKING:
    from cli.hl_adapter import DirectHLProxy, DirectMockProxy

log = logging.getLogger("order_manager")


class OrderManager:
    """Manages order lifecycle each tick: cancel stale -> place new -> collect fills.

    Uses IOC (Immediate-or-Cancel) orders by default: each tick the strategy
    produces fresh quotes, they either fill immediately or are discarded.
    """

    def __init__(
        self,
        hl,  # DirectHLProxy | DirectMockProxy
        instrument: str = "ETH-PERP",
        dry_run: bool = False,
        builder: dict = None,
    ):
        self.hl = hl
        self.instrument = instrument
        self.dry_run = dry_run
        self._builder = builder
        self._total_placed = 0
        self._total_filled = 0

    def update(
        self,
        decisions: List[StrategyDecision],
        snapshot: MarketSnapshot,
    ) -> List[HLFill]:
        """Full tick cycle: cancel open orders -> place new -> return fills."""
        fills: List[HLFill] = []

        # 1. Cancel any lingering open orders (safety net for IOC leftovers)
        self.cancel_all()

        # 2. Place new orders from strategy decisions
        for d in decisions:
            if d.action != "place_order" or d.size <= 0 or d.limit_price <= 0:
                continue

            if self.dry_run:
                log.info("[DRY RUN] %s %s %.6f @ %.4f",
                         d.side.upper(), d.instrument or self.instrument,
                         d.size, d.limit_price)
                self._total_placed += 1
                continue

            fill = self.hl.place_order(
                instrument=d.instrument or self.instrument,
                side=d.side,
                size=d.size,
                price=d.limit_price,
                tif="Ioc",
                builder=self._builder,
            )
            self._total_placed += 1
            if fill is not None:
                fills.append(fill)
                self._total_filled += 1

        return fills

    def cancel_all(self) -> int:
        """Cancel all open orders for the instrument."""
        if self.dry_run:
            return 0
        open_orders = self.hl.get_open_orders(self.instrument)
        cancelled = 0
        for order in open_orders:
            oid = order.get("oid", "")
            if oid and self.hl.cancel_order(self.instrument, oid):
                cancelled += 1
        if cancelled:
            log.info("Cancelled %d open orders", cancelled)
        return cancelled

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "total_placed": self._total_placed,
            "total_filled": self._total_filled,
        }
