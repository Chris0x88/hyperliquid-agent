"""Oil Bot-Pattern Adaptive Position Evaluator — pure logic.

Spec context: Chris, 2026-04-09:

    Intelligence to me is unstructured problem solving and adaptive risk.
    I'd like to encourage the system to evaluate its position live and
    consider adaptation too. That forces it to monitor the market, it
    forces it to test its hypothesis, like how fast moves might occur,
    or patterns rather than just entering a position and reviewing after
    it takes profit or is stopped out.

Sub-system 5 originally only managed open positions via three rules:
  1. 24h hard cap on shorts
  2. Funding-cost exit for longs
  3. Exchange-side SL/TP via exchange_protection

None of those re-test the THESIS that triggered the entry. A bot-pattern
entry is a hypothesis: "this is bot-driven mispricing, the market will
mean-revert to X within Y hours." This module re-tests that hypothesis
on every tick and recommends an adaptation action.

The evaluator is PURE CODE. Zero AI dependency. All thresholds are
configurable. The iterator owns state persistence and action execution.

Adaptation actions (priority order, most-drastic-first):
  - EXIT:           thesis invalidated, close the position
  - SCALE_OUT:      reached target, lock in half
  - TIGHTEN_STOP:   move stop closer to current price
  - TRAIL_BREAKEVEN: move stop to entry (no-risk trade from here)
  - HOLD:           nothing to do

Each adaptation carries a reason string for the Telegram alert + audit
log. Reasons are human-readable and explain WHY the system adapted.

Evaluation inputs:
  - PositionHypothesis — captured at entry (entry price, entry
    classification, entry confidence, expected_reach_price,
    expected_reach_hours)
  - MarketSnapshot — current tick state (current price, latest pattern
    for the instrument, recent catalysts, supply state)
  - AdaptiveConfig — thresholds, all configurable

Engine vs guard: pure computation, zero I/O. The iterator owns
everything stateful.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Action + reason enums
# ---------------------------------------------------------------------------

class AdaptiveAction(str, Enum):
    HOLD = "hold"
    TRAIL_BREAKEVEN = "trail_breakeven"
    TIGHTEN_STOP = "tighten_stop"
    SCALE_OUT = "scale_out"
    EXIT = "exit"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PositionHypothesis:
    """The testable claims made at entry.

    Captured once when the position opens, then compared against
    MarketSnapshot on every subsequent tick.
    """
    instrument: str
    side: str                       # "long" | "short"
    entry_ts: str                   # ISO 8601
    entry_price: float
    expected_reach_price: float     # target the thesis implies
    expected_reach_hours: float     # time horizon for the move
    entry_classification: str       # from sub-system 4 at entry
    entry_confidence: float         # classifier confidence at entry
    entry_pattern_direction: str    # "up"|"down"|"flat" at entry


@dataclass(frozen=True)
class MarketSnapshot:
    """The tick-time view of the market for adaptation checks.

    All fields are optional — the evaluator degrades gracefully. A
    missing latest_pattern means "classifier silent, no drift signal";
    a missing catalysts list means "no catalyst pressure signal"; etc.
    """
    current_price: float
    latest_pattern: dict | None = None      # most recent bot_patterns.jsonl row
    recent_catalysts: list[dict] = field(default_factory=list)
    supply_state: dict | None = None        # data/supply/state.json blob
    now: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


@dataclass(frozen=True)
class AdaptiveConfig:
    """Threshold knobs for the adaptive evaluator.

    All configurable so L2 reflect can propose new values down the road.
    Defaults are conservative — tighten later based on real data.
    """
    # Time-progress thresholds
    stale_time_progress: float = 1.0       # >= this fraction of window elapsed
    stale_price_progress: float = 0.3      # with < this price progress → exit
    # Velocity thresholds
    slow_velocity_ratio: float = 0.25      # actual / required velocity
    slow_velocity_time_floor: float = 0.5  # only act after this much time elapsed
    # Profit-lock thresholds (fraction of move to expected_reach)
    breakeven_at_progress: float = 0.5     # 50% of the move → move stop to entry
    tighten_at_progress: float = 0.8       # 80% of the move → tighten stop
    tighten_buffer_pct: float = 0.5        # stop = current * (1 - buffer) for longs
    scale_out_at_progress: float = 2.0     # DORMANT in v1: SCALE_OUT reduces
                                           # to a full close (same as TP hit).
                                           # When partial closes ship, drop this
                                           # to ~1.0 to lock in half at target.
    # Catalyst pressure
    adverse_catalyst_severity: int = 4     # sev >= this, against-direction
    catalyst_lookback_hours: float = 24.0
    # Classification drift
    drift_exit_classifications: tuple[str, ...] = (
        "informed_flow",                   # the opposite of bot_driven_overextension
    )


@dataclass(frozen=True)
class AdaptiveDecision:
    """One evaluation output. Carries action + reason + numeric context."""
    action: AdaptiveAction
    reason: str
    hours_held: float
    price_progress: float       # 0.0..1.0 for on-track move; can exceed 1.0
    time_progress: float        # 0.0..1.0 for window elapsed; can exceed 1.0
    velocity_ratio: float       # actual / required
    new_stop_price: float | None = None   # only for TIGHTEN_STOP / TRAIL_BREAKEVEN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_price_progress(
    hypothesis: PositionHypothesis,
    current_price: float,
) -> float:
    """Return the fraction of the move from entry toward expected_reach.

    Zero at entry, 1.0 at expected_reach, negative if moving against.
    Can exceed 1.0 when the price passes the target.
    """
    if hypothesis.entry_price <= 0 or hypothesis.expected_reach_price <= 0:
        return 0.0
    denom = hypothesis.expected_reach_price - hypothesis.entry_price
    if denom == 0:
        return 0.0
    actual = current_price - hypothesis.entry_price
    # For shorts the expected_reach is below entry, so denom is negative
    # and actual is negative-on-track; the ratio sign-corrects
    return actual / denom


def compute_time_progress(
    hypothesis: PositionHypothesis,
    now: datetime,
) -> tuple[float, float]:
    """Return (hours_held, time_progress).

    time_progress = hours_held / expected_reach_hours. Can exceed 1.0 if
    the position is held past the window.
    """
    entry_dt = _parse_iso(hypothesis.entry_ts)
    if entry_dt is None:
        return (0.0, 0.0)
    hours_held = max(0.0, (now - entry_dt).total_seconds() / 3600.0)
    if hypothesis.expected_reach_hours <= 0:
        return (hours_held, 0.0)
    return (hours_held, hours_held / hypothesis.expected_reach_hours)


def compute_velocity_ratio(price_progress: float, time_progress: float) -> float:
    """Return actual-velocity / required-velocity as a dimensionless ratio.

    > 1.0 means moving faster than needed to hit target in time.
    < 1.0 means lagging. 0.0 means flat. Negative means adverse.
    If time_progress == 0 return 0 (too early to judge).
    """
    if time_progress <= 0:
        return 0.0
    return price_progress / time_progress


# ---------------------------------------------------------------------------
# Individual evaluators
# ---------------------------------------------------------------------------

def evaluate_classification_drift(
    hypothesis: PositionHypothesis,
    snapshot: MarketSnapshot,
    config: AdaptiveConfig,
) -> tuple[bool, str]:
    """Has the classifier's view of this instrument drifted away from
    the entry thesis?

    Returns (drifted, reason).
    """
    latest = snapshot.latest_pattern
    if latest is None:
        return (False, "no latest classifier output")

    latest_class = str(latest.get("classification", "unclear"))
    latest_dir = str(latest.get("direction", "flat"))

    # Drift 1: direction flipped
    if (
        hypothesis.entry_pattern_direction == "up" and latest_dir == "down"
    ) or (
        hypothesis.entry_pattern_direction == "down" and latest_dir == "up"
    ):
        return (
            True,
            f"classifier direction flipped {hypothesis.entry_pattern_direction}→{latest_dir}",
        )

    # Drift 2: classification moved to a "drift_exit" type
    if (
        hypothesis.entry_classification != latest_class
        and latest_class in config.drift_exit_classifications
    ):
        return (
            True,
            f"classification drifted {hypothesis.entry_classification}→{latest_class}",
        )

    return (False, "classifier still consistent with entry")


def evaluate_adverse_catalyst(
    hypothesis: PositionHypothesis,
    snapshot: MarketSnapshot,
    config: AdaptiveConfig,
) -> tuple[bool, str]:
    """Has a new adverse catalyst appeared since entry?

    For longs: sev>=floor catalyst with direction=down is adverse.
    For shorts: sev>=floor catalyst with direction=up or neutral is adverse.
    """
    cutoff_hours = config.catalyst_lookback_hours
    window_start = snapshot.now - timedelta(hours=cutoff_hours)
    entry_dt = _parse_iso(hypothesis.entry_ts)
    # Only consider catalysts that appeared AFTER entry — pre-entry catalysts
    # were evaluated by the entry gate chain
    effective_start = window_start
    if entry_dt is not None and entry_dt > window_start:
        effective_start = entry_dt

    for cat in snapshot.recent_catalysts:
        try:
            sev = int(cat.get("severity", 0))
        except (TypeError, ValueError):
            continue
        if sev < config.adverse_catalyst_severity:
            continue

        # Timestamp check
        ts_str = cat.get("published_at") or cat.get("scheduled_at") or cat.get("created_at")
        ts = _parse_iso(ts_str) if ts_str else None
        if ts is None or ts < effective_start:
            continue

        cat_dir = str(cat.get("direction") or "").lower()
        category = cat.get("category", "?")

        if hypothesis.side == "long" and cat_dir == "down":
            return (
                True,
                f"adverse catalyst: sev{sev} {category} bearish since entry",
            )
        if hypothesis.side == "short" and cat_dir in ("up", "", "neutral"):
            return (
                True,
                f"adverse catalyst: sev{sev} {category} non-bearish since entry",
            )

    return (False, "no adverse catalyst in window")


def evaluate_staleness(
    hypothesis: PositionHypothesis,
    time_progress: float,
    price_progress: float,
    config: AdaptiveConfig,
) -> tuple[bool, str]:
    """Has the position exceeded its expected window without enough progress?"""
    if time_progress < config.stale_time_progress:
        return (False, "")
    if price_progress >= config.stale_price_progress:
        return (False, "")
    return (
        True,
        f"stale: {time_progress:.1%} of window elapsed, only {price_progress:.1%} progress",
    )


def evaluate_slow_velocity(
    time_progress: float,
    velocity_ratio: float,
    config: AdaptiveConfig,
) -> tuple[bool, str]:
    """Is the move happening too slowly to plausibly complete in time?"""
    if time_progress < config.slow_velocity_time_floor:
        return (False, "")
    if velocity_ratio >= config.slow_velocity_ratio:
        return (False, "")
    return (
        True,
        f"slow: velocity_ratio {velocity_ratio:.2f} < {config.slow_velocity_ratio}",
    )


def compute_breakeven_stop(hypothesis: PositionHypothesis) -> float:
    """Stop-at-entry price. Same for long and short."""
    return hypothesis.entry_price


def compute_tightened_stop(
    hypothesis: PositionHypothesis,
    current_price: float,
    config: AdaptiveConfig,
) -> float:
    """Move stop closer to current price to lock in profit."""
    buf = config.tighten_buffer_pct / 100.0
    if hypothesis.side == "long":
        return current_price * (1.0 - buf)
    if hypothesis.side == "short":
        return current_price * (1.0 + buf)
    return current_price


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def evaluate(
    hypothesis: PositionHypothesis,
    snapshot: MarketSnapshot,
    config: AdaptiveConfig | None = None,
    current_stop_price: float | None = None,
) -> AdaptiveDecision:
    """Top-level adaptive evaluation.

    Applies the rule set in priority order (most drastic first):
      1. Classification drift → EXIT
      2. Adverse catalyst → EXIT
      3. Staleness (time elapsed, little progress) → EXIT
      4. Scale-out (price reached target) → SCALE_OUT
      5. Slow velocity → TIGHTEN_STOP
      6. Price progressed past tighten threshold → TIGHTEN_STOP
      7. Price progressed past breakeven threshold → TRAIL_BREAKEVEN
      8. Otherwise → HOLD

    For TIGHTEN_STOP / TRAIL_BREAKEVEN: `new_stop_price` in the returned
    decision is a SUGGESTION. The iterator decides whether to accept
    it (usually: only if the new stop is better than the current one —
    never loosen).
    """
    cfg = config or AdaptiveConfig()
    price_progress = compute_price_progress(hypothesis, snapshot.current_price)
    hours_held, time_progress = compute_time_progress(hypothesis, snapshot.now)
    velocity_ratio = compute_velocity_ratio(price_progress, time_progress)

    # Rule 1: classification drift
    drifted, drift_reason = evaluate_classification_drift(hypothesis, snapshot, cfg)
    if drifted:
        return AdaptiveDecision(
            action=AdaptiveAction.EXIT,
            reason=drift_reason,
            hours_held=hours_held,
            price_progress=price_progress,
            time_progress=time_progress,
            velocity_ratio=velocity_ratio,
        )

    # Rule 2: adverse catalyst
    adverse, catalyst_reason = evaluate_adverse_catalyst(hypothesis, snapshot, cfg)
    if adverse:
        return AdaptiveDecision(
            action=AdaptiveAction.EXIT,
            reason=catalyst_reason,
            hours_held=hours_held,
            price_progress=price_progress,
            time_progress=time_progress,
            velocity_ratio=velocity_ratio,
        )

    # Rule 3: staleness
    stale, stale_reason = evaluate_staleness(hypothesis, time_progress, price_progress, cfg)
    if stale:
        return AdaptiveDecision(
            action=AdaptiveAction.EXIT,
            reason=stale_reason,
            hours_held=hours_held,
            price_progress=price_progress,
            time_progress=time_progress,
            velocity_ratio=velocity_ratio,
        )

    # Rule 4: scale-out at target
    if price_progress >= cfg.scale_out_at_progress:
        return AdaptiveDecision(
            action=AdaptiveAction.SCALE_OUT,
            reason=f"reached target ({price_progress:.1%} of move)",
            hours_held=hours_held,
            price_progress=price_progress,
            time_progress=time_progress,
            velocity_ratio=velocity_ratio,
        )

    # Rule 5: slow velocity → tighten stop
    slow, slow_reason = evaluate_slow_velocity(time_progress, velocity_ratio, cfg)
    if slow:
        new_stop = compute_tightened_stop(hypothesis, snapshot.current_price, cfg)
        if _is_better_stop(hypothesis.side, current_stop_price, new_stop):
            return AdaptiveDecision(
                action=AdaptiveAction.TIGHTEN_STOP,
                reason=slow_reason,
                hours_held=hours_held,
                price_progress=price_progress,
                time_progress=time_progress,
                velocity_ratio=velocity_ratio,
                new_stop_price=new_stop,
            )

    # Rule 6: progressed past tighten threshold → tighten stop
    if price_progress >= cfg.tighten_at_progress:
        new_stop = compute_tightened_stop(hypothesis, snapshot.current_price, cfg)
        if _is_better_stop(hypothesis.side, current_stop_price, new_stop):
            return AdaptiveDecision(
                action=AdaptiveAction.TIGHTEN_STOP,
                reason=f"progressed past {cfg.tighten_at_progress:.0%} → lock profit",
                hours_held=hours_held,
                price_progress=price_progress,
                time_progress=time_progress,
                velocity_ratio=velocity_ratio,
                new_stop_price=new_stop,
            )

    # Rule 7: progressed past breakeven threshold → trail to entry
    if price_progress >= cfg.breakeven_at_progress:
        new_stop = compute_breakeven_stop(hypothesis)
        if _is_better_stop(hypothesis.side, current_stop_price, new_stop):
            return AdaptiveDecision(
                action=AdaptiveAction.TRAIL_BREAKEVEN,
                reason=f"progressed past {cfg.breakeven_at_progress:.0%} → break-even stop",
                hours_held=hours_held,
                price_progress=price_progress,
                time_progress=time_progress,
                velocity_ratio=velocity_ratio,
                new_stop_price=new_stop,
            )

    # Rule 8: nothing to do
    return AdaptiveDecision(
        action=AdaptiveAction.HOLD,
        reason="hypothesis intact",
        hours_held=hours_held,
        price_progress=price_progress,
        time_progress=time_progress,
        velocity_ratio=velocity_ratio,
    )


def _is_better_stop(side: str, current: float | None, proposed: float) -> bool:
    """Return True iff proposed stop is strictly better (tighter) than current.

    For longs: better = higher (closer to price, less room to lose).
    For shorts: better = lower.
    Missing current is treated as "accept any proposal".
    """
    if current is None or current <= 0:
        return True
    if side == "long":
        return proposed > current
    if side == "short":
        return proposed < current
    return False


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def config_from_dict(d: dict) -> AdaptiveConfig:
    """Build AdaptiveConfig from a config dict (e.g. the adaptive section
    of oil_botpattern.json). Unknown keys are ignored."""
    kwargs: dict[str, Any] = {}
    for field_name in (
        "stale_time_progress", "stale_price_progress",
        "slow_velocity_ratio", "slow_velocity_time_floor",
        "breakeven_at_progress", "tighten_at_progress",
        "tighten_buffer_pct", "scale_out_at_progress",
        "adverse_catalyst_severity", "catalyst_lookback_hours",
    ):
        if field_name in d:
            try:
                kwargs[field_name] = float(d[field_name]) if field_name != "adverse_catalyst_severity" else int(d[field_name])
            except (TypeError, ValueError):
                continue
    if "drift_exit_classifications" in d:
        raw = d["drift_exit_classifications"]
        if isinstance(raw, (list, tuple)):
            kwargs["drift_exit_classifications"] = tuple(str(x) for x in raw)
    return AdaptiveConfig(**kwargs)


def decision_to_dict(d: AdaptiveDecision) -> dict:
    out = asdict(d)
    out["action"] = d.action.value
    return out


# ---------------------------------------------------------------------------
# Training-ready log entries
# ---------------------------------------------------------------------------
#
# Every call to evaluate() produces an AdaptiveDecision. The iterator
# persists those decisions (non-HOLD by default, optionally HOLD heartbeats)
# to data/strategy/oil_botpattern_adaptive_log.jsonl. Each row is flat,
# pre-featurized (derived metrics already computed), and ready to be
# consumed by:
#
#   - retrospective review (did the rule engine do the right thing?)
#   - L1 / L2 harness learning (nudge thresholds based on observed outcomes)
#   - future ML / classifier training (features = position + snapshot,
#     label = action)
#
# Keep the schema append-only and stable. NEVER change the meaning of
# an existing key — add new ones. The whole point is to accumulate
# training data over time.


def hypothesis_to_features(h: PositionHypothesis) -> dict:
    """Flatten a PositionHypothesis into ML-friendly features."""
    return {
        "instrument": h.instrument,
        "side": h.side,
        "entry_ts": h.entry_ts,
        "entry_price": h.entry_price,
        "expected_reach_price": h.expected_reach_price,
        "expected_reach_hours": h.expected_reach_hours,
        "entry_classification": h.entry_classification,
        "entry_confidence": h.entry_confidence,
        "entry_pattern_direction": h.entry_pattern_direction,
    }


def snapshot_to_features(
    snapshot: MarketSnapshot,
    hypothesis_side: str = "long",
) -> dict:
    """Flatten a MarketSnapshot into ML-friendly features.

    Derives:
    - latest_pattern_* fields (or None if classifier silent)
    - recent_catalysts_count
    - max_adverse_severity (filtered to the side's adverse direction)
    - supply_active_disruption_count + supply_age_hours (None if missing)
    """
    latest = snapshot.latest_pattern or {}
    pattern_class = latest.get("classification") if latest else None
    pattern_dir = latest.get("direction") if latest else None
    pattern_conf: float | None = None
    if latest and "confidence" in latest:
        try:
            pattern_conf = float(latest.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            pattern_conf = None

    # Catalyst aggregation — filter to adverse-for-this-side
    max_adverse_severity = 0
    adverse_count = 0
    for cat in snapshot.recent_catalysts or []:
        try:
            sev = int(cat.get("severity", 0) or 0)
        except (TypeError, ValueError):
            continue
        cat_dir = str(cat.get("direction") or "").lower()
        is_adverse = False
        if hypothesis_side == "long" and cat_dir == "down":
            is_adverse = True
        elif hypothesis_side == "short" and cat_dir in ("up", "", "neutral"):
            is_adverse = True
        if is_adverse:
            adverse_count += 1
            if sev > max_adverse_severity:
                max_adverse_severity = sev

    # Supply state
    supply = snapshot.supply_state or {}
    active_disruption_count: int | None = None
    supply_age_hours: float | None = None
    if isinstance(supply, dict) and supply:
        try:
            active_disruption_count = int(supply.get("active_disruption_count", 0) or 0)
        except (TypeError, ValueError):
            active_disruption_count = None
        computed_at = _parse_iso(supply.get("computed_at", ""))
        if computed_at is not None:
            supply_age_hours = (snapshot.now - computed_at).total_seconds() / 3600.0

    return {
        "current_price": snapshot.current_price,
        "latest_pattern_classification": pattern_class,
        "latest_pattern_direction": pattern_dir,
        "latest_pattern_confidence": pattern_conf,
        "recent_catalysts_count": len(snapshot.recent_catalysts or []),
        "adverse_catalysts_count": adverse_count,
        "max_adverse_catalyst_severity": max_adverse_severity,
        "supply_active_disruption_count": active_disruption_count,
        "supply_age_hours": supply_age_hours,
    }


def build_log_entry(
    hypothesis: PositionHypothesis,
    snapshot: MarketSnapshot,
    decision: AdaptiveDecision,
    now: datetime | None = None,
) -> dict:
    """Compose a single JSONL log row combining features + label.

    Stable schema:
    {
      "logged_at": ISO 8601,
      "position": { ...hypothesis_to_features(h)... },
      "snapshot": { ...snapshot_to_features(s)... },
      "decision": { ...decision_to_dict(d)... }
    }

    Mirror this schema verbatim into downstream training pipelines.
    """
    log_ts = (now or snapshot.now or datetime.now(tz=timezone.utc)).isoformat()
    return {
        "logged_at": log_ts,
        "position": hypothesis_to_features(hypothesis),
        "snapshot": snapshot_to_features(snapshot, hypothesis.side),
        "decision": decision_to_dict(decision),
    }


def should_log(
    decision: AdaptiveDecision,
    last_heartbeat_at: datetime | None,
    now: datetime,
    heartbeat_interval_minutes: float = 15.0,
) -> bool:
    """Decide whether to persist a given tick's decision.

    Always log non-HOLD decisions — those are the rare, informative events.
    Log HOLD decisions at most once per `heartbeat_interval_minutes` per
    position — gives temporal coverage without exploding log volume.
    """
    if decision.action != AdaptiveAction.HOLD:
        return True
    if last_heartbeat_at is None:
        return True
    elapsed_minutes = (now - last_heartbeat_at).total_seconds() / 60.0
    return elapsed_minutes >= heartbeat_interval_minutes
