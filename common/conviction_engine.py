"""Conviction Engine — pure functions for thesis-driven position sizing and execution.

All functions are pure (no I/O, no side effects) and independently testable.
The heartbeat calls these to modulate trade sizing based on ThesisState conviction.

Kill switch: ``HeartbeatConfig.conviction_bands.enabled = False`` disables all
conviction-driven execution, reverting to Phase 1 middle-office only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from common.heartbeat_config import ConvictionBands


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Conviction → target position size
# ═══════════════════════════════════════════════════════════════════════════════

def conviction_to_target_pct(conviction: float, bands: ConvictionBands) -> float:
    """Map conviction (0.0-1.0) to target position size as fraction of equity.

    Returns 0.0 for conviction below the defensive threshold.
    Linearly interpolates within each band.

    >>> from common.heartbeat_config import ConvictionBands
    >>> bands = ConvictionBands()
    >>> conviction_to_target_pct(0.2, bands)
    0.0
    >>> 0.05 <= conviction_to_target_pct(0.4, bands) <= 0.10
    True
    """
    if conviction < bands.defensive_max:
        return 0.0

    # Walk through bands in order
    for (lo_c, hi_c), (lo_s, hi_s) in [
        (bands.small_range, bands.small_size),
        (bands.medium_range, bands.medium_size),
        (bands.large_range, bands.large_size),
        (bands.max_range, bands.max_size),
    ]:
        if lo_c <= conviction <= hi_c:
            # Linear interpolation
            t = (conviction - lo_c) / max(hi_c - lo_c, 1e-9)
            return lo_s + t * (hi_s - lo_s)

    # Above max range — return top of max band
    if conviction > bands.max_range[1]:
        return bands.max_size[1]

    return 0.0


def compute_target_notional(
    conviction: float,
    equity: float,
    bands: ConvictionBands,
) -> float:
    """Target notional = equity * conviction_to_target_pct(conviction, bands)."""
    return equity * conviction_to_target_pct(conviction, bands)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Conviction modulation of execution parameters
# ═══════════════════════════════════════════════════════════════════════════════

def modulate_dip_add_pct(base_pct: float, conviction: float) -> float:
    """Scale dip-add size by conviction.

    At conviction 0.5: 50% of base.  At 0.95: 95% of base.
    Below 0.3: returns 0 (no adds in defensive mode).
    """
    if conviction < 0.3:
        return 0.0
    return base_pct * min(conviction, 1.0)


def modulate_spike_take_pct(base_pct: float, conviction: float) -> float:
    """Scale spike profit-take by conviction. Lower conviction = take more.

    At conviction 0.3: 2x base (take aggressively — low confidence, bank profits).
    At conviction 0.9+: 0.5x base (let it run — high confidence).
    Linear interpolation between.
    """
    if conviction <= 0.3:
        return base_pct * 2.0
    if conviction >= 0.9:
        return base_pct * 0.5

    # Linear: 2.0 at 0.3 → 0.5 at 0.9
    t = (conviction - 0.3) / 0.6
    multiplier = 2.0 - t * 1.5  # 2.0 → 0.5
    return base_pct * multiplier


# ═══════════════════════════════════════════════════════════════════════════════
# 3. BRENTOIL roll awareness
# ═══════════════════════════════════════════════════════════════════════════════

def is_near_roll_window(dt: datetime | None = None) -> bool:
    """True if current date is near the monthly BRENTOIL roll window.

    HL BRENTOIL perp rolls between the 5th-10th business day of each month.
    We buffer 2 business days on each side: 3rd-12th business day.

    During this window: halve dip-add aggressiveness, tighten take-profit.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    # Count business days from 1st of month to current date
    bday_count = 0
    day = dt.replace(day=1)
    while day.day <= dt.day:
        if day.weekday() < 5:  # Mon-Fri
            bday_count += 1
        if day.day == dt.day:
            break
        day = day.replace(day=day.day + 1)

    return 3 <= bday_count <= 12


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Safety guards
# ═══════════════════════════════════════════════════════════════════════════════

def check_oil_direction_guard(direction: str) -> bool:
    """HARDCODED: oil is LONG or NEUTRAL only. Never short.

    This is NOT configurable. It reflects a core portfolio rule.
    """
    return direction.lower() in ("long", "flat", "neutral", "")


def can_execute_add(
    thesis_exists: bool,
    effective_conv: float,
    escalation: str,
    is_oil: bool,
    thesis_direction: str,
    is_vault_no_tactical: bool,
    total_notional: float,
    add_notional: float,
    equity: float,
    max_notional_pct: float,
) -> tuple[bool, str]:
    """Check all 6 safeguards for dip-add execution.

    Returns (can_add, block_reason). If can_add is True, block_reason is empty.
    """
    if not thesis_exists:
        return False, "no thesis file"
    if effective_conv <= 0.5:
        return False, f"conviction {effective_conv:.2f} <= 0.5"
    if escalation in ("L2", "L3"):
        return False, f"escalation {escalation}"
    if is_oil and not check_oil_direction_guard(thesis_direction):
        return False, "oil long-only violated"
    if is_vault_no_tactical:
        return False, "vault tactical trades disabled"
    if equity > 0 and (total_notional + add_notional) > equity * max_notional_pct:
        return False, "would exceed max notional cap"
    return True, ""
