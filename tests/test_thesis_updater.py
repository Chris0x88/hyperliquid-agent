"""Tests for modules/thesis_updater.py"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from trading.thesis.updater import (
    HaikuClassification,
    ThesisUpdaterEngine,
    apply_guardrails,
    build_haiku_prompt,
    compute_conviction_delta,
    determine_tier,
    adjust_tier_with_price,
    parse_haiku_response,
    _news_helps_position,
)


# ---------------------------------------------------------------------------
# Tier determination
# ---------------------------------------------------------------------------

class TestDetermineTier:
    def test_minor(self):
        assert determine_tier(0) == "MINOR"
        assert determine_tier(3) == "MINOR"

    def test_moderate(self):
        assert determine_tier(4) == "MODERATE"
        assert determine_tier(6) == "MODERATE"

    def test_major(self):
        assert determine_tier(7) == "MAJOR"
        assert determine_tier(8) == "MAJOR"

    def test_critical(self):
        assert determine_tier(9) == "CRITICAL"
        assert determine_tier(10) == "CRITICAL"


class TestAdjustTierWithPrice:
    def test_critical_unchanged(self):
        assert adjust_tier_with_price("CRITICAL", 0.0, 0.0) == "CRITICAL"

    def test_major_upgraded_by_price(self):
        assert adjust_tier_with_price("MAJOR", 6.0, 1.0) == "CRITICAL"

    def test_major_upgraded_by_volume(self):
        assert adjust_tier_with_price("MAJOR", 1.0, 4.0) == "CRITICAL"

    def test_major_not_upgraded(self):
        assert adjust_tier_with_price("MAJOR", 2.0, 1.0) == "MAJOR"

    def test_moderate_upgraded_by_price(self):
        assert adjust_tier_with_price("MODERATE", 4.0, 1.0) == "MAJOR"

    def test_moderate_not_upgraded(self):
        assert adjust_tier_with_price("MODERATE", 1.0, 1.0) == "MODERATE"

    def test_minor_unchanged(self):
        assert adjust_tier_with_price("MINOR", 10.0, 10.0) == "MINOR"


# ---------------------------------------------------------------------------
# News direction vs thesis direction
# ---------------------------------------------------------------------------

class TestNewsHelpsPosition:
    def test_bullish_long(self):
        assert _news_helps_position("bullish", "long") is True

    def test_bearish_short(self):
        assert _news_helps_position("bearish", "short") is True

    def test_bullish_short(self):
        assert _news_helps_position("bullish", "short") is False

    def test_bearish_long(self):
        assert _news_helps_position("bearish", "long") is False

    def test_unclear_long(self):
        assert _news_helps_position("unclear", "long") is False

    def test_mixed_short(self):
        assert _news_helps_position("mixed", "short") is False

    def test_flat(self):
        assert _news_helps_position("bullish", "flat") is False


# ---------------------------------------------------------------------------
# Conviction delta computation
# ---------------------------------------------------------------------------

class TestComputeConvictionDelta:
    def test_minor_no_delta(self):
        delta, side = compute_conviction_delta("MINOR", 2, "bullish", "long")
        assert delta == 0.0

    def test_critical_helps(self):
        delta, side = compute_conviction_delta("CRITICAL", 10, "bullish", "long")
        assert delta == 0.15
        assert side == "for"

    def test_critical_hurts(self):
        delta, side = compute_conviction_delta("CRITICAL", 10, "bearish", "long")
        assert delta == -0.15
        assert side == "against"

    def test_major_helps(self):
        delta, side = compute_conviction_delta("MAJOR", 8, "bearish", "short")
        assert delta == pytest.approx(0.12)
        assert side == "for"

    def test_moderate_scales(self):
        delta4, _ = compute_conviction_delta("MODERATE", 4, "bullish", "long")
        delta6, _ = compute_conviction_delta("MODERATE", 6, "bullish", "long")
        assert delta6 > delta4  # higher score = higher delta


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

class TestGuardrails:
    def test_per_event_cap(self):
        delta, guardrail = apply_guardrails(0.25, 0.5, 0.0)
        assert delta == 0.15
        assert guardrail == "per_event_cap"

    def test_24h_cap(self):
        delta, guardrail = apply_guardrails(0.10, 0.5, 0.25)
        assert delta == pytest.approx(0.05)  # only 0.05 remaining in 24h budget
        assert guardrail == "24h_cap"

    def test_24h_exhausted(self):
        delta, guardrail = apply_guardrails(0.10, 0.5, 0.30)
        assert delta == 0.0
        assert guardrail == "24h_cap"

    def test_conviction_upper_bound(self):
        delta, guardrail = apply_guardrails(0.10, 0.95, 0.0)
        assert delta == pytest.approx(0.05)
        assert guardrail == "boundary"

    def test_conviction_lower_bound(self):
        delta, guardrail = apply_guardrails(-0.10, 0.03, 0.0)
        assert delta == pytest.approx(-0.03)
        assert guardrail == "boundary"

    def test_weekend_dampening(self):
        delta, _ = apply_guardrails(0.10, 0.5, 0.0, weekend=True)
        assert delta == pytest.approx(0.05)

    def test_no_guardrail_hit(self):
        delta, guardrail = apply_guardrails(0.10, 0.5, 0.0)
        assert delta == 0.10
        assert guardrail == ""

    def test_negative_delta_capped(self):
        delta, guardrail = apply_guardrails(-0.20, 0.5, 0.0)
        assert delta == -0.15
        assert guardrail == "per_event_cap"


# ---------------------------------------------------------------------------
# Haiku response parsing
# ---------------------------------------------------------------------------

class TestParseHaikuResponse:
    def test_valid_json(self):
        text = json.dumps({
            "impact_score": 7,
            "affected_markets": ["xyz:BRENTOIL"],
            "direction_hint": "bearish",
            "summary": "Ceasefire announced",
            "need_full_article": False,
        })
        result = parse_haiku_response(text)
        assert result is not None
        assert result.impact_score == 7
        assert result.direction_hint == "bearish"

    def test_code_fenced_json(self):
        text = '```json\n{"impact_score": 5, "affected_markets": [], "direction_hint": "unclear", "summary": "test", "need_full_article": false}\n```'
        result = parse_haiku_response(text)
        assert result is not None
        assert result.impact_score == 5

    def test_invalid_json(self):
        result = parse_haiku_response("not json at all")
        assert result is None

    def test_empty_string(self):
        """Empty Haiku response (whitespace-only block) returns None gracefully."""
        assert parse_haiku_response("") is None
        assert parse_haiku_response("   ") is None

    def test_trailing_prose_after_json(self):
        """Haiku often appends an explanation after the JSON object.

        This was the primary failure mode seen 2026-04-17: json.loads raises
        'Extra data' because it sees characters after the closing '}'.
        The fix: extract the first {...} block before calling json.loads.
        """
        raw = (
            '{"impact_score": 7, "affected_markets": ["xyz:BRENTOIL"], '
            '"direction_hint": "bearish", "summary": "Iran ceasefire reduces supply risk", '
            '"need_full_article": false}'
            "\n\nNote: This news is significant because of ongoing US-Iran tensions."
        )
        result = parse_haiku_response(raw)
        assert result is not None, "Expected successful parse but got None"
        assert result.impact_score == 7
        assert result.direction_hint == "bearish"
        assert "BRENTOIL" in result.affected_markets[0]

    def test_code_fence_with_trailing_text_after_closing_fence(self):
        """Haiku sometimes adds prose after the closing ``` fence.

        The old regex re.sub(r'\\s*```$', '', ...) only matched ``` at the very
        end of the string. If trailing prose was present, the closing fence was
        not at the end, so the regex left it in place — causing json.loads to
        fail on the remaining ``` and prose.
        """
        raw = (
            "```json\n"
            '{"impact_score": 5, "affected_markets": [], "direction_hint": "unclear",'
            ' "summary": "test", "need_full_article": false}\n'
            "```\n"
            "This is my additional analysis of the current geopolitical situation."
        )
        result = parse_haiku_response(raw)
        assert result is not None, "Expected successful parse but got None"
        assert result.impact_score == 5

    def test_preamble_text_before_json(self):
        """Haiku occasionally emits a preamble sentence before the JSON block."""
        raw = (
            "Here is my assessment of the news:\n"
            '{"impact_score": 6, "affected_markets": ["xyz:GOLD"], '
            '"direction_hint": "bullish", "summary": "Gold demand rises", '
            '"need_full_article": false}'
        )
        result = parse_haiku_response(raw)
        assert result is not None, "Expected successful parse but got None"
        assert result.impact_score == 6
        assert result.direction_hint == "bullish"

    def test_score_clamped(self):
        text = json.dumps({
            "impact_score": 15,
            "affected_markets": [],
            "direction_hint": "unclear",
            "summary": "",
        })
        result = parse_haiku_response(text)
        assert result is not None
        assert result.impact_score == 10


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

