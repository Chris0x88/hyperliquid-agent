"""Tests for engines/checklist/sweep_detector.py."""
from __future__ import annotations

import time

import pytest

from engines.checklist.sweep_detector import (
    detect_sweep_risk,
    _zone_within_atr,
    _recent_cascade,
    _funding_adverse,
    _bot_pattern_sweep_signal,
    PHASE3_GAPS,
)

# ── Fixtures ──────────────────────────────────────────────────

SILVER_LONG_POS = {
    "coin": "xyz:SILVER",
    "size": 50.0,
    "leverage": "25",
}


def _base_ctx(**overrides):
    ctx = {
        "positions": [SILVER_LONG_POS],
        "market_price": 72.0,
        "atr": 2.5,
        "funding_rate": 0.0001,
        "heatmap_zones": [],
        "cascades": [],
        "bot_patterns": [],
    }
    ctx.update(overrides)
    return ctx


# ── _zone_within_atr ─────────────────────────────────────────

class TestZoneWithinAtr:
    def test_no_zones_returns_none(self):
        result = _zone_within_atr([], 72.0, 2.5, "long")
        assert result is None

    def test_zone_within_threshold_long(self):
        """Bid-side zone below price and within 1.5 ATR should flag."""
        zone = {
            "centroid": 70.0,  # 72 - 70 = 2 < 1.5 * 2.5 = 3.75
            "side": "bid",
            "notional_usd": 1_000_000.0,
            "instrument": "xyz:SILVER",
        }
        result = _zone_within_atr([zone], 72.0, 2.5, "long")
        assert result is not None
        assert result["centroid"] == 70.0

    def test_zone_outside_threshold_returns_none(self):
        """Zone 5 ATR away should not flag."""
        zone = {
            "centroid": 59.5,  # 72 - 59.5 = 12.5 > 3.75
            "side": "bid",
            "notional_usd": 1_000_000.0,
            "instrument": "xyz:SILVER",
        }
        result = _zone_within_atr([zone], 72.0, 2.5, "long")
        assert result is None

    def test_ask_zone_not_adverse_for_long(self):
        """Ask-side zone (above price) is not adverse for a long position."""
        zone = {
            "centroid": 74.0,
            "side": "ask",
            "notional_usd": 5_000_000.0,
            "instrument": "xyz:SILVER",
        }
        result = _zone_within_atr([zone], 72.0, 2.5, "long")
        assert result is None

    def test_ask_zone_adverse_for_short(self):
        """Ask-side zone above price IS adverse for a short position."""
        zone = {
            "centroid": 74.0,  # 74 - 72 = 2 < 3.75
            "side": "ask",
            "notional_usd": 2_000_000.0,
            "instrument": "xyz:SILVER",
        }
        result = _zone_within_atr([zone], 72.0, 2.5, "short")
        assert result is not None

    def test_picks_highest_notional(self):
        """When multiple zones qualify, return the highest notional."""
        zone_small = {"centroid": 70.5, "side": "bid", "notional_usd": 100_000.0}
        zone_large = {"centroid": 71.0, "side": "bid", "notional_usd": 5_000_000.0}
        result = _zone_within_atr([zone_small, zone_large], 72.0, 2.5, "long")
        assert result["notional_usd"] == 5_000_000.0


# ── _recent_cascade ───────────────────────────────────────────

class TestRecentCascade:
    def test_no_cascades_returns_none(self):
        assert _recent_cascade([], "xyz:SILVER") is None

    def test_returns_recent_cascade(self):
        now = time.time()
        cascade = {"instrument": "xyz:SILVER", "ts": now - 3600}  # 1h ago
        result = _recent_cascade([cascade], "xyz:SILVER")
        assert result is not None

    def test_ignores_old_cascade(self):
        old = time.time() - 25 * 3600  # 25h ago, outside 18h window
        cascade = {"instrument": "xyz:SILVER", "ts": old}
        result = _recent_cascade([cascade], "xyz:SILVER")
        assert result is None

    def test_matches_bare_coin(self):
        now = time.time()
        cascade = {"instrument": "SILVER", "ts": now - 1800}
        result = _recent_cascade([cascade], "xyz:SILVER")
        assert result is not None


# ── _funding_adverse ──────────────────────────────────────────

