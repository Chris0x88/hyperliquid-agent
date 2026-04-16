"""Consolidation — detects when a sharp price drop has stabilized before
signaling a buy opportunity.

Sits BETWEEN heartbeat dip detection and the dip-add safety guards:
    detect_spike_or_dip() → ConsolidationDetector → should_add_on_dip() → execute

The key insight: a dip is NOT a buy signal. A dip that CONSOLIDATES is.

Consolidation criteria:
1. Volume declines to <50% of spike volume (selling exhaustion)
2. Price range compresses to <30% of drop range (stabilization)
3. At least N candles hold above the dip low (base forming)
4. No second leg down (price doesn't break below dip low)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("consolidation")


@dataclass
class ConsolidationConfig:
    """Tunable parameters for consolidation detection."""
    volume_decline_ratio: float = 0.5     # Volume must drop to 50% of spike vol
    range_compression_ratio: float = 0.3  # Range must narrow to 30% of drop range
    min_sideways_candles: int = 3          # Need 3+ candles of sideways action
    max_wait_candles: int = 15             # Give up after 15 candles (e.g. 15 min on 1m)
    second_leg_tolerance_pct: float = 0.2  # Abort if price drops 0.2% below dip low

    # Laddered entry configuration
    ladder_tranche_pcts: List[float] = field(
        default_factory=lambda: [0.40, 0.30, 0.30]  # 40/30/30 split
    )
    ladder_step_pct: float = 0.5  # Each tranche 0.5% apart


@dataclass
class Candle:
    """Minimal candle representation for consolidation analysis."""
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: float = 0.0


@dataclass
class ConsolidationResult:
    """Result of consolidation evaluation."""
    action: str      # "BUY_SIGNAL", "ABORT", "TIMEOUT", "WAITING"
    reason: str
    price: float = 0.0
    consolidation_level: float = 0.0
    drop_from_high_pct: float = 0.0
    candles_waited: int = 0
    volume_ratio: float = 0.0
    range_ratio: float = 0.0

    @property
    def should_buy(self) -> bool:
        return self.action == "BUY_SIGNAL"


class ConsolidationDetector:
    """Evaluates whether a detected dip has consolidated enough for an entry.

    Usage:
        detector = ConsolidationDetector(config)

        # Feed candles one at a time as they arrive
        detector.start(dip_low=108.5, dip_high=112.0, spike_volume=50000)

        for candle in incoming_candles:
            result = detector.feed(candle)
            if result.action != "WAITING":
                break  # Got a signal
    """

    def __init__(self, config: Optional[ConsolidationConfig] = None):
        self.config = config or ConsolidationConfig()
        self._dip_low: float = 0.0
        self._dip_high: float = 0.0
        self._drop_range: float = 0.0
        self._spike_volume: float = 0.0
        self._sideways_count: int = 0
        self._total_candles: int = 0
        self._active: bool = False

    def start(self, dip_low: float, dip_high: float, spike_volume: float) -> None:
        """Begin monitoring for consolidation after a dip.

        Args:
            dip_low: The lowest price reached during the dip.
            dip_high: The price before the dip started (recent high).
            spike_volume: The volume during the dip candle(s).
        """
        self._dip_low = dip_low
        self._dip_high = dip_high
        self._drop_range = abs(dip_high - dip_low)
        self._spike_volume = max(spike_volume, 1.0)  # avoid division by zero
        self._sideways_count = 0
        self._total_candles = 0
        self._active = True
        log.info("Consolidation watch started: low=%.2f high=%.2f range=%.2f vol=%.0f",
                 dip_low, dip_high, self._drop_range, spike_volume)

    def feed(self, candle: Candle) -> ConsolidationResult:
        """Feed a new candle and check consolidation status.

        Args:
            candle: The latest candle data.

        Returns:
            ConsolidationResult with the current assessment.
        """
        if not self._active:
            return ConsolidationResult(action="WAITING", reason="Not started")

        self._total_candles += 1

        # ── ABORT: Second leg down ──
        abort_level = self._dip_low * (1 - self.config.second_leg_tolerance_pct / 100)
        if candle.low < abort_level:
            self._active = False
            log.info("Consolidation ABORT: second leg down (%.2f < %.2f)",
                     candle.low, abort_level)
            return ConsolidationResult(
                action="ABORT",
                reason="second_leg_down",
                price=candle.close,
                candles_waited=self._total_candles,
            )

        # ── TIMEOUT: Too many candles ──
        if self._total_candles >= self.config.max_wait_candles:
            self._active = False
            log.info("Consolidation TIMEOUT after %d candles", self._total_candles)
            return ConsolidationResult(
                action="TIMEOUT",
                reason="no_consolidation_in_window",
                candles_waited=self._total_candles,
            )

        # ── CHECK: Volume declining? ──
        vol_ratio = candle.volume / self._spike_volume
        if vol_ratio > self.config.volume_decline_ratio:
            self._sideways_count = 0  # reset — still too much activity
            return ConsolidationResult(
                action="WAITING",
                reason=f"volume_still_high ({vol_ratio:.2f}x)",
                volume_ratio=vol_ratio,
                candles_waited=self._total_candles,
            )

        # ── CHECK: Range compressing? ──
        candle_range = candle.high - candle.low
        range_ratio = candle_range / self._drop_range if self._drop_range > 0 else 0
        if range_ratio > self.config.range_compression_ratio:
            self._sideways_count = 0  # range still too wide
            return ConsolidationResult(
                action="WAITING",
                reason=f"range_still_wide ({range_ratio:.2f}x)",
                range_ratio=range_ratio,
                candles_waited=self._total_candles,
            )

        # ── Both volume and range are quiet → sideways candle ──
        self._sideways_count += 1

        # ── CHECK: Enough sideways candles? ──
        if self._sideways_count >= self.config.min_sideways_candles:
            self._active = False
            drop_pct = (self._drop_range / self._dip_high * 100) if self._dip_high > 0 else 0
            log.info("Consolidation BUY_SIGNAL at %.2f after %d candles (%d sideways)",
                     candle.close, self._total_candles, self._sideways_count)
            return ConsolidationResult(
                action="BUY_SIGNAL",
                reason="consolidation_confirmed",
                price=candle.close,
                consolidation_level=candle.close,
                drop_from_high_pct=drop_pct,
                candles_waited=self._total_candles,
                volume_ratio=vol_ratio,
                range_ratio=range_ratio,
            )

        return ConsolidationResult(
            action="WAITING",
            reason=f"sideways_{self._sideways_count}/{self.config.min_sideways_candles}",
            volume_ratio=vol_ratio,
            range_ratio=range_ratio,
            candles_waited=self._total_candles,
        )

    @property
    def is_active(self) -> bool:
        return self._active

    def reset(self) -> None:
        """Reset the detector for reuse."""
        self._active = False
        self._sideways_count = 0
        self._total_candles = 0


def calculate_ladder_orders(
    consolidation_price: float,
    total_add_size: float,
    config: Optional[ConsolidationConfig] = None,
) -> List[Dict[str, float]]:
    """Calculate laddered limit orders for a dip-buy entry.

    Instead of one market order, splits the add size across descending
    price levels for better average entry.

    Args:
        consolidation_price: The price at consolidation confirmation.
        total_add_size: Total size to add (in contracts/units).
        config: Consolidation config with ladder parameters.

    Returns:
        List of order dicts: [{"price": float, "size": float, "tranche": int}]
    """
    cfg = config or ConsolidationConfig()
    orders = []

    for i, pct in enumerate(cfg.ladder_tranche_pcts):
        step_down = cfg.ladder_step_pct * i / 100  # e.g. 0%, -0.5%, -1.0%
        price = consolidation_price * (1 - step_down)
        size = total_add_size * pct
        orders.append({
            "price": round(price, 6),
            "size": round(size, 6),
            "tranche": i + 1,
        })

    return orders
