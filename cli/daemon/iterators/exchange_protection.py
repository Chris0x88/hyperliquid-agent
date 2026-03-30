"""ExchangeProtectionIterator — places exchange-level SL/TP trigger orders.

This is the PRIMARY defense against account wipe.  These orders live on the
exchange server and execute even if the bot is offline.

For every open leveraged position the iterator maintains a stop-loss (and,
when the adapter supports it, a take-profit) trigger order on HyperLiquid.
Orders are re-placed when the computed price drifts more than 0.5 % from the
currently tracked order.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Optional

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.exchange_protection")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ProtectionConfig:
    """Global + per-instrument SL/TP configuration."""

    max_loss_pct: Decimal = Decimal("0.05")       # 5 % stop loss
    take_profit_pct: Decimal = Decimal("0.15")     # 15 % take profit
    tick_interval_s: int = 60                      # throttle — one check per minute
    update_threshold_pct: Decimal = Decimal("0.005")  # 0.5 % drift before re-placing

    # Per-instrument overrides:  instrument -> {"max_loss_pct": ..., "take_profit_pct": ...}
    overrides: Dict[str, Dict[str, Decimal]] = field(default_factory=dict)

    def sl_pct(self, instrument: str) -> Decimal:
        ovr = self.overrides.get(instrument)
        if ovr and "max_loss_pct" in ovr:
            return ovr["max_loss_pct"]
        return self.max_loss_pct

    def tp_pct(self, instrument: str) -> Decimal:
        ovr = self.overrides.get(instrument)
        if ovr and "take_profit_pct" in ovr:
            return ovr["take_profit_pct"]
        return self.take_profit_pct


# ---------------------------------------------------------------------------
# Tracked order state
# ---------------------------------------------------------------------------

@dataclass
class TrackedOrders:
    """Exchange order IDs and prices for one instrument."""
    sl_oid: Optional[str] = None
    sl_price: Optional[Decimal] = None
    tp_oid: Optional[str] = None
    tp_price: Optional[Decimal] = None


# ---------------------------------------------------------------------------
# Iterator
# ---------------------------------------------------------------------------

class ExchangeProtectionIterator:
    name = "exchange_protection"

    def __init__(
        self,
        adapter: Any = None,
        config: Optional[ProtectionConfig] = None,
    ):
        self._adapter = adapter
        self._cfg = config or ProtectionConfig()
        self._tracked: Dict[str, TrackedOrders] = {}  # instrument -> TrackedOrders
        self._last_tick: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_start(self, ctx: TickContext) -> None:
        log.info(
            "ExchangeProtectionIterator started  "
            "sl=%.1f%%  tp=%.1f%%  interval=%ds  threshold=%.2f%%",
            float(self._cfg.max_loss_pct) * 100,
            float(self._cfg.take_profit_pct) * 100,
            self._cfg.tick_interval_s,
            float(self._cfg.update_threshold_pct) * 100,
        )
        if self._cfg.overrides:
            for inst, ovr in self._cfg.overrides.items():
                log.info("  override %s: %s", inst, {k: f"{float(v)*100:.1f}%" for k, v in ovr.items()})

    def on_stop(self) -> None:
        """Best-effort cancel of all tracked trigger orders."""
        if self._adapter is None:
            return
        for inst, tracked in list(self._tracked.items()):
            self._cancel_sl(inst, tracked)
            self._cancel_tp(inst, tracked)
        self._tracked.clear()
        log.info("ExchangeProtectionIterator stopped — all tracked orders cancelled")

    # ------------------------------------------------------------------
    # Main tick
    # ------------------------------------------------------------------

    def tick(self, ctx: TickContext) -> None:
        if self._adapter is None:
            return

        # Throttle
        now = time.monotonic()
        if now - self._last_tick < self._cfg.tick_interval_s:
            return
        self._last_tick = now

        # Build set of instruments with an open position
        active_instruments: Dict[str, Any] = {}  # instrument -> Position
        for pos in ctx.positions:
            if pos.net_qty != 0:
                active_instruments[pos.instrument] = pos

        # --- Handle positions that have been closed ---
        closed = [inst for inst in self._tracked if inst not in active_instruments]
        for inst in closed:
            self._cleanup_instrument(inst, ctx)

        # --- Place / update orders for open positions ---
        for inst, pos in active_instruments.items():
            self._protect_position(inst, pos, ctx)

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def _protect_position(self, inst: str, pos: Any, ctx: TickContext) -> None:
        """Ensure exchange SL (and eventually TP) exist for *inst*."""
        entry = Decimal(str(pos.avg_entry_price))
        qty = pos.net_qty  # Decimal; positive = long, negative = short
        size = float(abs(qty))
        is_long = qty > 0

        sl_pct = self._cfg.sl_pct(inst)
        tp_pct = self._cfg.tp_pct(inst)

        # Compute target prices
        if is_long:
            target_sl = entry * (1 - sl_pct)
            target_tp = entry * (1 + tp_pct)
            sl_side = "sell"
            # tp_side = "buy"  # unused until adapter supports TP
        else:
            target_sl = entry * (1 + sl_pct)
            target_tp = entry * (1 - tp_pct)
            sl_side = "buy"
            # tp_side = "sell"  # unused until adapter supports TP

        tracked = self._tracked.get(inst, TrackedOrders())

        # ---- Stop Loss ----
        self._ensure_sl(inst, sl_side, size, target_sl, tracked, ctx)

        # ---- Take Profit ----
        if hasattr(self._adapter, 'place_tp_trigger_order'):
            tp_side = "sell" if is_long else "buy"
            self._ensure_tp(inst, tp_side, size, target_tp, tracked, ctx)
        elif tracked.tp_oid is None:
            log.debug(
                "TP order for %s not placed — adapter lacks TP support.  "
                "Target TP: %s",
                inst, self._fmt_price(target_tp),
            )

        self._tracked[inst] = tracked

    def _ensure_sl(
        self,
        inst: str,
        side: str,
        size: float,
        target_price: Decimal,
        tracked: TrackedOrders,
        ctx: TickContext,
    ) -> None:
        """Place or update the stop-loss trigger order for *inst*."""
        if tracked.sl_oid is not None and tracked.sl_price is not None:
            # Check if current SL is close enough
            drift = abs(target_price - tracked.sl_price) / tracked.sl_price
            if drift <= self._cfg.update_threshold_pct:
                return  # still within tolerance

            # Drift exceeded — cancel old, place new
            log.info(
                "SL for %s drifted %.2f%% — updating  old=%s  new=%s",
                inst,
                float(drift) * 100,
                self._fmt_price(tracked.sl_price),
                self._fmt_price(target_price),
            )
            self._cancel_sl(inst, tracked)

        # Place new SL
        oid = self._adapter.place_trigger_order(
            instrument=inst,
            side=side,
            size=size,
            trigger_price=float(target_price),
        )
        if oid:
            tracked.sl_oid = oid
            tracked.sl_price = target_price
            log.info(
                "Placed SL for %s  oid=%s  side=%s  size=%.6f  trigger=%s",
                inst, oid, side, size, self._fmt_price(target_price),
            )
            ctx.alerts.append(Alert(
                severity="info",
                source=self.name,
                message=f"Exchange SL set for {inst} at {self._fmt_price(target_price)}",
                data={"instrument": inst, "sl_oid": oid, "sl_price": str(target_price)},
            ))
        else:
            log.warning("Failed to place SL for %s at %s", inst, self._fmt_price(target_price))
            ctx.alerts.append(Alert(
                severity="warning",
                source=self.name,
                message=f"Failed to place exchange SL for {inst}",
            ))

    def _ensure_tp(
        self,
        inst: str,
        side: str,
        size: float,
        target_price: Decimal,
        tracked: TrackedOrders,
        ctx: TickContext,
    ) -> None:
        """Place or update the take-profit trigger order for *inst*."""
        if tracked.tp_oid is not None and tracked.tp_price is not None:
            drift = abs(target_price - tracked.tp_price) / tracked.tp_price
            if drift <= self._cfg.update_threshold_pct:
                return

            log.info(
                "TP for %s drifted %.2f%% — updating  old=%s  new=%s",
                inst,
                float(drift) * 100,
                self._fmt_price(tracked.tp_price),
                self._fmt_price(target_price),
            )
            self._cancel_tp(inst, tracked)

        oid = self._adapter.place_tp_trigger_order(
            instrument=inst,
            side=side,
            size=size,
            trigger_price=float(target_price),
        )
        if oid:
            tracked.tp_oid = oid
            tracked.tp_price = target_price
            log.info(
                "Placed TP for %s  oid=%s  side=%s  size=%.6f  trigger=%s",
                inst, oid, side, size, self._fmt_price(target_price),
            )
            ctx.alerts.append(Alert(
                severity="info",
                source=self.name,
                message=f"Exchange TP set for {inst} at {self._fmt_price(target_price)}",
                data={"instrument": inst, "tp_oid": oid, "tp_price": str(target_price)},
            ))
        else:
            log.warning("Failed to place TP for %s at %s", inst, self._fmt_price(target_price))

    # ------------------------------------------------------------------
    # Cancellation helpers
    # ------------------------------------------------------------------

    def _cancel_sl(self, inst: str, tracked: TrackedOrders) -> None:
        if tracked.sl_oid is None:
            return
        ok = self._adapter.cancel_trigger_order(inst, tracked.sl_oid)
        if ok:
            log.info("Cancelled SL for %s  oid=%s", inst, tracked.sl_oid)
        else:
            log.warning("Failed to cancel SL for %s  oid=%s", inst, tracked.sl_oid)
        tracked.sl_oid = None
        tracked.sl_price = None

    def _cancel_tp(self, inst: str, tracked: TrackedOrders) -> None:
        """Cancel TP order (ready for when adapter supports TP)."""
        if tracked.tp_oid is None:
            return
        ok = self._adapter.cancel_trigger_order(inst, tracked.tp_oid)
        if ok:
            log.info("Cancelled TP for %s  oid=%s", inst, tracked.tp_oid)
        else:
            log.warning("Failed to cancel TP for %s  oid=%s", inst, tracked.tp_oid)
        tracked.tp_oid = None
        tracked.tp_price = None

    def _cleanup_instrument(self, inst: str, ctx: TickContext) -> None:
        """Position closed — cancel all tracked orders for *inst*."""
        tracked = self._tracked.pop(inst, None)
        if tracked is None:
            return
        log.info("Position closed for %s — cancelling exchange protection orders", inst)
        self._cancel_sl(inst, tracked)
        self._cancel_tp(inst, tracked)
        ctx.alerts.append(Alert(
            severity="info",
            source=self.name,
            message=f"Exchange protection removed for {inst} (position closed)",
        ))

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_price(price: Decimal) -> str:
        """Human-readable price string."""
        f = float(price)
        if f >= 1000:
            return f"{f:,.2f}"
        if f >= 1:
            return f"{f:.4f}"
        return f"{f:.6f}"