class TestBuildHaikuPrompt:
    def test_basic_prompt(self):
        msgs = build_haiku_prompt(
            "Oil drops 20%", "Details here", "iran_deal",
            "Oil is dominant",
        )
        assert len(msgs) == 2
        assert "Oil is dominant" in msgs[0]["content"]
        assert "Oil drops 20%" in msgs[1]["content"]

    def test_with_full_article(self):
        msgs = build_haiku_prompt(
            "Test", "excerpt", "test",
            "context",
            full_article_text="Full article body here",
        )
        assert "Full article body" in msgs[1]["content"]


# ---------------------------------------------------------------------------
# Engine integration tests
# ---------------------------------------------------------------------------

class TestThesisUpdaterEngine:
    @pytest.fixture
    def tmp_dir(self, tmp_path):
        """Set up temp directory with thesis files and config."""
        thesis_dir = tmp_path / "thesis"
        thesis_dir.mkdir()
        news_dir = tmp_path / "news"
        news_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Write a thesis file
        thesis = {
            "market": "xyz:BRENTOIL",
            "direction": "long",
            "conviction": 0.60,
            "thesis_summary": "Oil long thesis",
            "invalidation_conditions": ["ceasefire"],
            "evidence_for": [],
            "evidence_against": [],
            "recommended_leverage": 10.0,
            "recommended_size_pct": 0.10,
            "weekend_leverage_cap": 5.0,
            "last_evaluation_ts": 0,
            "take_profit_price": None,
        }
        (thesis_dir / "xyz_brentoil_state.json").write_text(json.dumps(thesis))

        # Write config
        config = {
            "enabled": True,
            "catalysts_jsonl": str(news_dir / "catalysts.jsonl"),
            "headlines_jsonl": str(news_dir / "headlines.jsonl"),
            "audit_jsonl": str(thesis_dir / "audit.jsonl"),
            "news_log_jsonl": str(thesis_dir / "news_log.jsonl"),
            "thesis_dir": str(thesis_dir),
            "max_delta_per_event": 0.15,
            "max_delta_per_24h": 0.30,
            "go_flat_threshold": 0.10,
            "cooldown_minutes_default": 60,
            "weekend_dampening_factor": 0.5,
            "macro_context": "Oil is dominant driver",
        }
        config_path = config_dir / "thesis_updater.json"
        config_path.write_text(json.dumps(config))

        # Write a headline
        headline = {
            "id": "h1",
            "source": "test",
            "url": "https://example.com",
            "title": "Iran ceasefire announced",
            "body_excerpt": "A two-week ceasefire has been declared...",
            "published_at": "2026-04-08T00:00:00Z",
            "fetched_at": "2026-04-08T00:01:00Z",
        }
        (news_dir / "headlines.jsonl").write_text(json.dumps(headline) + "\n")

        # Write a catalyst
        catalyst = {
            "id": "c1",
            "headline_id": "h1",
            "instruments": ["xyz:BRENTOIL"],
            "event_date": "2026-04-08T00:00:00Z",
            "category": "iran_deal",
            "severity": 4,
            "expected_direction": "bear",
            "rationale": "rule: iran_deal",
            "created_at": "2026-04-08T00:01:00Z",
        }
        (news_dir / "catalysts.jsonl").write_text(json.dumps(catalyst) + "\n")

        return tmp_path, config_path

    @patch("trading.thesis.updater.is_weekend", return_value=False)
    def test_process_catalyst_critical_defensive(self, _mock_wknd, tmp_dir):
        """CRITICAL bearish news on a long position triggers defensive mode."""
        tmp_path, config_path = tmp_dir

        # Mock Haiku
        def mock_haiku(messages):
            return json.dumps({
                "impact_score": 9,
                "affected_markets": ["xyz:BRENTOIL"],
                "direction_hint": "bearish",
                "summary": "Iran ceasefire reduces supply disruption risk",
                "need_full_article": False,
            })

        engine = ThesisUpdaterEngine(config_path=str(config_path), call_haiku_fn=mock_haiku)
        engine.reload_config()

        catalyst = json.loads((tmp_path / "news" / "catalysts.jsonl").read_text().strip())
        headline = json.loads((tmp_path / "news" / "headlines.jsonl").read_text().strip())

        classification = engine.classify_catalyst(catalyst, headline)
        assert classification is not None
        assert classification.impact_score == 9

        changes = engine.process_catalyst(catalyst, headline, classification)
        assert len(changes) == 1

        change = changes[0]
        assert change.tier == "CRITICAL"
        assert change.defensive_mode is True
        assert change.conviction_after < change.conviction_before
        assert change.delta_applied == pytest.approx(-0.15)

        # Check leverage was halved
        thesis = json.loads((tmp_path / "thesis" / "xyz_brentoil_state.json").read_text())
        assert thesis["recommended_leverage"] == 5.0  # halved from 10
        assert thesis["weekend_leverage_cap"] == 2.5  # halved from 5

    @patch("trading.thesis.updater.is_weekend", return_value=True)
    def test_process_catalyst_critical_defensive_weekend(self, _mock_wknd, tmp_dir):
        """CRITICAL bearish news on weekend applies 0.5x dampening."""
        tmp_path, config_path = tmp_dir

        def mock_haiku(messages):
            return json.dumps({
                "impact_score": 9,
                "affected_markets": ["xyz:BRENTOIL"],
                "direction_hint": "bearish",
                "summary": "Iran ceasefire reduces supply disruption risk",
                "need_full_article": False,
            })

        engine = ThesisUpdaterEngine(config_path=str(config_path), call_haiku_fn=mock_haiku)
        engine.reload_config()

        catalyst = json.loads((tmp_path / "news" / "catalysts.jsonl").read_text().strip())
        headline = json.loads((tmp_path / "news" / "headlines.jsonl").read_text().strip())

        classification = engine.classify_catalyst(catalyst, headline)
        changes = engine.process_catalyst(catalyst, headline, classification)
        assert len(changes) == 1

        change = changes[0]
        assert change.tier == "CRITICAL"
        assert change.defensive_mode is True
        assert change.delta_applied == pytest.approx(-0.075)  # 0.15 * 0.5 weekend factor

    def test_process_catalyst_critical_bullish(self, tmp_dir):
        """CRITICAL bullish news on a long position strengthens conviction."""
        tmp_path, config_path = tmp_dir

        def mock_haiku(messages):
            return json.dumps({
                "impact_score": 10,
                "affected_markets": ["xyz:BRENTOIL"],
                "direction_hint": "bullish",
                "summary": "Hormuz blockade intensifies, oil supply cut",
                "need_full_article": False,
            })

        engine = ThesisUpdaterEngine(config_path=str(config_path), call_haiku_fn=mock_haiku)
        engine.reload_config()

        catalyst = {"id": "c2", "headline_id": "h1", "category": "chokepoint_blockade",
                    "severity": 5, "expected_direction": "bull"}
        headline = {"id": "h1", "title": "Hormuz fully blocked", "body_excerpt": "...", "url": ""}

        classification = engine.classify_catalyst(catalyst, headline)
        changes = engine.process_catalyst(catalyst, headline, classification)

        assert len(changes) == 1
        change = changes[0]
        assert change.conviction_after > change.conviction_before
        assert change.defensive_mode is False
        assert change.evidence_side == "for"

    def test_dedup(self, tmp_dir):
        """Same catalyst ID is only processed once."""
        tmp_path, config_path = tmp_dir

        def mock_haiku(messages):
            return json.dumps({
                "impact_score": 5,
                "affected_markets": ["xyz:BRENTOIL"],
                "direction_hint": "bearish",
                "summary": "test",
            })

        engine = ThesisUpdaterEngine(config_path=str(config_path), call_haiku_fn=mock_haiku)
        engine.reload_config()

        catalyst = {"id": "c1", "headline_id": "h1", "category": "iran_deal",
                    "severity": 4, "expected_direction": "bear"}
        headline = {"id": "h1", "title": "Test", "body_excerpt": "...", "url": ""}

        classification = engine.classify_catalyst(catalyst, headline)
        changes1 = engine.process_catalyst(catalyst, headline, classification)
        changes2 = engine.process_catalyst(catalyst, headline, classification)

        assert len(changes1) == 1
        assert len(changes2) == 0  # deduped

    def test_minor_no_change(self, tmp_dir):
        """MINOR tier news doesn't change conviction."""
        tmp_path, config_path = tmp_dir

        def mock_haiku(messages):
            return json.dumps({
                "impact_score": 2,
                "affected_markets": ["xyz:BRENTOIL"],
                "direction_hint": "unclear",
                "summary": "routine report",
            })

        engine = ThesisUpdaterEngine(config_path=str(config_path), call_haiku_fn=mock_haiku)
        engine.reload_config()

        catalyst = {"id": "c3", "headline_id": "h1", "category": "eia_weekly",
                    "severity": 3, "expected_direction": None}
        headline = {"id": "h1", "title": "EIA weekly", "body_excerpt": "...", "url": ""}

        classification = engine.classify_catalyst(catalyst, headline)
        changes = engine.process_catalyst(catalyst, headline, classification)

        assert len(changes) == 0

    def test_consecutive_parse_failures_logged(self, tmp_dir, caplog):
        """Engine warns when >= 3 consecutive Haiku parse failures occur."""
        import logging
        _, config_path = tmp_dir

        # Haiku returns unparseable garbage every time
        def bad_haiku(messages):
            return "This is not JSON and never will be."

        engine = ThesisUpdaterEngine(config_path=str(config_path), call_haiku_fn=bad_haiku)
        engine.reload_config()

        catalyst = {"id": "cx", "headline_id": "h1", "category": "test", "severity": 3}
        headline = {"id": "h1", "title": "Test", "body_excerpt": "...", "url": ""}

        with caplog.at_level(logging.WARNING, logger="thesis_updater"):
            for _ in range(3):
                engine.classify_catalyst(catalyst, headline)

        # Should have emitted the consecutive-failure warning by the 3rd failure
        warning_msgs = [r.message for r in caplog.records if "consecutive Haiku parse failure" in r.message]
        assert len(warning_msgs) >= 1, (
            "Expected consecutive parse failure warning but none was logged"
        )

    def test_consecutive_failures_reset_on_success(self, tmp_dir):
        """Consecutive failure counter resets when parse succeeds."""
        import json as _json
        _, config_path = tmp_dir

        call_count = [0]

        def sometimes_bad_haiku(messages):
            call_count[0] += 1
            if call_count[0] <= 2:
                return "not json"
            return _json.dumps({
                "impact_score": 4,
                "affected_markets": ["xyz:BRENTOIL"],
                "direction_hint": "bearish",
                "summary": "ok",
                "need_full_article": False,
            })

        engine = ThesisUpdaterEngine(config_path=str(config_path), call_haiku_fn=sometimes_bad_haiku)
        engine.reload_config()

        catalyst = {"id": "cy", "headline_id": "h1", "category": "test", "severity": 3}
        headline = {"id": "h1", "title": "Test", "body_excerpt": "...", "url": ""}

        engine.classify_catalyst(catalyst, headline)  # fail 1
        engine.classify_catalyst(catalyst, headline)  # fail 2
        assert engine._consecutive_parse_failures == 2

        engine.classify_catalyst(catalyst, headline)  # success
        assert engine._consecutive_parse_failures == 0

    def test_audit_trail_written(self, tmp_dir):
        """Audit trail is written for conviction changes."""
        tmp_path, config_path = tmp_dir

        def mock_haiku(messages):
            return json.dumps({
                "impact_score": 6,
                "affected_markets": ["xyz:BRENTOIL"],
                "direction_hint": "bearish",
                "summary": "moderate news",
            })

        engine = ThesisUpdaterEngine(config_path=str(config_path), call_haiku_fn=mock_haiku)
        engine.reload_config()

        catalyst = {"id": "c4", "headline_id": "h1", "category": "trump_oil_announcement",
                    "severity": 4, "expected_direction": None}
        headline = {"id": "h1", "title": "Trump announces something", "body_excerpt": "...", "url": ""}

        classification = engine.classify_catalyst(catalyst, headline)
        engine.process_catalyst(catalyst, headline, classification)

        audit_path = tmp_path / "thesis" / "audit.jsonl"
        assert audit_path.exists()
        entries = [json.loads(l) for l in audit_path.read_text().strip().split("\n")]
        assert len(entries) == 1
        assert entries[0]["market"] == "xyz:BRENTOIL"
        assert entries[0]["tier"] == "MODERATE"
