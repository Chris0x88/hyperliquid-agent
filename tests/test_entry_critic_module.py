"""Tests for modules/entry_critic.py — pure-logic signal stack, grading, and
formatting for the Trade Entry Critic.

The critic is deterministic — no LLM, no AI, no stochasticity. These tests
drive the gather/grade/format functions with fixture dicts so they exercise
every axis in isolation + the end-to-end path with all inputs present.

Covers:
- _coin_matches / _coin_variants (xyz: prefix normalization bug)
- gather_signal_stack with every input present
- gather_signal_stack with every input missing (degraded mode)
- per-axis grading rules with edge cases
- overall summary counting
- format_critique_telegram / format_critique_jsonl produce valid output
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from engines.protection.entry_critic import (
    CATALYST_LATE,
    CATALYST_LEAD,
    CATALYST_NEUTRAL,
    DIRECTION_ALIGNED,
    DIRECTION_NO_THESIS,
    DIRECTION_OPPOSED,
    FUNDING_CHEAP,
    FUNDING_EXPENSIVE,
    FUNDING_FAIR,
    FUNDING_UNKNOWN,
    LIQUIDITY_CASCADE_RISK,
    LIQUIDITY_SAFE,
    LIQUIDITY_UNKNOWN,
    SIZING_GREAT,
    SIZING_OK,
    SIZING_OVERWEIGHT,
    SIZING_UNDERWEIGHT,
    SIZING_UNKNOWN,
    EntryGrade,
    SignalStack,
    _coin_matches,
    _coin_variants,
    format_critique_jsonl,
    format_critique_telegram,
    gather_signal_stack,
    grade_entry,
)


# ───────────────────────────────────────────────────────────
# Coin normalization helpers
# ───────────────────────────────────────────────────────────


class TestCoinMatching:
    def test_exact_match(self):
        assert _coin_matches("BTC", "BTC") is True

    def test_xyz_prefix_on_one_side(self):
        assert _coin_matches("xyz:BRENTOIL", "BRENTOIL") is True
        assert _coin_matches("BRENTOIL", "xyz:BRENTOIL") is True

    def test_mismatch(self):
        assert _coin_matches("BTC", "ETH") is False

    def test_empty_or_none(self):
        assert _coin_matches("", "BTC") is False
        assert _coin_matches("BTC", "") is False

    def test_variants_adds_both_forms(self):
        assert _coin_variants("BRENTOIL") == {"BRENTOIL", "xyz:BRENTOIL"}
        assert _coin_variants("xyz:BRENTOIL") == {"BRENTOIL", "xyz:BRENTOIL"}

    def test_variants_empty(self):
        assert _coin_variants("") == set()


# ───────────────────────────────────────────────────────────
# gather_signal_stack — degraded paths (missing inputs)
# ───────────────────────────────────────────────────────────


@pytest.fixture
def workdir(tmp_path):
    """Hermetic workdir with empty paths by default."""
    return {
        "tmp": tmp_path,
        "zones": tmp_path / "heatmap" / "zones.jsonl",
        "cascades": tmp_path / "heatmap" / "cascades.jsonl",
        "catalysts": tmp_path / "news" / "catalysts.jsonl",
        "bot_patterns": tmp_path / "research" / "bot_patterns.jsonl",
    }


def _position(**overrides) -> dict:
    base = {
        "instrument": "xyz:BRENTOIL",
        "direction": "long",
        "entry_price": 89.5,
        "entry_qty": 10.0,
        "entry_ts_ms": 1_712_640_000_000,
        "leverage": 5.0,
        "notional_usd": 895.0,
        "equity_usd": 10_000.0,
    }
    base.update(overrides)
    return base


def _stub_lessons(*rows):
    def fn(**kwargs):
        return list(rows)
    return fn


class TestGatherMissingInputs:
    def test_all_missing_returns_stack_with_degraded_flags(self, workdir):
        stack = gather_signal_stack(
            _position(),
            ctx=None,
            zones_path=str(workdir["zones"]),
            cascades_path=str(workdir["cascades"]),
            catalysts_path=str(workdir["catalysts"]),
            bot_patterns_path=str(workdir["bot_patterns"]),
            search_lessons_fn=_stub_lessons(),
        )
        assert stack.instrument == "xyz:BRENTOIL"
        assert stack.direction == "long"
        assert stack.entry_price == 89.5
        assert stack.actual_size_pct == pytest.approx(0.0895)
        assert stack.thesis_direction is None
        assert stack.upcoming_catalysts == []
        assert stack.nearest_wall_bps is None
        assert stack.recent_cascade_against is None
        assert stack.bot_pattern is None
        assert stack.lessons == []
        # Degraded flags should explain WHY each axis is missing
        assert "catalysts" in stack.degraded

    def test_no_ctx_no_thesis(self, workdir):
        stack = gather_signal_stack(
            _position(),
            ctx=None,
            zones_path=str(workdir["zones"]),
            cascades_path=str(workdir["cascades"]),
            catalysts_path=str(workdir["catalysts"]),
            bot_patterns_path=str(workdir["bot_patterns"]),
            search_lessons_fn=_stub_lessons(),
        )
        assert stack.thesis_conviction is None
        assert stack.thesis_target_size_pct is None

    def test_garbage_position_does_not_raise(self, workdir):
        """Corrupt position dict must not take down gather."""
        stack = gather_signal_stack(
            {"instrument": "BTC", "direction": "long", "entry_price": "nope", "entry_qty": None},
            ctx=None,
            zones_path=str(workdir["zones"]),
            cascades_path=str(workdir["cascades"]),
            catalysts_path=str(workdir["catalysts"]),
            bot_patterns_path=str(workdir["bot_patterns"]),
            search_lessons_fn=_stub_lessons(),
        )
        assert stack.entry_price == 0.0
        assert stack.entry_qty == 0.0


# ───────────────────────────────────────────────────────────
# gather_signal_stack — inputs present
# ───────────────────────────────────────────────────────────


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


@dataclass
class _FakeTrend:
    rsi: float = 55.0
    rsi_divergence: str = "none"


@dataclass
class _FakeTF:
    atr_value: float = 1.5
    atr_pct: float = 1.8
    trend: _FakeTrend = None

    def __post_init__(self):
        if self.trend is None:
            self.trend = _FakeTrend()


@dataclass
class _FakeSnap:
    timeframes: dict = None
    flags: list = None
    suggested_stop: float = 87.5
    suggested_tp: float = 95.0
    suggested_short_stop: float = 92.0
    suggested_short_tp: float = 84.0

    def __post_init__(self):
        if self.timeframes is None:
            self.timeframes = {"4h": _FakeTF()}
        if self.flags is None:
            self.flags = ["bb_squeeze_4h"]


@dataclass
class _FakeThesis:
    direction: str = "long"
    conviction: float = 0.55
    recommended_size_pct: float = 0.09
    take_profit_price: float = 98.0


class _FakeCtx:
    def __init__(self, thesis_states=None, market_snapshots=None, total_equity=10_000.0):
        self.thesis_states = thesis_states or {}
        self.market_snapshots = market_snapshots or {}
        self.total_equity = total_equity


class TestGatherWithInputs:
    def test_thesis_from_ctx_aligned(self, workdir):
        ctx = _FakeCtx(thesis_states={"xyz:BRENTOIL": _FakeThesis()})
        stack = gather_signal_stack(
            _position(),
            ctx=ctx,
            zones_path=str(workdir["zones"]),
            cascades_path=str(workdir["cascades"]),
            catalysts_path=str(workdir["catalysts"]),
            bot_patterns_path=str(workdir["bot_patterns"]),
            search_lessons_fn=_stub_lessons(),
        )
        assert stack.thesis_direction == "long"
        assert stack.thesis_conviction == 0.55
        assert stack.thesis_target_size_pct == 0.09
        assert stack.thesis_take_profit == 98.0

    def test_thesis_coin_prefix_match(self, workdir):
        """Thesis key with xyz: prefix must match instrument 'BRENTOIL'."""
        ctx = _FakeCtx(thesis_states={"xyz:BRENTOIL": _FakeThesis(direction="long", conviction=0.7)})
        stack = gather_signal_stack(
            _position(instrument="BRENTOIL"),
            ctx=ctx,
            zones_path=str(workdir["zones"]),
            cascades_path=str(workdir["cascades"]),
            catalysts_path=str(workdir["catalysts"]),
            bot_patterns_path=str(workdir["bot_patterns"]),
            search_lessons_fn=_stub_lessons(),
        )
        assert stack.thesis_conviction == 0.7

    def test_market_snapshot_from_ctx(self, workdir):
        ctx = _FakeCtx(market_snapshots={"xyz:BRENTOIL": _FakeSnap()})
        stack = gather_signal_stack(
            _position(),
            ctx=ctx,
            zones_path=str(workdir["zones"]),
            cascades_path=str(workdir["cascades"]),
            catalysts_path=str(workdir["catalysts"]),
            bot_patterns_path=str(workdir["bot_patterns"]),
            search_lessons_fn=_stub_lessons(),
        )
        assert stack.atr_value == 1.5
        assert stack.atr_pct == 1.8
        assert stack.rsi == 55.0
        assert "bb_squeeze_4h" in stack.snapshot_flags
        assert stack.suggested_stop == 87.5
        assert stack.suggested_tp == 95.0

    def test_catalyst_window_filters_instrument_and_time(self, workdir):
        now_ms = 1_712_640_000_000
        _write_jsonl(workdir["catalysts"], [
            # Match: sev 4, 10h ahead
            {"id": "c1", "instruments": ["xyz:BRENTOIL"],
             "event_date": "2024-04-09T10:00:00+00:00",
             "category": "OPEC_meeting", "severity": 4,
             "expected_direction": "up", "rationale": "test"},
            # Wrong instrument
            {"id": "c2", "instruments": ["BTC"],
             "event_date": "2024-04-09T05:00:00+00:00",
             "category": "FOMC", "severity": 4,
             "expected_direction": "down", "rationale": "test"},
            # Past event (should be dropped)
            {"id": "c3", "instruments": ["BRENTOIL"],
             "event_date": "2020-01-01T00:00:00+00:00",
             "category": "old", "severity": 4,
             "expected_direction": "up", "rationale": "test"},
        ])

        stack = gather_signal_stack(
            _position(entry_ts_ms=now_ms),
            ctx=None,
            zones_path=str(workdir["zones"]),
            cascades_path=str(workdir["cascades"]),
            catalysts_path=str(workdir["catalysts"]),
            bot_patterns_path=str(workdir["bot_patterns"]),
            search_lessons_fn=_stub_lessons(),
            now_ms=now_ms,
        )
        assert len(stack.upcoming_catalysts) == 1
        assert stack.upcoming_catalysts[0]["id"] == "c1"

    def test_heatmap_nearest_wall(self, workdir):
        _write_jsonl(workdir["zones"], [
            {"id": "z1", "instrument": "xyz:BRENTOIL",
             "snapshot_at": "2024-04-09T00:00:00+00:00", "mid": 89.5,
             "side": "ask", "price_low": 90.0, "price_high": 90.5,
             "centroid": 90.2, "distance_bps": 78.0,
             "notional_usd": 1_000_000, "level_count": 3, "rank": 1},
            {"id": "z2", "instrument": "xyz:BRENTOIL",
             "snapshot_at": "2024-04-09T00:00:00+00:00", "mid": 89.5,
             "side": "ask", "price_low": 91.0, "price_high": 91.5,
             "centroid": 91.2, "distance_bps": 190.0,
             "notional_usd": 500_000, "level_count": 2, "rank": 2},
            {"id": "z3", "instrument": "xyz:BRENTOIL",
             "snapshot_at": "2024-04-09T00:00:00+00:00", "mid": 89.5,
             "side": "bid", "price_low": 88.8, "price_high": 89.0,
             "centroid": 88.9, "distance_bps": -67.0,
             "notional_usd": 800_000, "level_count": 3, "rank": 1},
        ])
        stack = gather_signal_stack(
            _position(),  # long → care about ask walls
            ctx=None,
            zones_path=str(workdir["zones"]),
            cascades_path=str(workdir["cascades"]),
            catalysts_path=str(workdir["catalysts"]),
            bot_patterns_path=str(workdir["bot_patterns"]),
            search_lessons_fn=_stub_lessons(),
        )
        assert stack.nearest_wall_side == "ask"
        assert stack.nearest_wall_bps == 78.0
        assert stack.nearest_wall_notional == 1_000_000

    def test_cascade_against_direction(self, workdir):
        now_ms = 1_712_640_000_000
        # Within window (30 min ago)
        _write_jsonl(workdir["cascades"], [
            {"id": "cas1", "instrument": "xyz:BRENTOIL",
             "detected_at": "2024-04-09T03:30:00+00:00",  # ~30 min before entry
             "window_s": 180, "side": "long",
             "oi_delta_pct": -2.5, "funding_jump_bps": 15.0,
             "severity": 3, "notes": "test"},
        ])
        stack = gather_signal_stack(
            _position(entry_ts_ms=now_ms),  # direction=long, cascade.side=long → MATCH
            ctx=None,
            zones_path=str(workdir["zones"]),
            cascades_path=str(workdir["cascades"]),
            catalysts_path=str(workdir["catalysts"]),
            bot_patterns_path=str(workdir["bot_patterns"]),
            search_lessons_fn=_stub_lessons(),
            now_ms=now_ms,
        )
        assert stack.recent_cascade_against is not None
        assert stack.recent_cascade_against["id"] == "cas1"

    def test_bot_pattern_latest(self, workdir):
        _write_jsonl(workdir["bot_patterns"], [
            {"id": "bp1", "instrument": "xyz:BRENTOIL",
             "detected_at": "2024-04-08T00:00:00+00:00",
             "lookback_minutes": 30, "classification": "informed_move",
             "confidence": 0.7, "direction": "up",
             "price_at_detection": 88.0, "price_change_pct": 1.2,
             "signals": [], "notes": ""},
            {"id": "bp2", "instrument": "xyz:BRENTOIL",
             "detected_at": "2024-04-09T00:00:00+00:00",
             "lookback_minutes": 30, "classification": "bot_driven_overextension",
             "confidence": 0.8, "direction": "up",
             "price_at_detection": 89.5, "price_change_pct": 2.0,
             "signals": [], "notes": ""},
        ])
        stack = gather_signal_stack(
            _position(),
            ctx=None,
            zones_path=str(workdir["zones"]),
            cascades_path=str(workdir["cascades"]),
            catalysts_path=str(workdir["catalysts"]),
            bot_patterns_path=str(workdir["bot_patterns"]),
            search_lessons_fn=_stub_lessons(),
        )
        assert stack.bot_pattern is not None
        assert stack.bot_pattern["id"] == "bp2"
        assert stack.bot_pattern["classification"] == "bot_driven_overextension"

    def test_lessons_passed_through(self, workdir):
        stack = gather_signal_stack(
            _position(),
            ctx=None,
            zones_path=str(workdir["zones"]),
            cascades_path=str(workdir["cascades"]),
            catalysts_path=str(workdir["catalysts"]),
            bot_patterns_path=str(workdir["bot_patterns"]),
            search_lessons_fn=_stub_lessons(
                {"id": 42, "summary": "BRENTOIL longs in low funding work well"},
                {"id": 98, "summary": "avoid scaling in within 6h of FOMC"},
            ),
        )
        assert len(stack.lessons) == 2
        assert stack.lessons[0]["id"] == 42

    def test_lessons_fn_raises_is_graceful(self, workdir):
        def bad_fn(**kwargs):
            raise RuntimeError("boom")
        stack = gather_signal_stack(
            _position(),
            ctx=None,
            zones_path=str(workdir["zones"]),
            cascades_path=str(workdir["cascades"]),
            catalysts_path=str(workdir["catalysts"]),
            bot_patterns_path=str(workdir["bot_patterns"]),
            search_lessons_fn=bad_fn,
        )
        assert stack.lessons == []
        assert "lessons" in stack.degraded

    def test_liquidation_cushion_from_position(self, workdir):
        stack = gather_signal_stack(
            _position(
                liquidation_price=85.0,
                mark_price=89.5,
            ),
            ctx=None,
            zones_path=str(workdir["zones"]),
            cascades_path=str(workdir["cascades"]),
            catalysts_path=str(workdir["catalysts"]),
            bot_patterns_path=str(workdir["bot_patterns"]),
            search_lessons_fn=_stub_lessons(),
        )
        assert stack.liquidation_cushion_pct is not None
        assert stack.liquidation_cushion_pct == pytest.approx((89.5 - 85.0) / 89.5)


# ───────────────────────────────────────────────────────────
# Grading rules
# ───────────────────────────────────────────────────────────


def _stack(**overrides) -> SignalStack:
    base = dict(
        instrument="xyz:BRENTOIL",
        direction="long",
        entry_price=89.5,
        entry_qty=10.0,
        entry_ts_ms=1_712_640_000_000,
    )
    base.update(overrides)
    return SignalStack(**base)


class TestGradingSizing:
    def test_unknown_when_no_target(self):
        s = _stack(actual_size_pct=0.1, thesis_target_size_pct=None)
        g = grade_entry(s)
        assert g.sizing == SIZING_UNKNOWN

    def test_great_within_10pct(self):
        s = _stack(actual_size_pct=0.105, thesis_target_size_pct=0.10)
        g = grade_entry(s)
        assert g.sizing == SIZING_GREAT

    def test_ok_between_10_and_30(self):
        s = _stack(actual_size_pct=0.12, thesis_target_size_pct=0.10)
        g = grade_entry(s)
        assert g.sizing == SIZING_OK

    def test_overweight(self):
        s = _stack(actual_size_pct=0.20, thesis_target_size_pct=0.10)
        g = grade_entry(s)
        assert g.sizing == SIZING_OVERWEIGHT

    def test_underweight(self):
        s = _stack(actual_size_pct=0.05, thesis_target_size_pct=0.10)
        g = grade_entry(s)
        assert g.sizing == SIZING_UNDERWEIGHT


class TestGradingDirection:
    def test_no_thesis(self):
        g = grade_entry(_stack(thesis_direction=None))
        assert g.direction == DIRECTION_NO_THESIS

    def test_aligned(self):
        g = grade_entry(_stack(thesis_direction="long", thesis_conviction=0.55))
        assert g.direction == DIRECTION_ALIGNED

    def test_opposed(self):
        g = grade_entry(_stack(direction="long", thesis_direction="short", thesis_conviction=0.6))
        assert g.direction == DIRECTION_OPPOSED

    def test_flat_thesis_treated_as_no_thesis(self):
        g = grade_entry(_stack(thesis_direction="flat", thesis_conviction=0.2))
        assert g.direction == DIRECTION_NO_THESIS


class TestGradingCatalystTiming:
    def test_neutral_no_catalysts(self):
        g = grade_entry(_stack(upcoming_catalysts=[]))
        assert g.catalyst_timing == CATALYST_NEUTRAL

    def test_late_inside_one_hour(self):
        now_ms = 1_712_640_000_000
        g = grade_entry(_stack(
            entry_ts_ms=now_ms,
            upcoming_catalysts=[{
                "_event_ms": now_ms + 30 * 60_000,
                "category": "FOMC",
                "severity": 4,
            }],
        ))
        assert g.catalyst_timing == CATALYST_LATE

    def test_lead_beyond_24h(self):
        now_ms = 1_712_640_000_000
        g = grade_entry(_stack(
            entry_ts_ms=now_ms,
            upcoming_catalysts=[{
                "_event_ms": now_ms + 30 * 3_600_000,
                "category": "OPEC_meeting",
                "severity": 4,
            }],
        ))
        assert g.catalyst_timing == CATALYST_LEAD

    def test_neutral_between_1_and_24h(self):
        now_ms = 1_712_640_000_000
        g = grade_entry(_stack(
            entry_ts_ms=now_ms,
            upcoming_catalysts=[{
                "_event_ms": now_ms + 10 * 3_600_000,
                "category": "misc",
                "severity": 4,
            }],
        ))
        assert g.catalyst_timing == CATALYST_NEUTRAL

    def test_severity_floor_drops_minor(self):
        """Severity below floor means 'no catalyst' effectively."""
        now_ms = 1_712_640_000_000
        g = grade_entry(_stack(
            entry_ts_ms=now_ms,
            upcoming_catalysts=[{
                "_event_ms": now_ms + 30 * 60_000,
                "category": "tweet",
                "severity": 1,
            }],
        ))
        assert g.catalyst_timing == CATALYST_NEUTRAL


class TestGradingLiquidity:
    def test_unknown_without_data(self):
        g = grade_entry(_stack())
        assert g.liquidity == LIQUIDITY_UNKNOWN

    def test_cascade_risk_overrides(self):
        g = grade_entry(_stack(
            recent_cascade_against={"side": "long", "severity": 3, "oi_delta_pct": -2.5},
        ))
        assert g.liquidity == LIQUIDITY_CASCADE_RISK

    def test_wall_within_atr_multiplier_is_risk(self):
        """atr_pct=2 → threshold=2.4% → wall at 100bps (1%) is within."""
        g = grade_entry(_stack(atr_pct=2.0, nearest_wall_bps=100, nearest_wall_side="ask"))
        assert g.liquidity == LIQUIDITY_CASCADE_RISK

    def test_wall_beyond_atr_multiplier_is_safe(self):
        """atr_pct=2 → threshold=2.4% → wall at 300bps (3%) is outside."""
        g = grade_entry(_stack(atr_pct=2.0, nearest_wall_bps=300, nearest_wall_side="ask"))
        assert g.liquidity == LIQUIDITY_SAFE


class TestGradingFunding:
    def test_unknown(self):
        g = grade_entry(_stack())
        assert g.funding == FUNDING_UNKNOWN

    def test_long_cheap_when_negative_funding(self):
        """Negative annualized funding means shorts pay longs → CHEAP for longs."""
        g = grade_entry(_stack(direction="long", funding_bps_annualized=-2.0))
        assert g.funding == FUNDING_CHEAP

    def test_long_expensive_when_high_positive(self):
        g = grade_entry(_stack(direction="long", funding_bps_annualized=40.0))
        assert g.funding == FUNDING_EXPENSIVE

    def test_long_fair_in_middle(self):
        g = grade_entry(_stack(direction="long", funding_bps_annualized=15.0))
        assert g.funding == FUNDING_FAIR

    def test_short_cheap_when_positive(self):
        """Positive bps = longs pay = shorts collect → CHEAP for shorts."""
        g = grade_entry(_stack(direction="short", funding_bps_annualized=20.0))
        assert g.funding == FUNDING_CHEAP


class TestOverallSummary:
    def test_good_when_many_passes(self):
        s = _stack(
            actual_size_pct=0.10, thesis_target_size_pct=0.10,   # GREAT
            thesis_direction="long", thesis_conviction=0.6,       # ALIGNED
            upcoming_catalysts=[],                                 # NEUTRAL
            atr_pct=2.0, nearest_wall_bps=500, nearest_wall_side="ask",  # SAFE
            funding_bps_annualized=-2.0,                           # CHEAP
        )
        g = grade_entry(s)
        assert g.overall_label == "GOOD ENTRY"
        assert g.pass_count >= 3

    def test_bad_when_multiple_failures(self):
        now_ms = 1_712_640_000_000
        s = _stack(
            entry_ts_ms=now_ms,
            actual_size_pct=0.30, thesis_target_size_pct=0.10,   # OVERWEIGHT
            thesis_direction="short", thesis_conviction=0.7,      # OPPOSED
            upcoming_catalysts=[{
                "_event_ms": now_ms + 20 * 60_000,
                "category": "FOMC", "severity": 4,
            }],                                                    # LATE
            atr_pct=2.0, nearest_wall_bps=50, nearest_wall_side="ask",  # CASCADE_RISK (wall)
            funding_bps_annualized=50.0,                          # EXPENSIVE (long)
        )
        g = grade_entry(s)
        assert g.overall_label == "BAD ENTRY"
        assert g.fail_count >= 2


class TestSuggestions:
    def test_overweight_suggests_trim(self):
        s = _stack(actual_size_pct=0.20, thesis_target_size_pct=0.10)
        g = grade_entry(s)
        assert any("over thesis target" in sug for sug in g.suggestions)

    def test_underweight_suggests_scale_in(self):
        s = _stack(actual_size_pct=0.05, thesis_target_size_pct=0.10)
        g = grade_entry(s)
        assert any("Under target" in sug for sug in g.suggestions)

    def test_opposed_suggests_reeval(self):
        g = grade_entry(_stack(direction="long", thesis_direction="short", thesis_conviction=0.6))
        assert any("opposes thesis" in sug for sug in g.suggestions)


# ───────────────────────────────────────────────────────────
# Formatters
# ───────────────────────────────────────────────────────────


class TestFormatters:
    def test_telegram_contains_header_and_grade(self):
        s = _stack(
            actual_size_pct=0.10, thesis_target_size_pct=0.10,
            thesis_direction="long", thesis_conviction=0.6,
            atr_pct=2.0, nearest_wall_bps=500, nearest_wall_side="ask",
            funding_bps_annualized=-2.0,
        )
        g = grade_entry(s)
        out = format_critique_telegram(g, s)
        assert "Entry Critique" in out
        assert "xyz:BRENTOIL" in out
        assert "LONG" in out
        assert "Sizing" in out
        assert "Direction" in out
        assert "Timing" in out
        assert "Liquidity" in out
        assert "Funding" in out
        assert "OVERALL" in out

    def test_telegram_includes_lessons_when_present(self):
        s = _stack(
            thesis_direction="long",
            lessons=[
                {"id": 42, "summary": "BRENTOIL longs in low funding work well when technicals align"},
                {"id": 98, "summary": "avoid scaling in within 6h of FOMC"},
            ],
        )
        g = grade_entry(s)
        out = format_critique_telegram(g, s)
        assert "#42" in out
        assert "#98" in out

    def test_telegram_includes_suggestions_when_present(self):
        s = _stack(actual_size_pct=0.20, thesis_target_size_pct=0.10)
        g = grade_entry(s)
        out = format_critique_telegram(g, s)
        assert "Suggestions" in out

    def test_jsonl_has_required_fields(self):
        s = _stack(
            actual_size_pct=0.10, thesis_target_size_pct=0.10,
            thesis_direction="long", thesis_conviction=0.55,
            thesis_take_profit=98.0,
            atr_value=1.5, atr_pct=2.0,
            funding_bps_annualized=-2.0,
            lessons=[{"id": 42, "summary": "test"}],
        )
        g = grade_entry(s)
        row = format_critique_jsonl(g, s)
        assert row["schema_version"] == 1
        assert row["kind"] == "entry_critique"
        assert row["instrument"] == "xyz:BRENTOIL"
        assert row["direction"] == "long"
        assert row["entry_price"] == 89.5
        assert "grade" in row
        assert row["grade"]["direction"] == DIRECTION_ALIGNED
        assert row["grade"]["overall_label"] in ("GOOD ENTRY", "MIXED ENTRY", "BAD ENTRY")
        assert "signals" in row
        assert row["signals"]["thesis_conviction"] == 0.55
        assert row["signals"]["lesson_ids"] == [42]
        assert "created_at" in row
        # Round-trip through JSON — must be serializable
        assert json.loads(json.dumps(row))["instrument"] == "xyz:BRENTOIL"

    def test_jsonl_strips_internal_event_ms(self):
        now_ms = 1_712_640_000_000
        s = _stack(
            upcoming_catalysts=[{
                "_event_ms": now_ms + 3_600_000,
                "id": "cat1",
                "category": "FOMC",
                "severity": 4,
            }],
        )
        g = grade_entry(s)
        row = format_critique_jsonl(g, s)
        cat = row["signals"]["upcoming_catalysts"][0]
        assert "_event_ms" not in cat
        assert cat["id"] == "cat1"
