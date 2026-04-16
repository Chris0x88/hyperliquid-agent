"""ExecutionEngineIterator — conviction-based adaptive sizing and ruin prevention.

Layer 2 of the two-layer architecture. Reads ThesisState from ctx.thesis_states
(written by AI, injected by thesis_engine) and generates OrderIntents to size
positions appropriately.

Conviction bands (Druckenmiller 70-80% rule):
  0.8-1.0  → 20% account, 15x max leverage (full conviction, pyramid dips)
  0.5-0.8  → 12% account, 10x max leverage (standard position)
  0.2-0.5  →  6% account,  5x max leverage (cautious)
  0.0-0.2  →  0% account,  0x (exit positions)

Account-level ruin prevention (UNCONDITIONAL — cannot be overridden by AI):
  25% drawdown: halt new entries
  40% drawdown: close ALL positions

Time-aware leverage caps:
  Weekend (Fri 4PM–Sun 6PM ET): reduce leverage by 50%
  Thin session (8PM–3AM ET): cap leverage at 7x
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from daemon.context import Alert, OrderIntent, TickContext
from common.authority import is_agent_managed
from trading.thesis.state import ThesisState

log = logging.getLogger("daemon.execution_engine")

ZERO = Decimal("0")

# Ruin prevention thresholds (absolute, cannot be thesis-overridden)
HALT_DRAWDOWN_PCT = 25.0    # stop new entries
RUIN_DRAWDOWN_PCT = 40.0    # close all immediately

# Rebalance only when position delta exceeds this fraction of target
REBALANCE_THRESHOLD = 0.05  # 5%
REBALANCE_INTERVAL_S = 120  # check every 2 minutes


def _is_weekend_et() -> bool:
    """True during thin weekend hours (Fri 4PM ET to Sun 6PM ET)."""
    # ET offset: UTC-5 (EST) or UTC-4 (EDT). Use UTC-5 conservatively.
    et_offset = -5 * 3600
    ts = time.time() + et_offset
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    weekday = dt.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour = dt.hour

    if weekday == 4 and hour >= 16:  # Friday 4PM ET+
        return True
    if weekday == 5:  # Saturday all day
        return True
    if weekday == 6 and hour < 18:  # Sunday before 6PM ET
        return True
    return False


def _is_thin_session_et() -> bool:
    """True during thin Asian overnight hours (8PM–3AM ET)."""
    et_offset = -5 * 3600
    ts = time.time() + et_offset
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    hour = dt.hour
    return hour >= 20 or hour < 3


def _conviction_band(conviction: float) -> Tuple[float, float, str]:
    """Returns (target_size_pct, max_leverage, band_name) for a conviction score."""
    if conviction >= 0.8:
        return 0.20, 15.0, "full"
    elif conviction >= 0.5:
        return 0.12, 10.0, "standard"
    elif conviction >= 0.2:
        return 0.06, 5.0, "cautious"
    else:
        return 0.0, 0.0, "exit"


class ExecutionEngineIterator:
    """Conviction-based adaptive execution engine."""

    name = "execution_engine"

    def __init__(self, adapter: Any = None):
        self._adapter = adapter
        self._last_rebalance: float = 0.0

    def on_start(self, ctx: TickContext) -> None:
        log.info(
            "ExecutionEngine started  halt_at=%.0f%%  ruin_at=%.0f%%  rebalance_threshold=%.0f%%",
            HALT_DRAWDOWN_PCT, RUIN_DRAWDOWN_PCT, REBALANCE_THRESHOLD * 100,
        )

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        # --- RUIN PREVENTION (unconditional) ---
        drawdown = ctx.account_drawdown_pct

        if drawdown >= RUIN_DRAWDOWN_PCT:
            self._close_all_positions(ctx)
            ctx.alerts.append(Alert(
                severity="critical",
                source=self.name,
                message=f"RUIN PREVENTION: {drawdown:.1f}% drawdown — closing ALL positions",
                data={"drawdown_pct": drawdown, "hwm": ctx.high_water_mark},
            ))
            ctx.risk_gate = type(ctx.risk_gate).CLOSED if hasattr(ctx.risk_gate, 'CLOSED') else ctx.risk_gate
            return

        if drawdown >= HALT_DRAWDOWN_PCT:
            log.warning("Drawdown %.1f%% — halting new entries (threshold: %.0f%%)",
                        drawdown, HALT_DRAWDOWN_PCT)
            # Don't close existing, just don't open new
            return

        # --- Throttle rebalancing ---
        now = time.monotonic()
        if now - self._last_rebalance < REBALANCE_INTERVAL_S:
            return
        self._last_rebalance = now

        # --- Process each thesis market ---
        for market, thesis in ctx.thesis_states.items():
            self._process_market(market, thesis, ctx)

    def _process_market(self, market: str, thesis: ThesisState, ctx: TickContext) -> None:
        """Evaluate and rebalance one market based on thesis conviction."""
        # H2 hardening — explicit per-asset authority gate (closes the
        # LATENT-REBALANCE gap from the 2026-04-07 verification ledger).
        # Even though ctx.thesis_states is normally populated only for
        # delegated assets, a manually-created thesis file or a delegation
        # change between the thesis_engine load and the execution_engine
        # tick could produce a thesis for a non-delegated asset. Refuse
        # to act on anything that isn't 'agent' authority.
        if not is_agent_managed(market):
            log.warning(
                "ExecutionEngine skipping %s — authority is not 'agent' "
                "(thesis present but asset not delegated)",
                market,
            )
            return

        conviction = thesis.effective_conviction()
        target_size_pct, max_lev, band = _conviction_band(conviction)

        # Weekend and thin session leverage caps
        weekend = _is_weekend_et()
        thin = _is_thin_session_et()

        if weekend:
            max_lev = min(max_lev, thesis.weekend_leverage_cap)
        elif thin:
            max_lev = min(max_lev, 7.0)

        # AI-recommended leverage cap (lower of band max and AI recommendation)
        max_lev = min(max_lev, thesis.recommended_leverage)
        target_size_pct = min(target_size_pct, thesis.recommended_size_pct)

        # Get current position
        current_pos = self._find_position(market, ctx)
        account_equity = float(ctx.total_equity or ctx.balances.get("USDC", ZERO))
        if account_equity <= 0:
            log.debug("ExecutionEngine: no equity data yet for %s", market)
            return

        # Get current price
        price = float(ctx.prices.get(market, ZERO))
        if price <= 0:
            log.debug("ExecutionEngine: no price data for %s", market)
            return

        target_notional = account_equity * target_size_pct
        target_qty = target_notional / price if price > 0 else 0

        current_qty = float(current_pos.net_qty) if current_pos else 0.0
        current_notional = abs(current_qty) * price

        # Determine if rebalance needed
        if target_notional > 0:
            delta_pct = abs(current_notional - target_notional) / target_notional
        else:
            delta_pct = 1.0 if current_qty != 0 else 0.0

        if delta_pct < REBALANCE_THRESHOLD:
            log.debug(
                "ExecutionEngine: %s delta=%.1f%% < threshold — no action  "
                "band=%s  conviction=%.2f  weekend=%s",
                market, delta_pct * 100, band, conviction, weekend,
            )
            return

        self._emit_rebalance(
            market, thesis, current_qty, target_qty, band, conviction,
            max_lev, account_equity, ctx,
        )

    def _emit_rebalance(
        self,
        market: str,
        thesis: ThesisState,
        current_qty: float,
        target_qty: float,
        band: str,
        conviction: float,
        max_lev: float,
        account_equity: float,
        ctx: TickContext,
    ) -> None:
        """Queue an OrderIntent to move from current_qty to target_qty."""
        delta = target_qty - current_qty

        if band == "exit":
            if current_qty == 0:
                return
            log.info("ExecutionEngine: %s conviction=%.2f → EXIT (band=%s)", market, conviction, band)
            ctx.order_queue.append(OrderIntent(
                strategy_name=self.name,
                instrument=market,
                action="close",
                size=Decimal(str(abs(current_qty))),
                reduce_only=True,
                meta={
                    "reason": "conviction_exit",
                    "conviction": conviction,
                    "band": band,
                },
            ))
            ctx.alerts.append(Alert(
                severity="warning",
                source=self.name,
                message=f"Exiting {market} — conviction {conviction:.2f} below exit threshold",
                data={"conviction": conviction, "current_qty": current_qty},
            ))
            return

        if abs(delta) < 0.001:
            return

        direction = thesis.direction
        action = "buy" if (direction == "long" and delta > 0) or (direction == "short" and delta < 0) else "sell"
        size = abs(delta)

        log.info(
            "ExecutionEngine: %s %s %.4f  band=%s  conviction=%.2f  max_lev=%.1fx  "
            "target=%.4f  current=%.4f",
            action.upper(), market, size, band, conviction, max_lev,
            target_qty, current_qty,
        )

        ctx.order_queue.append(OrderIntent(
            strategy_name=self.name,
            instrument=market,
            action=action,
            size=Decimal(str(round(size, 4))),
            meta={
                "reason": "conviction_rebalance",
                "conviction": conviction,
                "band": band,
                "max_leverage": max_lev,
                "weekend_mode": _is_weekend_et(),
                "thin_session": _is_thin_session_et(),
                "thesis_direction": thesis.direction,
            },
        ))

        ctx.alerts.append(Alert(
            severity="info",
            source=self.name,
            message=(
                f"ExecutionEngine: {action} {size:.4f} {market}  "
                f"band={band}  conviction={conviction:.2f}  lev≤{max_lev:.1f}x"
            ),
            data={
                "instrument": market, "action": action, "size": size,
                "conviction": conviction, "band": band,
            },
        ))

    def _close_all_positions(self, ctx: TickContext) -> None:
        """Queue close orders for all open positions (ruin prevention)."""
        for pos in ctx.positions:
            if pos.net_qty == ZERO:
                continue
            ctx.order_queue.append(OrderIntent(
                strategy_name=self.name,
                instrument=pos.instrument,
                action="close",
                size=abs(pos.net_qty),
                reduce_only=True,
                meta={"reason": "ruin_prevention", "drawdown_pct": ctx.account_drawdown_pct},
            ))
            log.critical("RUIN: queuing close for %s size=%s", pos.instrument, pos.net_qty)

    def _find_position(self, market: str, ctx: TickContext) -> Optional[Any]:
        """Find position for a market in ctx.positions (handles xyz: prefix)."""
        clean = market.replace("xyz:", "").replace("XYZ:", "")
        for pos in ctx.positions:
            if pos.instrument == market or pos.instrument.replace("xyz:", "") == clean:
                return pos
        return None
