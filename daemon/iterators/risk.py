"""RiskIterator — wraps parent/risk_manager.py to set risk gate.

Uses the composable ProtectionChain (Freqtrade + LEAN pattern) to run
multiple independent risk checks. Worst gate wins, all reasons consolidated
into a single alert per tick (no spam).
"""
from __future__ import annotations

import logging
from typing import Optional

from daemon.context import Alert, TickContext
from exchange.risk_manager import (
    RiskGate, RiskLimits, RiskManager,
    ProtectionChain, MaxDrawdownProtection, StoplossGuardProtection,
    DailyLossProtection, RuinProtection,
)
from exchange.position_tracker import PositionTracker

log = logging.getLogger("daemon.risk")


class RiskIterator:
    name = "risk"

    def __init__(self, limits: Optional[RiskLimits] = None, mainnet: bool = False,
                 protection_chain: Optional[ProtectionChain] = None):
        self._limits = limits or (RiskLimits.mainnet_defaults() if mainnet else RiskLimits())
        self._risk_mgr = RiskManager(limits=self._limits)
        self._tracker = PositionTracker()
        self._chain = protection_chain or ProtectionChain()

    def on_start(self, ctx: TickContext) -> None:
        log.info("RiskIterator started with %d protections: %s",
                 len(self._chain.protections),
                 [p.name for p in self._chain.protections])

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        mark_prices = {inst: val for inst, val in ctx.prices.items()}

        # 1. Run existing pre-round check (daily drawdown, leverage, circuit breakers)
        ok, reason = self._risk_mgr.pre_round_check(self._tracker, mark_prices)

        if not ok:
            if self._risk_mgr.state.safe_mode:
                ctx.risk_gate = RiskGate.CLOSED
            else:
                ctx.risk_gate = RiskGate.COOLDOWN
            ctx.alerts.append(Alert(
                severity="warning" if ctx.risk_gate == RiskGate.COOLDOWN else "critical",
                source=self.name,
                message=f"Risk gate {ctx.risk_gate.value}: {reason}",
            ))
        else:
            ctx.risk_gate = RiskGate.OPEN

        # 2. Run composable protection chain (Freqtrade/LEAN pattern)
        # Chain runs ALL protections independently, worst gate wins
        has_positions = len(ctx.positions) > 0
        chain_gate, triggered = self._chain.check_all(
            equity=ctx.high_water_mark,  # current HWM-tracked equity
            hwm=ctx.high_water_mark,
            drawdown_pct=ctx.account_drawdown_pct,
            has_positions=has_positions,
            consecutive_losses=self._risk_mgr.state.consecutive_losses,
        )

        # Merge: worst of existing gate and chain gate
        gate_severity = {RiskGate.OPEN: 0, RiskGate.COOLDOWN: 1, RiskGate.CLOSED: 2}
        if gate_severity.get(chain_gate, 0) > gate_severity.get(ctx.risk_gate, 0):
            ctx.risk_gate = chain_gate

        # Consolidated alert: one message with ALL triggered reasons.
        #
        # BUG-FIX 2026-04-08 (alert-format): replaced the single-line
        # ``Protection chain [COOLDOWN]: reason | reason [tag, tag]``
        # with a labelled markdown block so the gate state, reasons, and
        # market context each get their own line.
        if triggered:
            worst_severity = "critical" if chain_gate == RiskGate.CLOSED else "warning"
            # C4: append calendar regime tags so the operator knows the
            # market context the protection chain fired in
            from daemon.calendar_tags import get_current_tags
            from daemon.iterators._format import humanize_tags
            cal = get_current_tags()
            tag_line = (
                f"\n  Market: _{humanize_tags(cal['tags'])}_" if cal["tags"] else ""
            )
            # Human-readable gate label
            gate_label = {
                "CLOSED": "All entries blocked",
                "COOLDOWN": "Cooling down — reduced activity",
                "OPEN": "Normal",
            }.get(chain_gate.value, chain_gate.value)
            # Format reasons as bullet points
            reason_lines = "\n".join(f"  - {t.reason}" for t in triggered)
            ctx.alerts.append(Alert(
                severity=worst_severity,
                source=self.name,
                message=(
                    f"*Risk status — {gate_label}*\n"
                    f"{reason_lines}{tag_line}"
                ),
                data={
                    "calendar_tags": cal["tags"],
                    "weekend": cal["weekend"],
                    "thin_session": cal["thin_session"],
                    "high_impact_event_24h": cal["high_impact_event_24h"],
                },
            ))
