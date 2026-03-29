"""GuardIterator — wraps modules/trailing_stop.py for per-position trailing stops."""
from __future__ import annotations

import logging
from typing import Dict, Optional

from cli.daemon.context import Alert, OrderIntent, TickContext
from modules.guard_config import GuardConfig
from modules.guard_state import GuardState
from modules.trailing_stop import GuardAction, TrailingStopEngine

log = logging.getLogger("daemon.guard")


class GuardIterator:
    name = "guard"

    def __init__(self, config: Optional[GuardConfig] = None):
        self._config = config or GuardConfig()
        self._engine = TrailingStopEngine(self._config)
        self._states: Dict[str, GuardState] = {}  # instrument → state

    def on_start(self, ctx: TickContext) -> None:
        log.info("GuardIterator started")

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        from decimal import Decimal

        for pos in ctx.positions:
            inst = pos.instrument if hasattr(pos, 'instrument') else str(pos)
            price = ctx.prices.get(inst)
            if price is None:
                continue

            # Get or create guard state for this position
            if inst not in self._states:
                entry_price = float(pos.entry_price) if hasattr(pos, 'entry_price') else float(price)
                direction = "long" if (hasattr(pos, 'net_qty') and pos.net_qty > 0) else "short"
                self._states[inst] = GuardState(
                    entry_price=entry_price,
                    direction=direction,
                    peak_price=entry_price,
                )

            state = self._states[inst]
            result = self._engine.evaluate(float(price), state)
            self._states[inst] = result.state

            if result.action == GuardAction.CLOSE:
                log.info("Guard closing %s: %s (ROE=%.2f%%)", inst, result.reason, result.roe_pct)
                ctx.order_queue.append(OrderIntent(
                    strategy_name="guard",
                    instrument=inst,
                    action="close",
                    size=Decimal("0"),
                    reduce_only=True,
                    meta={"reason": result.reason, "roe_pct": result.roe_pct},
                ))
                ctx.alerts.append(Alert(
                    severity="warning",
                    source=self.name,
                    message=f"Closing {inst}: {result.reason}",
                ))
                del self._states[inst]
            elif result.action == GuardAction.TIER_CHANGED:
                log.info("Guard tier change on %s: tier=%s", inst, result.new_tier_index)
