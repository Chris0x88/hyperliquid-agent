"""ExchangeProtectionIterator — ruin prevention only.

Places exchange-level stop-loss trigger orders just above the liquidation price.
This is NOT a trading stop. It is a "don't die" failsafe.

  SL = liquidation_price * 1.02  (2% buffer above liq)

No fixed percentages. No take-profit orders (conviction changes = position size
changes via execution_engine, not TP orders). This iterator has one job: ensure
the account never gets liquidated even if the bot is offline.

Why ruin-prevention only:
  - Fixed % stops get hunted on weekends on leveraged positions
  - Thesis-driven exits are handled by execution_engine (conviction band → exit)
  - TP orders conflict with conviction-based pyramid-on-dip strategy
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Optional

from cli.daemon.context import Alert, TickContext
from common.authority import is_agent_managed

log = logging.getLogger("daemon.exchange_protection")

ZERO = Decimal("0")

# Buffer above liquidation price for exchange SL
LIQ_BUFFER = Decimal("0.02")    # 2% above liquidation price

# Throttling
TICK_INTERVAL_S = 60             # check once per minute
UPDATE_THRESHOLD = Decimal("0.005")  # only update if SL price drifted > 0.5%


@dataclass
class RuinProtectionConfig:
    """Configuration for ruin prevention SL placement."""
    buffer_above_liq_pct: Decimal = LIQ_BUFFER
    tick_interval_s: int = TICK_INTERVAL_S
    update_threshold_pct: Decimal = UPDATE_THRESHOLD


@dataclass
class TrackedSL:
    """One tracked exchange SL order."""
    sl_oid: Optional[str] = None
    sl_price: Optional[Decimal] = None


class ExchangeProtectionIterator:
    """Ruin prevention: maintains exchange-level SL just above liquidation price."""

    name = "exchange_protection"

    def __init__(
        self,
        adapter: Any = None,
        config: Optional[RuinProtectionConfig] = None,
    ):
        self._adapter = adapter
        self._cfg = config or RuinProtectionConfig()
        self._tracked: Dict[str, TrackedSL] = {}
        self._last_tick: float = 0.0

    def on_start(self, ctx: TickContext) -> None:
        log.info(
            "ExchangeProtection (ruin-prevention) started  "
            "liq_buffer=%.1f%%  interval=%ds  threshold=%.2f%%",
            float(self._cfg.buffer_above_liq_pct) * 100,
            self._cfg.tick_interval_s,
            float(self._cfg.update_threshold_pct) * 100,
        )

    def on_stop(self) -> None:
        if self._adapter is None:
            return
        for inst, tracked in list(self._tracked.items()):
            self._cancel_sl(inst, tracked)
        self._tracked.clear()
        log.info("ExchangeProtection stopped — all SL orders cancelled")

    def tick(self, ctx: TickContext) -> None:
        if self._adapter is None:
            return

        now = time.monotonic()
        if now - self._last_tick < self._cfg.tick_interval_s:
            return
        self._last_tick = now

        # Active instruments with open positions where the bot has authority.
        # Per-asset authority gate (H1 hardening — closes the LATENT-REBALANCE gap
        # documented in writers-and-authority.md): only positions whose asset is
        # delegated to the agent get an SL placed/maintained here. Manual or 'off'
        # assets are skipped — they're managed by the user (or by heartbeat in
        # WATCH tier, which has its own authority gate). When authority is
        # reclaimed (agent → manual), the asset falls out of 'active' on the
        # next tick and the cleanup loop below cancels any SL we previously
        # placed.
        active: Dict[str, Any] = {}
        for pos in ctx.positions:
            if pos.net_qty == ZERO:
                continue
            if not is_agent_managed(pos.instrument):
                log.debug(
                    "ExchangeProtection skipping %s — authority is not 'agent'",
                    pos.instrument,
                )
                continue
            active[pos.instrument] = pos

        # Clean up closed positions and assets where authority was reclaimed
        closed = [inst for inst in self._tracked if inst not in active]
        for inst in closed:
            tracked = self._tracked.pop(inst)
            self._cancel_sl(inst, tracked)
            ctx.alerts.append(Alert(
                severity="info",
                source=self.name,
                message=f"Exchange SL removed for {inst} (position closed or authority reclaimed)",
            ))

        # Place/update SL for each agent-managed open position
        for inst, pos in active.items():
            self._protect_position(inst, pos, ctx)

    def _protect_position(self, inst: str, pos: Any, ctx: TickContext) -> None:
        """Ensure a ruin-prevention SL exists for this position."""
        liq_px = Decimal(str(pos.liquidation_price)) if pos.liquidation_price else ZERO
        entry_px = Decimal(str(pos.avg_entry_price))
        qty = pos.net_qty
        size = float(abs(qty))
        is_long = qty > ZERO

        if liq_px <= ZERO:
            # No liquidation price from exchange — skip, don't guess
            log.debug("No liq price for %s — exchange_protection cannot compute SL", inst)
            return

        # SL = liq_px * 1.02 for longs (above liq), liq_px * 0.98 for shorts
        if is_long:
            target_sl = liq_px * (1 + self._cfg.buffer_above_liq_pct)
            sl_side = "sell"
        else:
            target_sl = liq_px * (1 - self._cfg.buffer_above_liq_pct)
            sl_side = "buy"

        tracked = self._tracked.get(inst, TrackedSL())

        # Check if existing SL needs update
        if tracked.sl_oid and tracked.sl_price:
            drift = abs(target_sl - tracked.sl_price) / tracked.sl_price
            if drift <= self._cfg.update_threshold_pct:
                return  # within tolerance, no action needed
            log.info(
                "SL for %s drifted %.2f%% — updating  old=%s  new=%s",
                inst, float(drift) * 100,
                self._fmt(tracked.sl_price), self._fmt(target_sl),
            )
            self._cancel_sl(inst, tracked)

        # Place new ruin-prevention SL
        oid = self._adapter.place_trigger_order(
            instrument=inst,
            side=sl_side,
            size=size,
            trigger_price=float(target_sl),
        )
        if oid:
            tracked.sl_oid = oid
            tracked.sl_price = target_sl
            log.info(
                "Ruin-prevention SL set: %s  oid=%s  trigger=%s  liq=%s  side=%s  size=%.4f",
                inst, oid, self._fmt(target_sl), self._fmt(liq_px), sl_side, size,
            )
            ctx.alerts.append(Alert(
                severity="info",
                source=self.name,
                message=f"Ruin-prevention SL: {inst} @ {self._fmt(target_sl)} (liq={self._fmt(liq_px)})",
                data={"instrument": inst, "sl_price": str(target_sl), "liq_price": str(liq_px)},
            ))
        else:
            log.warning("Failed to place ruin-prevention SL for %s", inst)
            ctx.alerts.append(Alert(
                severity="critical",
                source=self.name,
                message=f"FAILED to place ruin-prevention SL for {inst} at {self._fmt(target_sl)}",
            ))

        self._tracked[inst] = tracked

    def _cancel_sl(self, inst: str, tracked: TrackedSL) -> None:
        if tracked.sl_oid is None:
            return
        if self._adapter and hasattr(self._adapter, 'cancel_trigger_order'):
            ok = self._adapter.cancel_trigger_order(inst, tracked.sl_oid)
            if ok:
                log.info("Cancelled SL for %s  oid=%s", inst, tracked.sl_oid)
            else:
                log.warning("Failed to cancel SL for %s  oid=%s", inst, tracked.sl_oid)
        tracked.sl_oid = None
        tracked.sl_price = None

    @staticmethod
    def _fmt(price: Decimal) -> str:
        f = float(price)
        if f >= 1000:
            return f"{f:,.2f}"
        if f >= 1:
            return f"{f:.4f}"
        return f"{f:.6f}"
