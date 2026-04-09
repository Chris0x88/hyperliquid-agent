"""Tests for modules/oil_botpattern_adaptive.py — live thesis testing pure logic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from modules.oil_botpattern_adaptive import (
    AdaptiveAction,
    AdaptiveConfig,
    AdaptiveDecision,
    MarketSnapshot,
    PositionHypothesis,
    _is_better_stop,
    compute_breakeven_stop,
    compute_price_progress,
    compute_tightened_stop,
    compute_time_progress,
    compute_velocity_ratio,
    config_from_dict,
    decision_to_dict,
    evaluate,
    evaluate_adverse_catalyst,
    evaluate_classification_drift,
    evaluate_slow_velocity,
    evaluate_staleness,
)


UTC = timezone.utc


def _now() -> datetime:
    return datetime(2026, 4, 9, 12, 0, tzinfo=UTC)


def _long_hypo(**overrides) -> PositionHypothesis:
    base = dict(
        instrument="BRENTOIL",
        side="long",
        entry_ts=(_now() - timedelta(hours=4)).isoformat(),
        entry_price=67.00,
        expected_reach_price=70.35,   # +5%
        expected_reach_hours=48.0,
        entry_classification="bot_driven_overextension",
        entry_confidence=0.75,
        entry_pattern_direction="up",
    )
    base.update(overrides)
    return PositionHypothesis(**base)


def _short_hypo(**overrides) -> PositionHypothesis:
    base = dict(
        instrument="BRENTOIL",
        side="short",
        entry_ts=(_now() - timedelta(hours=2)).isoformat(),
        entry_price=70.00,
        expected_reach_price=66.50,   # -5%
        expected_reach_hours=12.0,
        entry_classification="bot_driven_overextension",
        entry_confidence=0.80,
        entry_pattern_direction="down",
    )
    base.update(overrides)
    return PositionHypothesis(**base)


def _snapshot(current_price=68.00, **overrides) -> MarketSnapshot:
    base = dict(
        current_price=current_price,
        latest_pattern=None,
        recent_catalysts=[],
        supply_state=None,
        now=_now(),
    )
    base.update(overrides)
    return MarketSnapshot(**base)


# ---------------------------------------------------------------------------
# compute_price_progress
# ---------------------------------------------------------------------------

def test_price_progress_long_at_entry():
    h = _long_hypo()
    assert compute_price_progress(h, 67.00) == 0.0


def test_price_progress_long_at_target():
    h = _long_hypo()
    assert compute_price_progress(h, 70.35) == pytest.approx(1.0)


def test_price_progress_long_halfway():
    h = _long_hypo()
    # halfway between 67.00 and 70.35 = ~68.675
    assert compute_price_progress(h, 68.675) == pytest.approx(0.5)


def test_price_progress_long_adverse():
    h = _long_hypo()
    # Price dropped below entry → negative progress
    assert compute_price_progress(h, 66.00) < 0


def test_price_progress_short_at_target():
    h = _short_hypo()
    assert compute_price_progress(h, 66.50) == pytest.approx(1.0)


def test_price_progress_short_adverse():
    h = _short_hypo()
    # Price rose above entry on a short → negative
    assert compute_price_progress(h, 71.00) < 0


def test_price_progress_zero_denom_safe():
    h = _long_hypo(expected_reach_price=67.00)
    assert compute_price_progress(h, 68.00) == 0.0


# ---------------------------------------------------------------------------
# compute_time_progress
# ---------------------------------------------------------------------------

def test_time_progress_long_fraction():
    h = _long_hypo()  # entry 4h ago, window 48h → 4/48 ≈ 0.0833
    hours, tp = compute_time_progress(h, _now())
    assert hours == pytest.approx(4.0)
    assert tp == pytest.approx(4 / 48)


def test_time_progress_past_window():
    h = _long_hypo(entry_ts=(_now() - timedelta(hours=60)).isoformat())
    _, tp = compute_time_progress(h, _now())
    assert tp > 1.0


def test_time_progress_bad_entry_ts_zero():
    h = _long_hypo(entry_ts="garbage")
    hours, tp = compute_time_progress(h, _now())
    assert hours == 0.0
    assert tp == 0.0


# ---------------------------------------------------------------------------
# compute_velocity_ratio
# ---------------------------------------------------------------------------

def test_velocity_ratio_on_track():
    # 50% of price move over 50% of time window → 1.0
    assert compute_velocity_ratio(0.5, 0.5) == pytest.approx(1.0)


def test_velocity_ratio_too_slow():
    # 10% move over 50% of time → 0.2
    assert compute_velocity_ratio(0.1, 0.5) == pytest.approx(0.2)


def test_velocity_ratio_too_fast():
    # 80% move over 20% time → 4.0
    assert compute_velocity_ratio(0.8, 0.2) == pytest.approx(4.0)


def test_velocity_ratio_time_zero_safe():
    assert compute_velocity_ratio(0.5, 0.0) == 0.0


# ---------------------------------------------------------------------------
# classification drift
# ---------------------------------------------------------------------------

def test_no_drift_when_classifier_silent():
    h = _long_hypo()
    snap = _snapshot(current_price=68.0, latest_pattern=None)
    drifted, reason = evaluate_classification_drift(h, snap, AdaptiveConfig())
    assert drifted is False


def test_drift_on_direction_flip_long():
    h = _long_hypo()
    snap = _snapshot(latest_pattern={
        "classification": "bot_driven_overextension",
        "direction": "down",
        "confidence": 0.7,
    })
    drifted, reason = evaluate_classification_drift(h, snap, AdaptiveConfig())
    assert drifted is True
    assert "up→down" in reason


def test_drift_on_classification_to_exit_type():
    h = _long_hypo()
    snap = _snapshot(latest_pattern={
        "classification": "informed_flow",  # in drift_exit_classifications
        "direction": "up",
        "confidence": 0.7,
    })
    drifted, _reason = evaluate_classification_drift(h, snap, AdaptiveConfig())
    assert drifted is True


def test_no_drift_when_same_classification():
    h = _long_hypo()
    snap = _snapshot(latest_pattern={
        "classification": "bot_driven_overextension",
        "direction": "up",
        "confidence": 0.75,
    })
    drifted, _reason = evaluate_classification_drift(h, snap, AdaptiveConfig())
    assert drifted is False


# ---------------------------------------------------------------------------
# adverse catalyst
# ---------------------------------------------------------------------------

def test_adverse_catalyst_long_bearish_high_sev():
    h = _long_hypo()
    snap = _snapshot(recent_catalysts=[
        {
            "severity": 5,
            "direction": "down",
            "category": "opec_cut",
            "published_at": (_now() - timedelta(hours=1)).isoformat(),
        },
    ])
    adverse, reason = evaluate_adverse_catalyst(h, snap, AdaptiveConfig())
    assert adverse is True
    assert "sev5" in reason


def test_adverse_catalyst_short_bullish_high_sev():
    h = _short_hypo()
    snap = _snapshot(recent_catalysts=[
        {
            "severity": 4,
            "direction": "up",
            "category": "supply_disruption",
            "published_at": (_now() - timedelta(minutes=30)).isoformat(),
        },
    ])
    adverse, _reason = evaluate_adverse_catalyst(h, snap, AdaptiveConfig())
    assert adverse is True


def test_adverse_catalyst_ignores_pre_entry():
    h = _long_hypo()
    snap = _snapshot(recent_catalysts=[
        {
            "severity": 5,
            "direction": "down",
            "category": "opec_cut",
            "published_at": (_now() - timedelta(hours=10)).isoformat(),  # before entry (4h ago)
        },
    ])
    adverse, _reason = evaluate_adverse_catalyst(h, snap, AdaptiveConfig())
    assert adverse is False


def test_adverse_catalyst_ignores_low_severity():
    h = _long_hypo()
    snap = _snapshot(recent_catalysts=[
        {
            "severity": 2,
            "direction": "down",
            "category": "minor",
            "published_at": (_now() - timedelta(hours=1)).isoformat(),
        },
    ])
    adverse, _reason = evaluate_adverse_catalyst(h, snap, AdaptiveConfig())
    assert adverse is False


def test_adverse_catalyst_ignores_aligned_catalyst():
    h = _long_hypo()
    snap = _snapshot(recent_catalysts=[
        {
            "severity": 5,
            "direction": "up",  # bullish aligned with long → not adverse
            "category": "supply_disruption",
            "published_at": (_now() - timedelta(hours=1)).isoformat(),
        },
    ])
    adverse, _reason = evaluate_adverse_catalyst(h, snap, AdaptiveConfig())
    assert adverse is False


# ---------------------------------------------------------------------------
# staleness
# ---------------------------------------------------------------------------

def test_staleness_fires_on_expired_window():
    stale, reason = evaluate_staleness(_long_hypo(), time_progress=1.2, price_progress=0.1, config=AdaptiveConfig())
    assert stale is True
    assert "stale" in reason


def test_staleness_no_fire_mid_window():
    stale, _reason = evaluate_staleness(_long_hypo(), time_progress=0.5, price_progress=0.1, config=AdaptiveConfig())
    assert stale is False


def test_staleness_no_fire_with_progress():
    stale, _reason = evaluate_staleness(_long_hypo(), time_progress=1.1, price_progress=0.6, config=AdaptiveConfig())
    assert stale is False


# ---------------------------------------------------------------------------
# slow velocity
# ---------------------------------------------------------------------------

def test_slow_velocity_fires_past_time_floor():
    slow, reason = evaluate_slow_velocity(time_progress=0.6, velocity_ratio=0.1, config=AdaptiveConfig())
    assert slow is True


def test_slow_velocity_no_fire_early():
    slow, _reason = evaluate_slow_velocity(time_progress=0.2, velocity_ratio=0.1, config=AdaptiveConfig())
    assert slow is False


def test_slow_velocity_no_fire_on_track():
    slow, _reason = evaluate_slow_velocity(time_progress=0.6, velocity_ratio=1.0, config=AdaptiveConfig())
    assert slow is False


# ---------------------------------------------------------------------------
# stop computations
# ---------------------------------------------------------------------------

def test_breakeven_stop_is_entry():
    h = _long_hypo()
    assert compute_breakeven_stop(h) == 67.00


def test_tightened_stop_long_below_current():
    h = _long_hypo()
    stop = compute_tightened_stop(h, current_price=70.00, config=AdaptiveConfig(tighten_buffer_pct=1.0))
    assert stop == pytest.approx(70.00 * 0.99)


def test_tightened_stop_short_above_current():
    h = _short_hypo()
    stop = compute_tightened_stop(h, current_price=66.00, config=AdaptiveConfig(tighten_buffer_pct=1.0))
    assert stop == pytest.approx(66.00 * 1.01)


def test_is_better_stop_long():
    assert _is_better_stop("long", current=66.0, proposed=67.0) is True
    assert _is_better_stop("long", current=67.0, proposed=66.0) is False


def test_is_better_stop_short():
    assert _is_better_stop("short", current=72.0, proposed=71.0) is True
    assert _is_better_stop("short", current=71.0, proposed=72.0) is False


def test_is_better_stop_missing_current():
    assert _is_better_stop("long", current=None, proposed=50) is True


# ---------------------------------------------------------------------------
# evaluate — end-to-end orchestration
# ---------------------------------------------------------------------------

def test_evaluate_hold_when_nothing_happening():
    h = _long_hypo()
    snap = _snapshot(current_price=67.50)
    d = evaluate(h, snap)
    assert d.action == AdaptiveAction.HOLD


def test_evaluate_exit_on_classification_drift():
    h = _long_hypo()
    snap = _snapshot(latest_pattern={
        "classification": "bot_driven_overextension",
        "direction": "down",
    })
    d = evaluate(h, snap)
    assert d.action == AdaptiveAction.EXIT
    assert "flipped" in d.reason


def test_evaluate_exit_on_adverse_catalyst():
    h = _long_hypo()
    snap = _snapshot(recent_catalysts=[
        {
            "severity": 5,
            "direction": "down",
            "category": "opec_surprise",
            "published_at": (_now() - timedelta(hours=1)).isoformat(),
        },
    ])
    d = evaluate(h, snap)
    assert d.action == AdaptiveAction.EXIT
    assert "catalyst" in d.reason


def test_evaluate_exit_on_staleness():
    # Entry 50h ago, window 48h, still near entry
    h = _long_hypo(entry_ts=(_now() - timedelta(hours=50)).isoformat())
    snap = _snapshot(current_price=67.10)  # basically no progress
    d = evaluate(h, snap)
    assert d.action == AdaptiveAction.EXIT
    assert "stale" in d.reason


def test_evaluate_scale_out_when_configured_low():
    """SCALE_OUT is dormant by default (threshold 2.0) because v1 reduces
    it to a full close — redundant with paper_check_exit's tp_hit. Drop
    the threshold explicitly to exercise the branch."""
    h = _long_hypo()
    snap = _snapshot(current_price=70.35)  # reached target
    d = evaluate(h, snap, config=AdaptiveConfig(scale_out_at_progress=1.0))
    assert d.action == AdaptiveAction.SCALE_OUT


def test_evaluate_scale_out_dormant_by_default():
    """With defaults, reaching target does NOT trigger SCALE_OUT — the
    classical TP hit path handles it via paper_check_exit."""
    h = _long_hypo()
    snap = _snapshot(current_price=70.35)
    d = evaluate(h, snap)  # default config
    # Should fall through to HOLD (or tighten_stop / trail_breakeven
    # depending on current_stop). With no current_stop, trail fires.
    assert d.action in (
        AdaptiveAction.HOLD,
        AdaptiveAction.TRAIL_BREAKEVEN,
        AdaptiveAction.TIGHTEN_STOP,
    )


def test_evaluate_trail_breakeven_at_50pct_progress():
    h = _long_hypo()
    snap = _snapshot(current_price=68.675)  # halfway → 50%
    d = evaluate(h, snap, current_stop_price=65.66)  # current stop below entry
    assert d.action == AdaptiveAction.TRAIL_BREAKEVEN
    assert d.new_stop_price == 67.00  # entry


def test_evaluate_no_trail_when_stop_already_better():
    h = _long_hypo()
    snap = _snapshot(current_price=68.675)
    d = evaluate(h, snap, current_stop_price=67.50)  # already above entry
    # Should fall through to HOLD — trail wouldn't improve
    assert d.action == AdaptiveAction.HOLD


def test_evaluate_tighten_stop_at_80pct_progress():
    h = _long_hypo()
    # 80% of (70.35 - 67.00) = 2.68 → 69.68
    snap = _snapshot(current_price=69.68)
    d = evaluate(h, snap, current_stop_price=67.00)
    assert d.action == AdaptiveAction.TIGHTEN_STOP
    assert d.new_stop_price is not None
    assert d.new_stop_price > 67.00


def test_evaluate_tighten_stop_on_slow_velocity():
    # Entry 30h ago (62% through a 48h window), only 10% progress
    h = _long_hypo(entry_ts=(_now() - timedelta(hours=30)).isoformat())
    # 10% of move = 67.335
    snap = _snapshot(current_price=67.335)
    d = evaluate(h, snap, current_stop_price=65.66)
    assert d.action == AdaptiveAction.TIGHTEN_STOP
    assert "slow" in d.reason


def test_evaluate_exit_takes_priority_over_scale_out():
    h = _long_hypo()
    # At target, BUT classifier drifted
    snap = _snapshot(
        current_price=70.35,
        latest_pattern={"classification": "bot_driven_overextension", "direction": "down"},
    )
    d = evaluate(h, snap)
    assert d.action == AdaptiveAction.EXIT  # drift wins


def test_evaluate_short_position_breakeven():
    h = _short_hypo()
    # Halfway: 70.00 - (70.00 - 66.50) * 0.5 = 68.25
    snap = _snapshot(current_price=68.25)
    d = evaluate(h, snap, current_stop_price=71.40)
    assert d.action == AdaptiveAction.TRAIL_BREAKEVEN
    assert d.new_stop_price == 70.00  # entry


# ---------------------------------------------------------------------------
# Config loading + serialization
# ---------------------------------------------------------------------------

def test_config_from_dict_parses_all_fields():
    d = {
        "stale_time_progress": 0.9,
        "stale_price_progress": 0.2,
        "slow_velocity_ratio": 0.3,
        "slow_velocity_time_floor": 0.6,
        "breakeven_at_progress": 0.4,
        "tighten_at_progress": 0.7,
        "tighten_buffer_pct": 1.0,
        "scale_out_at_progress": 0.95,
        "adverse_catalyst_severity": 5,
        "catalyst_lookback_hours": 48.0,
        "drift_exit_classifications": ["informed_flow", "unclear"],
    }
    cfg = config_from_dict(d)
    assert cfg.stale_time_progress == 0.9
    assert cfg.adverse_catalyst_severity == 5
    assert cfg.tighten_buffer_pct == 1.0
    assert cfg.drift_exit_classifications == ("informed_flow", "unclear")


def test_config_from_empty_dict_returns_defaults():
    cfg = config_from_dict({})
    assert cfg.stale_time_progress == 1.0  # default
    assert cfg.drift_exit_classifications == ("informed_flow",)


def test_decision_to_dict_serializable():
    d = AdaptiveDecision(
        action=AdaptiveAction.TIGHTEN_STOP,
        reason="test",
        hours_held=5.0,
        price_progress=0.7,
        time_progress=0.6,
        velocity_ratio=1.17,
        new_stop_price=68.50,
    )
    out = decision_to_dict(d)
    assert out["action"] == "tighten_stop"
    assert out["new_stop_price"] == 68.50
    assert out["reason"] == "test"


# ---------------------------------------------------------------------------
# Training-ready log entries
# ---------------------------------------------------------------------------

def test_hypothesis_to_features_flattens():
    h = _long_hypo()
    feats = None
    from modules.oil_botpattern_adaptive import hypothesis_to_features
    feats = hypothesis_to_features(h)
    assert feats["instrument"] == "BRENTOIL"
    assert feats["side"] == "long"
    assert feats["entry_price"] == 67.00
    assert feats["entry_classification"] == "bot_driven_overextension"
    assert feats["entry_confidence"] == 0.75


def test_snapshot_to_features_with_pattern():
    from modules.oil_botpattern_adaptive import snapshot_to_features
    snap = _snapshot(latest_pattern={
        "classification": "bot_driven_overextension",
        "direction": "up",
        "confidence": 0.72,
    })
    feats = snapshot_to_features(snap, hypothesis_side="long")
    assert feats["latest_pattern_classification"] == "bot_driven_overextension"
    assert feats["latest_pattern_direction"] == "up"
    assert feats["latest_pattern_confidence"] == 0.72
    assert feats["recent_catalysts_count"] == 0
    assert feats["adverse_catalysts_count"] == 0


def test_snapshot_to_features_catalyst_adverse_filter():
    from modules.oil_botpattern_adaptive import snapshot_to_features
    snap = _snapshot(recent_catalysts=[
        {"severity": 5, "direction": "down"},     # adverse for long
        {"severity": 3, "direction": "up"},        # supportive for long
        {"severity": 4, "direction": "down"},     # adverse for long
    ])
    feats_long = snapshot_to_features(snap, hypothesis_side="long")
    assert feats_long["recent_catalysts_count"] == 3
    assert feats_long["adverse_catalysts_count"] == 2
    assert feats_long["max_adverse_catalyst_severity"] == 5

    feats_short = snapshot_to_features(snap, hypothesis_side="short")
    assert feats_short["adverse_catalysts_count"] == 1  # only the "up" one
    assert feats_short["max_adverse_catalyst_severity"] == 3


def test_snapshot_to_features_supply_state():
    from modules.oil_botpattern_adaptive import snapshot_to_features
    snap = _snapshot(supply_state={
        "active_disruption_count": 4,
        "computed_at": (_now() - timedelta(hours=6)).isoformat(),
    })
    feats = snapshot_to_features(snap, hypothesis_side="long")
    assert feats["supply_active_disruption_count"] == 4
    assert feats["supply_age_hours"] == pytest.approx(6.0)


def test_snapshot_to_features_missing_supply_state():
    from modules.oil_botpattern_adaptive import snapshot_to_features
    feats = snapshot_to_features(_snapshot(supply_state=None))
    assert feats["supply_active_disruption_count"] is None
    assert feats["supply_age_hours"] is None


def test_build_log_entry_full_row():
    from modules.oil_botpattern_adaptive import build_log_entry
    h = _long_hypo()
    snap = _snapshot(current_price=68.675, latest_pattern={
        "classification": "bot_driven_overextension",
        "direction": "up",
        "confidence": 0.80,
    })
    d = evaluate(h, snap, current_stop_price=65.66)
    entry = build_log_entry(h, snap, d)
    assert "logged_at" in entry
    assert entry["position"]["instrument"] == "BRENTOIL"
    assert entry["snapshot"]["current_price"] == 68.675
    assert entry["snapshot"]["latest_pattern_confidence"] == 0.80
    assert entry["decision"]["action"] == "trail_breakeven"
    assert "reason" in entry["decision"]
    # derived metrics present
    assert "price_progress" in entry["decision"]
    assert "time_progress" in entry["decision"]
    assert "velocity_ratio" in entry["decision"]


def test_should_log_non_hold_always():
    from modules.oil_botpattern_adaptive import should_log
    d = AdaptiveDecision(
        action=AdaptiveAction.EXIT, reason="x",
        hours_held=1.0, price_progress=0.5, time_progress=0.5, velocity_ratio=1.0,
    )
    assert should_log(d, last_heartbeat_at=_now(), now=_now()) is True


def test_should_log_hold_first_time():
    from modules.oil_botpattern_adaptive import should_log
    d = AdaptiveDecision(
        action=AdaptiveAction.HOLD, reason="x",
        hours_held=1.0, price_progress=0.1, time_progress=0.1, velocity_ratio=1.0,
    )
    assert should_log(d, last_heartbeat_at=None, now=_now()) is True


def test_should_log_hold_throttled():
    from modules.oil_botpattern_adaptive import should_log
    d = AdaptiveDecision(
        action=AdaptiveAction.HOLD, reason="x",
        hours_held=1.0, price_progress=0.1, time_progress=0.1, velocity_ratio=1.0,
    )
    # Last heartbeat 2 min ago, 15 min interval → skip
    assert should_log(
        d,
        last_heartbeat_at=_now() - timedelta(minutes=2),
        now=_now(),
        heartbeat_interval_minutes=15.0,
    ) is False


def test_should_log_hold_past_interval():
    from modules.oil_botpattern_adaptive import should_log
    d = AdaptiveDecision(
        action=AdaptiveAction.HOLD, reason="x",
        hours_held=1.0, price_progress=0.1, time_progress=0.1, velocity_ratio=1.0,
    )
    assert should_log(
        d,
        last_heartbeat_at=_now() - timedelta(minutes=30),
        now=_now(),
        heartbeat_interval_minutes=15.0,
    ) is True
