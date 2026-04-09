"""LiquidityIterator — adjusts risk based on time-of-day and market liquidity.

Low-liquidity periods are dangerous:
  - Weekends: HL perps trade 24/7 but volume drops ~60-80%
  - After-hours (22:00-06:00 UTC): No US/EU institutional flow
  - Holidays: even less volume

In low liquidity:
  - Stop hunts are common (big players sweep stops)
  - Slippage is higher
  - Price can gap sharply on small volume

This iterator:
  1. Detects current liquidity regime
  2. Adjusts position sizing via ctx metadata
  3. Widens trailing stop thresholds
  4. Alerts when entering/exiting low-liquidity windows
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.liquidity")


class LiquidityRegime(Enum):
    NORMAL = "normal"         # US/EU market hours, weekday
    LOW = "low"               # After-hours weekday
    WEEKEND = "weekend"       # Saturday/Sunday
    DANGEROUS = "dangerous"   # Weekend + after-hours (worst)


# Size multipliers per regime — lower = smaller positions
REGIME_SIZE_MULT = {
    LiquidityRegime.NORMAL: 1.0,
    LiquidityRegime.LOW: 0.6,
    LiquidityRegime.WEEKEND: 0.4,
    LiquidityRegime.DANGEROUS: 0.25,
}

# Stop width multipliers — higher = wider stops to avoid stop hunts
REGIME_STOP_MULT = {
    LiquidityRegime.NORMAL: 1.0,
    LiquidityRegime.LOW: 1.3,
    LiquidityRegime.WEEKEND: 1.5,
    LiquidityRegime.DANGEROUS: 2.0,
}


class LiquidityIterator:
    """Adjusts risk parameters based on time-of-day liquidity regime."""
    name = "liquidity"

    def __init__(self):
        self._last_regime: Optional[LiquidityRegime] = None

    def on_start(self, ctx: TickContext) -> None:
        regime = self._detect_regime()
        self._last_regime = regime
        log.info("LiquidityIterator started — regime=%s", regime.value)

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        regime = self._detect_regime()

        # Alert on regime change
        if self._last_regime and regime != self._last_regime:
            if regime in (LiquidityRegime.WEEKEND, LiquidityRegime.DANGEROUS):
                ctx.alerts.append(Alert(
                    severity="warning",
                    source="liquidity",
                    message=f"Liquidity dropped to _{regime.value.replace('_', ' ')}_\n"
                            f"  Sizes reduced to {REGIME_SIZE_MULT[regime]:.0%}, stops widened {REGIME_STOP_MULT[regime]:.1f}x",
                ))
            elif self._last_regime in (LiquidityRegime.WEEKEND, LiquidityRegime.DANGEROUS):
                ctx.alerts.append(Alert(
                    severity="info",
                    source="liquidity",
                    message=f"Liquidity improving — back to _{regime.value.replace('_', ' ')}_",
                ))

        self._last_regime = regime

        # Store regime info in TickContext for other iterators to consume
        # We use the alerts data dict as a lightweight metadata channel
        ctx.alerts.append(Alert(
            severity="info",
            source="liquidity",
            message=f"Liquidity: {regime.value.replace('_', ' ').title()}",
            data={
                "regime": regime.value,
                "size_mult": REGIME_SIZE_MULT[regime],
                "stop_mult": REGIME_STOP_MULT[regime],
            },
        ))

    @staticmethod
    def _detect_regime() -> LiquidityRegime:
        """Detect current liquidity regime from UTC time."""
        now = datetime.now(timezone.utc)
        hour = now.hour
        weekday = now.weekday()  # 0=Monday, 6=Sunday

        is_weekend = weekday >= 5  # Saturday or Sunday
        is_after_hours = hour >= 22 or hour < 6  # 22:00-06:00 UTC

        if is_weekend and is_after_hours:
            return LiquidityRegime.DANGEROUS
        elif is_weekend:
            return LiquidityRegime.WEEKEND
        elif is_after_hours:
            return LiquidityRegime.LOW
        else:
            return LiquidityRegime.NORMAL

    @staticmethod
    def get_regime_multipliers() -> dict:
        """Get current regime multipliers (callable from outside daemon)."""
        regime = LiquidityIterator._detect_regime()
        return {
            "regime": regime.value,
            "size_mult": REGIME_SIZE_MULT[regime],
            "stop_mult": REGIME_STOP_MULT[regime],
        }
