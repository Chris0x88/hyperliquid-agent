"""RebalancerIterator — runs BaseStrategy.on_tick() for each roster slot."""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Optional

from cli.daemon.context import Alert, OrderIntent, TickContext
from common.models import MarketSnapshot
from sdk.strategy_sdk.base import StrategyContext

log = logging.getLogger("daemon.rebalancer")


class RebalancerIterator:
    name = "rebalancer"

    def on_start(self, ctx: TickContext) -> None:
        log.info("RebalancerIterator started with %d strategies", len(ctx.active_strategies))

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        now = int(time.time())

        for name, slot in ctx.active_strategies.items():
            if slot.paused or slot.strategy is None:
                continue

            # Check if enough time has passed for this strategy's tick interval
            if slot.last_tick > 0 and (now - slot.last_tick) < slot.tick_interval:
                continue

            price = ctx.prices.get(slot.instrument)
            if price is None:
                log.debug("No price for %s — skipping %s", slot.instrument, name)
                continue

            # Build MarketSnapshot from TickContext
            snapshot = MarketSnapshot(
                instrument=slot.instrument,
                mid_price=float(price),
                bid=float(price * Decimal("0.9999")),
                ask=float(price * Decimal("1.0001")),
                spread_bps=2.0,
                timestamp_ms=ctx.timestamp,
            )

            # Build StrategyContext
            strategy_ctx = StrategyContext(
                snapshot=snapshot,
                round_number=ctx.tick_number,
            )

            # Populate position info if available
            for pos in ctx.positions:
                inst = pos.instrument if hasattr(pos, 'instrument') else ""
                if inst == slot.instrument:
                    if hasattr(pos, 'net_qty'):
                        strategy_ctx.position_qty = float(pos.net_qty)
                    if hasattr(pos, 'unrealized_pnl'):
                        strategy_ctx.unrealized_pnl = float(pos.unrealized_pnl)
                    break

            # Call the strategy
            try:
                decisions = slot.strategy.on_tick(snapshot, strategy_ctx)
                slot.last_tick = now

                for dec in decisions:
                    if dec.action == "noop":
                        continue

                    # Convert StrategyDecision → OrderIntent
                    action = "buy" if dec.side == "buy" else "sell"
                    if dec.action == "close":
                        action = "close"

                    ctx.order_queue.append(OrderIntent(
                        strategy_name=name,
                        instrument=dec.instrument or slot.instrument,
                        action=action,
                        size=Decimal(str(dec.size)),
                        price=Decimal(str(dec.limit_price)) if dec.limit_price else None,
                        order_type=dec.order_type,
                        meta=dec.meta,
                    ))

                if decisions and any(d.action != "noop" for d in decisions):
                    log.info("[%s] Generated %d order(s)", name, len([d for d in decisions if d.action != "noop"]))

            except Exception as e:
                log.error("[%s] on_tick failed: %s", name, e)
                ctx.alerts.append(Alert(
                    severity="warning",
                    source=self.name,
                    message=f"Strategy {name} tick failed: {e}",
                ))
