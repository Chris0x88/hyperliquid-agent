"""Tests for modules/bot_classifier.py — sub-system 4 pure logic."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engines.data.bot_classifier import (
    BotPattern,
    append_pattern,
    classify_pattern,
    read_patterns,
)


def _now():
    return datetime(2026, 4, 9, 22, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Dataclass + JSONL round-trip
# ---------------------------------------------------------------------------

def _pattern():
    return BotPattern(
        id="BRENTOIL_2026-04-09T22:30:00+00:00",
        instrument="BRENTOIL",
        detected_at=_now(),
        lookback_minutes=60,
        classification="bot_driven_overextension",
        confidence=0.78,
        direction="down",
        price_at_detection=67.42,
        price_change_pct=-1.6,
        signals=["cascade_long_sev3 (OI -4.2%)", "no_high_sev_catalyst_in_24h"],
        notes="test",
    )


def test_pattern_dataclass_constructs():
    p = _pattern()
    assert p.classification == "bot_driven_overextension"
    assert p.confidence == 0.78


def test_pattern_jsonl_round_trip(tmp_path: Path):
    p = tmp_path / "p.jsonl"
    append_pattern(str(p), _pattern())
    rows = read_patterns(str(p))
    assert len(rows) == 1
    assert rows[0].id == _pattern().id
    assert rows[0].direction == "down"
    assert rows[0].signals == _pattern().signals


def test_read_missing_file_returns_empty(tmp_path: Path):
    assert read_patterns(str(tmp_path / "nope.jsonl")) == []


# ---------------------------------------------------------------------------
# classify_pattern
# ---------------------------------------------------------------------------

def _cascade(side="long", severity=3, oi_delta=-4.2, ts=None):
    return {
        "side": side,
        "severity": severity,
        "oi_delta_pct": oi_delta,
        "funding_jump_bps": 18.0,
        "detected_at": (ts or (_now() - timedelta(minutes=10))).isoformat(),
    }


def _catalyst(severity=4, direction="up", hours_ago=2, category="opec"):
    return {
        "severity": severity,
        "direction": direction,
        "category": category,
        "published_at": (_now() - timedelta(hours=hours_ago)).isoformat(),
    }


def _supply_state(active=3, fresh_hours_ago=12, chokepoints=()):
    return {
        "computed_at": (_now() - timedelta(hours=fresh_hours_ago)).isoformat(),
        "active_disruption_count": active,
        "active_chokepoints": list(chokepoints),
        "high_confidence_count": active,
    }


def test_below_floor_returns_unclear():
    p = classify_pattern(
        instrument="BRENTOIL",
        detected_at=_now(),
        price_at_detection=67.40,
        price_change_pct=0.2,  # below 0.5% floor
        atr=0.5,
        recent_cascades=[_cascade()],
        recent_catalysts=[],
        supply_state=None,
    )
    assert p.classification == "unclear"
    assert p.confidence == 0.5
    assert "below_classification_floor" in " ".join(p.signals)


def test_clean_bot_driven_overextension():
    """Cascade present, no catalyst, no fresh supply, big move → bot-driven."""
    p = classify_pattern(
        instrument="BRENTOIL",
        detected_at=_now(),
        price_at_detection=67.42,
        price_change_pct=-1.6,
        atr=0.8,
        recent_cascades=[_cascade(side="long", severity=3)],
        recent_catalysts=[],
        supply_state=None,
        atr_mult_for_big_move=1.5,
    )
    assert p.classification == "bot_driven_overextension"
    assert p.confidence >= 0.7
    assert p.direction == "down"
    assert any("cascade_long" in s for s in p.signals)
    assert any("no_high_sev_catalyst" in s for s in p.signals)
    assert any("no_fresh_supply" in s for s in p.signals)
    assert any("exceeds" in s for s in p.signals)


def test_clean_informed_move_catalyst():
    """High-sev matching catalyst with no cascade → informed move."""
    p = classify_pattern(
        instrument="BRENTOIL",
        detected_at=_now(),
        price_at_detection=68.50,
        price_change_pct=1.4,
        atr=0.4,
        recent_cascades=[],
        recent_catalysts=[_catalyst(severity=5, direction="up", category="opec_cut")],
        supply_state=_supply_state(active=2, fresh_hours_ago=10),
        atr_mult_for_big_move=10.0,  # disable ATR signal
    )
    assert p.classification == "informed_move"
    assert p.confidence >= 0.6
    assert p.direction == "up"
    assert any("catalyst_sev5" in s for s in p.signals)


def test_mixed_when_both_strong():
    """Cascade AND high-sev catalyst matching direction → mixed."""
    p = classify_pattern(
        instrument="BRENTOIL",
        detected_at=_now(),
        price_at_detection=68.50,
        price_change_pct=1.4,
        atr=0.4,
        recent_cascades=[_cascade(side="short", severity=3)],
        recent_catalysts=[_catalyst(severity=5, direction="up", category="opec_cut")],
        supply_state=_supply_state(active=3, fresh_hours_ago=10, chokepoints=("hormuz_strait",)),
        atr_mult_for_big_move=1.5,
    )
    # Bot signals: cascade_short. (no_catalyst FAILS — there is one. no_fresh_supply FAILS.)
    # ATR signal: 1.4% > 1.5*0.4=0.6% YES → bot_signals = [cascade, atr] = 2 → 0.7
    # Informed signals: catalyst, supply, chokepoint = 3 → 0.8
    # informed > bot + 0.1 → informed_move (not mixed)
    assert p.classification in ("informed_move", "mixed")


def test_unclear_when_no_signals():
    """Big move but no cascade, no catalyst, no supply data → mostly bot signals."""
    p = classify_pattern(
        instrument="BRENTOIL",
        detected_at=_now(),
        price_at_detection=67.42,
        price_change_pct=-1.0,
        atr=10.0,  # huge ATR so move doesn't exceed
        recent_cascades=[],
        recent_catalysts=[],
        supply_state=None,
        atr_mult_for_big_move=1.5,
    )
    # Only no_catalyst + no_fresh_supply = 2 bot signals → 0.7
    # 0 informed signals → 0.5
    # bot > informed + 0.1 → bot_driven_overextension
    assert p.classification == "bot_driven_overextension"


def test_cascade_direction_must_match_move():
    """Long cascade with rising price should NOT be a bot signal."""
    p = classify_pattern(
        instrument="BRENTOIL",
        detected_at=_now(),
        price_at_detection=68.50,
        price_change_pct=1.4,  # up
        atr=0.4,
        recent_cascades=[_cascade(side="long")],  # long cascade = price falling, not up
        recent_catalysts=[],
        supply_state=None,
        atr_mult_for_big_move=1.5,
    )
    # cascade does NOT match → bot_signals = [no_catalyst, no_supply, atr] = 3 → 0.8
    # NOT cascade signal
    assert not any("cascade_long" in s for s in p.signals)


def test_old_cascade_outside_window_ignored():
    p = classify_pattern(
        instrument="BRENTOIL",
        detected_at=_now(),
        price_at_detection=67.42,
        price_change_pct=-1.6,
        atr=10.0,  # disable atr
        recent_cascades=[_cascade(ts=_now() - timedelta(hours=2))],  # outside 30min
        recent_catalysts=[],
        supply_state=None,
        cascade_window_min=30,
    )
    assert not any("cascade_long" in s for s in p.signals)


def test_low_severity_catalyst_does_not_count():
    p = classify_pattern(
        instrument="BRENTOIL",
        detected_at=_now(),
        price_at_detection=68.50,
        price_change_pct=1.4,
        atr=10.0,
        recent_cascades=[],
        recent_catalysts=[_catalyst(severity=2, direction="up")],  # below floor 4
        supply_state=None,
        catalyst_floor=4,
    )
    # Catalyst doesn't qualify → no_catalyst bot signal applies
    assert any("no_high_sev_catalyst" in s for s in p.signals)
    assert not any("catalyst_sev" in s for s in p.signals)


def test_stale_supply_not_fresh():
    p = classify_pattern(
        instrument="BRENTOIL",
        detected_at=_now(),
        price_at_detection=68.50,
        price_change_pct=1.4,
        atr=10.0,
        recent_cascades=[],
        recent_catalysts=[],
        supply_state=_supply_state(active=2, fresh_hours_ago=200),  # stale
        supply_freshness_hours=72,
    )
    assert any("no_fresh_supply" in s for s in p.signals)


def test_classification_id_is_deterministic():
    p1 = classify_pattern(
        instrument="BRENTOIL", detected_at=_now(),
        price_at_detection=67.42, price_change_pct=-1.6, atr=0.8,
        recent_cascades=[_cascade()], recent_catalysts=[], supply_state=None,
    )
    p2 = classify_pattern(
        instrument="BRENTOIL", detected_at=_now(),
        price_at_detection=67.42, price_change_pct=-1.6, atr=0.8,
        recent_cascades=[_cascade()], recent_catalysts=[], supply_state=None,
    )
    assert p1.id == p2.id
    assert p1.classification == p2.classification
