"""RiskIterator — wraps parent/risk_manager.py to set risk gate."""
from __future__ import annotations

import logging
from typing import Optional

from cli.daemon.context import Alert, TickContext
from parent.risk_manager import RiskGate, RiskLimits, RiskManager
from parent.position_tracker import PositionTracker

log = logging.getLogger("daemon.risk")


class RiskIterator:
    name = "risk"

    def __init__(self, limits: Optional[RiskLimits] = None, mainnet: bool = False):
        self._limits = limits or (RiskLimits.mainnet_defaults() if mainnet else RiskLimits())
        self._risk_mgr = RiskManager(limits=self._limits)
        self._tracker = PositionTracker()

    def on_start(self, ctx: TickContext) -> None:
        log.info("RiskIterator started")

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        # Build mark prices from context
        mark_prices = {inst: val for inst, val in ctx.prices.items()}

        # Run pre-round check
        ok, reason = self._risk_mgr.pre_round_check(self._tracker, mark_prices)

        if not ok:
            # Determine gate from risk manager state
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
