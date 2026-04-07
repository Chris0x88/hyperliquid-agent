"""GuardIterator — per-position trailing stops with exchange-level SL sync.

Wraps modules/guard_bridge.py to:
  1. Evaluate Guard (trailing stop engine) on each tick
  2. Sync exchange-level SL trigger orders to match the Guard's current floor
  3. Queue close orders when Guard signals CLOSE

This is the second line of defense after ExchangeProtectionIterator.
ExchangeProtection sets a static SL at entry - X%; Guard RATCHETS the SL
upward as profit grows (trailing stop), and syncs that tighter SL to the
exchange.  Together they ensure the exchange always has a protective order.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from cli.daemon.context import Alert, OrderIntent, TickContext
from common.authority import is_agent_managed
from modules.guard_bridge import GuardBridge
from modules.guard_config import GuardConfig, PRESETS
from modules.guard_state import GuardState, GuardStateStore
from modules.trailing_stop import GuardAction

log = logging.getLogger("daemon.guard")


class GuardIterator:
    name = "guard"

    def __init__(
        self,
        config: Optional[GuardConfig] = None,
        adapter: Any = None,
        data_dir: str = "data/guard",
    ):
        self._config = config or PRESETS.get("moderate", GuardConfig())
        self._adapter = adapter
        self._store = GuardStateStore(data_dir=data_dir)
        self._bridges: Dict[str, GuardBridge] = {}  # instrument -> GuardBridge

    def on_start(self, ctx: TickContext) -> None:
        # Restore any active guards from disk
        for pos_id in self._store.list_active():
            bridge = GuardBridge.from_store(pos_id, self._store)
            if bridge and bridge.is_active:
                self._bridges[bridge.state.instrument] = bridge
                log.info(
                    "Restored guard for %s  entry=%.2f  tier=%d  floor_oid=%s",
                    bridge.state.instrument,
                    bridge.state.entry_price,
                    bridge.state.current_tier_index,
                    bridge.state.exchange_sl_oid or "(none)",
                )
        log.info("GuardIterator started — %d active guards, config=%s",
                 len(self._bridges), self._config.direction)

    def on_stop(self) -> None:
        for bridge in self._bridges.values():
            if bridge.is_active:
                self._store.save(bridge.state, bridge.config.to_dict())
        log.info("GuardIterator stopped — %d guards persisted", len(self._bridges))

    def tick(self, ctx: TickContext) -> None:
        for pos in ctx.positions:
            inst = pos.instrument
            price = ctx.prices.get(inst)
            if price is None:
                continue

            # H4 hardening — per-asset authority gate (closes the LATENT-REBALANCE
            # gap from the 2026-04-07 verification ledger and the FAQ admission
            # in tier-state-machine.md). Guard runs in REBALANCE+ tiers and used
            # to apply trailing stops to every position regardless of delegation.
            # Now: skip non-delegated assets, and if a previously-tracked asset
            # was reclaimed (agent → manual or off), tear down its bridge and
            # cancel its exchange SL on this tick.
            if not is_agent_managed(inst):
                if inst in self._bridges:
                    log.info(
                        "GuardIterator: tearing down bridge for %s — authority reclaimed",
                        inst,
                    )
                    bridge = self._bridges.pop(inst)
                    bridge.mark_closed(float(price), "authority_reclaimed")
                    if self._adapter:
                        bridge.cancel_exchange_sl(self._adapter, inst)
                    ctx.alerts.append(Alert(
                        severity="info",
                        source=self.name,
                        message=f"Guard released {inst} (authority reclaimed)",
                    ))
                else:
                    # BUG-FIX 2026-04-08: the "new position, not delegated"
                    # path was previously a silent continue.  Add an INFO
                    # log so operators can see the H4 gate firing in the
                    # daemon log per tick, matching H1/H2 visibility.
                    log.info(
                        "GuardIterator skipping %s — authority is not 'agent' (H4 gate)",
                        inst,
                    )
                continue

            qty = pos.net_qty
            if qty == 0:
                # Position closed — clean up guard
                if inst in self._bridges:
                    bridge = self._bridges.pop(inst)
                    bridge.mark_closed(float(price), "position_closed")
                    if self._adapter:
                        bridge.cancel_exchange_sl(self._adapter, inst)
                continue

            # Get or create GuardBridge for this position
            bridge = self._bridges.get(inst)
            if bridge is None:
                bridge = self._create_bridge(inst, pos, float(price))
                self._bridges[inst] = bridge
                log.info(
                    "Created guard for %s  entry=%.4f  size=%.6f  dir=%s",
                    inst, bridge.state.entry_price,
                    bridge.state.position_size, bridge.state.direction,
                )

            # Run Guard evaluation
            result = bridge.check(float(price))

            if result.action == GuardAction.CLOSE:
                log.info("Guard CLOSE for %s: %s (ROE=%.2f%%)", inst, result.reason, result.roe_pct)
                close_side = "sell" if qty > 0 else "buy"
                ctx.order_queue.append(OrderIntent(
                    strategy_name="guard",
                    instrument=inst,
                    action=close_side,
                    size=abs(qty),
                    reduce_only=True,
                    order_type="Ioc",
                    meta={"reason": result.reason, "roe_pct": result.roe_pct},
                ))
                ctx.alerts.append(Alert(
                    severity="critical",
                    source=self.name,
                    message=f"Guard closing {inst}: {result.reason} (ROE={result.roe_pct:.1f}%)",
                    data={"instrument": inst, "roe_pct": result.roe_pct},
                ))
                bridge.mark_closed(float(price), result.reason)
                if self._adapter:
                    bridge.cancel_exchange_sl(self._adapter, inst)
                self._bridges.pop(inst, None)

            elif result.action == GuardAction.TIER_CHANGED:
                log.info("Guard tier change on %s: tier=%d  floor=%.4f",
                         inst, result.new_tier_index or 0, result.effective_floor)
                ctx.alerts.append(Alert(
                    severity="info",
                    source=self.name,
                    message=(
                        f"Guard tier upgrade on {inst}: "
                        f"tier={result.new_tier_index} floor={result.effective_floor:.4f}"
                    ),
                ))
                # Sync tighter SL to exchange
                if self._adapter:
                    bridge.sync_exchange_sl(self._adapter, inst)

            elif result.action in (GuardAction.PHASE1_TIMEOUT, GuardAction.WEAK_PEAK_CUT):
                log.info("Guard %s for %s: %s", result.action.value, inst, result.reason)
                close_side = "sell" if qty > 0 else "buy"
                ctx.order_queue.append(OrderIntent(
                    strategy_name="guard",
                    instrument=inst,
                    action=close_side,
                    size=abs(qty),
                    reduce_only=True,
                    order_type="Ioc",
                    meta={"reason": result.reason, "roe_pct": result.roe_pct},
                ))
                ctx.alerts.append(Alert(
                    severity="warning",
                    source=self.name,
                    message=f"Guard {result.action.value} on {inst}: {result.reason}",
                ))
                bridge.mark_closed(float(price), result.reason)
                if self._adapter:
                    bridge.cancel_exchange_sl(self._adapter, inst)
                self._bridges.pop(inst, None)

            else:
                # HOLD — periodically re-sync exchange SL (every tier check)
                # This ensures exchange SL follows trailing floor even during HOLD
                if self._adapter and result.effective_floor > 0:
                    bridge.sync_exchange_sl(self._adapter, inst)

    def _create_bridge(self, inst: str, pos: Any, price: float) -> GuardBridge:
        """Create a new GuardBridge for a position."""
        direction = "long" if pos.net_qty > 0 else "short"
        entry = float(pos.avg_entry_price) if pos.avg_entry_price > 0 else price
        size = float(abs(pos.net_qty))

        state = GuardState.new(
            instrument=inst,
            entry_price=entry,
            position_size=size,
            direction=direction,
            position_id=inst,
        )

        # Clone config with correct direction
        config = GuardConfig.from_dict(self._config.to_dict())
        config.direction = direction

        return GuardBridge(config=config, state=state, store=self._store)