class TestFundingAdverse:
    def test_not_adverse_when_none(self):
        assert _funding_adverse(None, "long") is False

    def test_adverse_for_long_positive_rate(self):
        # 0.001/h, threshold is 0.002/8 = 0.00025 → 0.001 > 0.00025 → adverse
        assert _funding_adverse(0.001, "long") is True

    def test_not_adverse_for_long_low_rate(self):
        assert _funding_adverse(0.0001, "long") is False

    def test_adverse_for_short_negative_rate(self):
        assert _funding_adverse(-0.001, "short") is True

    def test_not_adverse_for_short_positive_rate(self):
        assert _funding_adverse(0.001, "short") is False


# ── _bot_pattern_sweep_signal ─────────────────────────────────

class TestBotPatternSweepSignal:
    def test_no_patterns_returns_false(self):
        assert _bot_pattern_sweep_signal([], "xyz:SILVER") is False

    def test_sweep_keyword_in_pattern_type(self):
        bp = {"instrument": "SILVER", "pattern_type": "liquidation_sweep", "tags": []}
        assert _bot_pattern_sweep_signal([bp], "xyz:SILVER") is True

    def test_sweep_keyword_in_tags(self):
        bp = {"instrument": "SILVER", "pattern_type": "accumulation", "tags": ["spoofing", "step_up"]}
        assert _bot_pattern_sweep_signal([bp], "xyz:SILVER") is True

    def test_different_market_ignored(self):
        bp = {"instrument": "BTC", "pattern_type": "sweep", "tags": []}
        assert _bot_pattern_sweep_signal([bp], "xyz:SILVER") is False


# ── detect_sweep_risk (integration) ──────────────────────────

class TestDetectSweepRisk:
    def test_score_0_clean_context(self):
        ctx = _base_ctx()
        result = detect_sweep_risk("xyz:SILVER", ctx)
        assert result["score"] == 0
        assert result["flags"] == []
        assert "phase3_gaps" in result

    def test_score_1_single_flag_zone(self):
        zone = {
            "centroid": 70.0,
            "side": "bid",
            "notional_usd": 2_000_000.0,
        }
        ctx = _base_ctx(heatmap_zones=[zone])
        result = detect_sweep_risk("xyz:SILVER", ctx)
        assert result["score"] == 1
        assert len(result["flags"]) == 1

    def test_score_2_zone_and_funding(self):
        zone = {"centroid": 70.0, "side": "bid", "notional_usd": 2_000_000.0}
        ctx = _base_ctx(heatmap_zones=[zone], funding_rate=0.005)
        result = detect_sweep_risk("xyz:SILVER", ctx)
        assert result["score"] == 2
        assert len(result["flags"]) == 2

    def test_score_3_three_flags(self):
        zone = {"centroid": 70.0, "side": "bid", "notional_usd": 2_000_000.0}
        cascade = {"instrument": "xyz:SILVER", "ts": time.time() - 3600}
        ctx = _base_ctx(
            heatmap_zones=[zone],
            funding_rate=0.005,
            cascades=[cascade],
        )
        result = detect_sweep_risk("xyz:SILVER", ctx)
        assert result["score"] == 3

    def test_score_3_severe_combination(self):
        """Zone + funding + cascade triggers severe flag = score 3."""
        zone = {"centroid": 70.0, "side": "bid", "notional_usd": 5_000_000.0}
        cascade = {"instrument": "SILVER", "ts": time.time() - 1800}
        ctx = _base_ctx(
            heatmap_zones=[zone],
            funding_rate=0.01,  # very high
            cascades=[cascade],
        )
        result = detect_sweep_risk("xyz:SILVER", ctx)
        assert result["score"] == 3

    def test_phase3_gaps_always_present(self):
        ctx = _base_ctx()
        result = detect_sweep_risk("xyz:SILVER", ctx)
        assert len(result["phase3_gaps"]) == 3
        assert all("not" in g or "no" in g.lower() for g in result["phase3_gaps"])

    def test_no_position_defaults_long(self):
        """No position in ctx — should default to long side and not crash."""
        ctx = _base_ctx(positions=[])
        result = detect_sweep_risk("xyz:SILVER", ctx)
        assert "score" in result
        assert result["position_side"] == "long"

    def test_short_position_correct_side(self):
        short = dict(SILVER_LONG_POS, size=-50.0)
        ctx = _base_ctx(positions=[short])
        result = detect_sweep_risk("xyz:SILVER", ctx)
        assert result["position_side"] == "short"
