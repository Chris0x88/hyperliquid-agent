"""Tests for the trade lesson engine (pure computation, zero I/O)."""
from __future__ import annotations

import json

import pytest

from engines.learning.lesson_engine import (
    LESSON_TYPES,
    Lesson,
    LessonAuthorRequest,
    LessonEngine,
    VALID_DIRECTIONS,
    VALID_OUTCOMES,
)


# ---------------------------------------------------------------------------
# Lesson dataclass
# ---------------------------------------------------------------------------

class TestLesson:
    def test_default_values(self):
        lesson = Lesson()
        assert lesson.id == 0
        assert lesson.tags == []
        assert lesson.reviewed_by_chris == 0
        assert lesson.conviction_at_open is None

    def test_roundtrip_preserves_all_fields(self):
        original = Lesson(
            id=42,
            created_at="2026-04-09T05:00:00Z",
            trade_closed_at="2026-04-09T04:55:00Z",
            market="xyz:BRENTOIL",
            direction="long",
            signal_source="thesis_driven",
            lesson_type="entry_timing",
            outcome="win",
            pnl_usd=123.45,
            roe_pct=8.7,
            holding_ms=3_600_000,
            conviction_at_open=0.72,
            journal_entry_id="xyz:BRENTOIL-1712633100000",
            thesis_snapshot_path="data/thesis_snapshots/xyz_brentoil_20260409T040000.json",
            summary="BRENTOIL long on EIA draw, entry ahead of print.",
            body_full="## verbatim body",
            tags=["supply-disruption", "eia-confirmed"],
            reviewed_by_chris=1,
        )
        roundtripped = Lesson.from_dict(original.to_dict())
        assert roundtripped == original

    def test_from_dict_tolerates_json_string_tags(self):
        """SQLite round-trip stores tags as a JSON string. from_dict must decode."""
        d = {
            "id": 1,
            "market": "BTC",
            "direction": "long",
            "tags": json.dumps(["weekend-wick", "stop-hunt"]),
        }
        lesson = Lesson.from_dict(d)
        assert lesson.tags == ["weekend-wick", "stop-hunt"]

    def test_from_dict_tolerates_empty_tags(self):
        lesson = Lesson.from_dict({"tags": ""})
        assert lesson.tags == []

    def test_from_dict_tolerates_garbage_tags(self):
        lesson = Lesson.from_dict({"tags": "not-json"})
        assert lesson.tags == []

    def test_to_dict_rounds_floats(self):
        lesson = Lesson(pnl_usd=123.456789, roe_pct=8.749)
        d = lesson.to_dict()
        assert d["pnl_usd"] == 123.4568
        assert d["roe_pct"] == 8.75


# ---------------------------------------------------------------------------
# Outcome classification
# ---------------------------------------------------------------------------

class TestClassifyOutcome:
    def test_win(self):
        assert LessonEngine.classify_outcome(50.0, 5.0) == "win"

    def test_loss(self):
        assert LessonEngine.classify_outcome(-50.0, -5.0) == "loss"

    def test_breakeven_small_positive(self):
        assert LessonEngine.classify_outcome(0.10, 0.1) == "breakeven"

    def test_breakeven_small_negative(self):
        assert LessonEngine.classify_outcome(-0.10, -0.1) == "breakeven"

    def test_breakeven_boundary(self):
        # |roe| < 0.5% is breakeven; 0.5% exact is not
        assert LessonEngine.classify_outcome(1.0, 0.49) == "breakeven"
        assert LessonEngine.classify_outcome(1.0, 0.5) == "win"

    def test_all_outputs_are_valid(self):
        for pnl, roe in [(10, 5), (-10, -5), (0.01, 0.1), (0, 0)]:
            assert LessonEngine.classify_outcome(pnl, roe) in VALID_OUTCOMES


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

class TestLessonAuthorRequest:
    def test_empty_request_produces_empty_block(self):
        req = LessonAuthorRequest()
        assert req.assemble_context_block() == ""

    def test_journal_entry_only(self):
        req = LessonAuthorRequest(
            journal_entry={"instrument": "BTC", "direction": "long", "pnl": 10.0},
        )
        block = req.assemble_context_block()
        assert "### journal_entry" in block
        assert '"instrument": "BTC"' in block
        # No other sections present
        assert "thesis_snapshot_at_open" not in block
        assert "learnings_md_slice" not in block

    def test_all_sections_present_and_ordered(self):
        req = LessonAuthorRequest(
            journal_entry={"instrument": "BTC"},
            thesis_snapshot={"conviction": 0.7},
            thesis_snapshot_path="path/to/snap.json",
            learnings_md_slice="- noted EIA draw expected",
            autoresearch_eval_window="sizing_alignment=ok",
            news_context_at_open="OPEC+ meeting Sunday",
        )
        block = req.assemble_context_block()
        # All sections present
        for header in (
            "### journal_entry",
            "### thesis_snapshot_at_open",
            "### learnings_md_slice",
            "### autoresearch_eval_window",
            "### news_context_at_open",
        ):
            assert header in block
        # Stable ordering: journal first, thesis second, then md, then eval, then news
        assert block.index("### journal_entry") < block.index("### thesis_snapshot_at_open")
        assert block.index("### thesis_snapshot_at_open") < block.index("### learnings_md_slice")
        assert block.index("### learnings_md_slice") < block.index("### autoresearch_eval_window")
        assert block.index("### autoresearch_eval_window") < block.index("### news_context_at_open")
        assert "path/to/snap.json" in block

    def test_whitespace_only_sections_are_skipped(self):
        req = LessonAuthorRequest(
            journal_entry={"instrument": "BTC"},
            learnings_md_slice="   \n  ",
            autoresearch_eval_window="",
        )
        block = req.assemble_context_block()
        assert "### learnings_md_slice" not in block
        assert "### autoresearch_eval_window" not in block


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

class TestBuildLessonPrompt:
    def test_prompt_contains_sentinels(self):
        engine = LessonEngine()
        req = LessonAuthorRequest(
            journal_entry={"instrument": "xyz:BRENTOIL", "direction": "long", "roe_pct": 8.5, "close_reason": "take_profit"},
        )
        prompt = engine.build_lesson_prompt(req)
        # All three sentinel pairs must appear
        for tag in (
            "<<<LESSON_SUMMARY>>>",
            "<<<END_LESSON_SUMMARY>>>",
            "<<<LESSON_TAGS>>>",
            "<<<END_LESSON_TAGS>>>",
            "<<<LESSON_TYPE>>>",
            "<<<END_LESSON_TYPE>>>",
        ):
            assert tag in prompt

    def test_prompt_includes_all_lesson_types(self):
        engine = LessonEngine()
        prompt = engine.build_lesson_prompt(LessonAuthorRequest())
        for t in LESSON_TYPES:
            assert t in prompt

    def test_prompt_mentions_trade_details(self):
        engine = LessonEngine()
        req = LessonAuthorRequest(
            journal_entry={
                "instrument": "xyz:BRENTOIL",
                "direction": "long",
                "roe_pct": 8.5,
                "close_reason": "take_profit",
            },
        )
        prompt = engine.build_lesson_prompt(req)
        assert "xyz:BRENTOIL" in prompt
        assert "long" in prompt
        assert "+8.50%" in prompt
        assert "take_profit" in prompt

    def test_prompt_embeds_context_block(self):
        engine = LessonEngine()
        req = LessonAuthorRequest(
            journal_entry={"instrument": "BTC"},
            thesis_snapshot={"conviction": 0.7},
            news_context_at_open="EIA draw Wednesday 10:30",
        )
        prompt = engine.build_lesson_prompt(req)
        assert "### journal_entry" in prompt
        assert "### thesis_snapshot_at_open" in prompt
        assert "EIA draw" in prompt


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _valid_response(
    lesson_type: str = "entry_timing",
    summary: str = "BRENTOIL long on EIA draw — entry ahead of print, +8% in 31h.",
    tags: str = "supply-disruption, eia-confirmed",
    extra_body: str = "## Analysis\n\n(a) what happened: EIA confirmed.",
) -> str:
    return (
        f"<<<LESSON_TYPE>>>\n{lesson_type}\n<<<END_LESSON_TYPE>>>\n\n"
        f"<<<LESSON_SUMMARY>>>\n{summary}\n<<<END_LESSON_SUMMARY>>>\n\n"
        f"<<<LESSON_TAGS>>>\n{tags}\n<<<END_LESSON_TAGS>>>\n\n"
        f"{extra_body}"
    )


class TestParseLessonResponse:
    def _req(self) -> LessonAuthorRequest:
        return LessonAuthorRequest(
            journal_entry={"instrument": "xyz:BRENTOIL", "direction": "long"},
        )

    def _call(self, engine: LessonEngine, response: str, **overrides) -> Lesson:
        defaults = dict(
            response_text=response,
            request=self._req(),
            market="xyz:BRENTOIL",
            direction="long",
            signal_source="thesis_driven",
            pnl_usd=100.0,
            roe_pct=8.5,
            holding_ms=3_600_000,
            trade_closed_at="2026-04-09T04:55:00Z",
            conviction_at_open=0.72,
            journal_entry_id="xyz:BRENTOIL-1",
            thesis_snapshot_path="data/thesis_snapshots/xyz_brentoil_20260409.json",
            now_iso="2026-04-09T05:00:00Z",
        )
        defaults.update(overrides)
        return engine.parse_lesson_response(**defaults)

    def test_valid_response_parses(self):
        engine = LessonEngine()
        lesson = self._call(engine, _valid_response())
        assert lesson.lesson_type == "entry_timing"
        assert "BRENTOIL long on EIA draw" in lesson.summary
        assert lesson.tags == ["supply-disruption", "eia-confirmed"]
        assert lesson.outcome == "win"
        assert lesson.market == "xyz:BRENTOIL"
        assert lesson.direction == "long"
        assert lesson.created_at == "2026-04-09T05:00:00Z"

    def test_loss_outcome_is_classified(self):
        engine = LessonEngine()
        lesson = self._call(engine, _valid_response(), pnl_usd=-50.0, roe_pct=-4.0)
        assert lesson.outcome == "loss"

    def test_breakeven_outcome_is_classified(self):
        engine = LessonEngine()
        lesson = self._call(engine, _valid_response(), pnl_usd=1.0, roe_pct=0.1)
        assert lesson.outcome == "breakeven"

    def test_missing_summary_sentinel_raises(self):
        engine = LessonEngine()
        bad = _valid_response().replace("<<<LESSON_SUMMARY>>>", "")
        with pytest.raises(ValueError, match="missing summary sentinel"):
            self._call(engine, bad)

    def test_missing_type_sentinel_raises(self):
        engine = LessonEngine()
        bad = _valid_response().replace("<<<END_LESSON_TYPE>>>", "")
        with pytest.raises(ValueError, match="missing lesson_type sentinel"):
            self._call(engine, bad)

    def test_invalid_lesson_type_raises(self):
        engine = LessonEngine()
        bad = _valid_response(lesson_type="made_up_type")
        with pytest.raises(ValueError, match="lesson_type must be one of"):
            self._call(engine, bad)

    def test_invalid_direction_raises(self):
        engine = LessonEngine()
        with pytest.raises(ValueError, match="direction must be one of"):
            self._call(engine, _valid_response(), direction="diagonal")

    def test_empty_summary_raises(self):
        engine = LessonEngine()
        bad = _valid_response(summary="   ")
        with pytest.raises(ValueError, match="summary sentinel block was empty"):
            self._call(engine, bad)

    def test_tags_are_deduped_and_capped(self):
        engine = LessonEngine()
        tags = ", ".join(f"tag{i}" for i in range(15)) + ", tag0, tag1"  # duplicates at end
        response = _valid_response(tags=tags)
        lesson = self._call(engine, response)
        assert len(lesson.tags) == 8  # cap
        assert len(set(lesson.tags)) == 8  # dedupe
        assert lesson.tags[0] == "tag0"

    def test_tags_are_lowercased(self):
        engine = LessonEngine()
        response = _valid_response(tags="Supply-Disruption, EIA-CONFIRMED")
        lesson = self._call(engine, response)
        assert lesson.tags == ["supply-disruption", "eia-confirmed"]

    def test_empty_tags_is_empty_list(self):
        engine = LessonEngine()
        response = _valid_response(tags="")
        lesson = self._call(engine, response)
        assert lesson.tags == []

    def test_body_full_strips_sentinels(self):
        engine = LessonEngine()
        lesson = self._call(engine, _valid_response())
        for tag in (
            "<<<LESSON_SUMMARY>>>",
            "<<<END_LESSON_SUMMARY>>>",
            "<<<LESSON_TAGS>>>",
            "<<<END_LESSON_TAGS>>>",
            "<<<LESSON_TYPE>>>",
            "<<<END_LESSON_TYPE>>>",
        ):
            assert tag not in lesson.body_full
        # The analysis content from extra_body must still be present.
        assert "what happened" in lesson.body_full

    def test_body_full_safety_net_appends_verbatim_context(self):
        """If the agent forgot to copy the context block, the parser appends it."""
        engine = LessonEngine()
        req = LessonAuthorRequest(
            journal_entry={"instrument": "BTC", "direction": "long"},
            news_context_at_open="EIA draw Wednesday 10:30",
        )
        # Response has no trace of the context block
        response = _valid_response(extra_body="(no context copied here)")
        lesson = engine.parse_lesson_response(
            response_text=response,
            request=req,
            market="BTC",
            direction="long",
            signal_source="manual",
            pnl_usd=50.0,
            roe_pct=5.0,
            holding_ms=1_800_000,
            trade_closed_at="2026-04-09T04:55:00Z",
        )
        assert "Verbatim source context (auto-attached)" in lesson.body_full
        assert "EIA draw Wednesday 10:30" in lesson.body_full

    def test_body_full_no_duplication_when_agent_copied_context(self):
        engine = LessonEngine()
        req = LessonAuthorRequest(
            journal_entry={"instrument": "BTC", "direction": "long"},
            news_context_at_open="EIA draw Wednesday 10:30",
        )
        context = req.assemble_context_block()
        response = _valid_response(extra_body=f"## Analysis\n\n(a) happened.\n\n## Verbatim source context\n\n{context}")
        lesson = engine.parse_lesson_response(
            response_text=response,
            request=req,
            market="BTC",
            direction="long",
            signal_source="manual",
            pnl_usd=50.0,
            roe_pct=5.0,
            holding_ms=1_800_000,
            trade_closed_at="2026-04-09T04:55:00Z",
        )
        # Context should appear exactly once, no auto-attached duplicate
        assert "Verbatim source context (auto-attached)" not in lesson.body_full
        assert lesson.body_full.count("EIA draw Wednesday 10:30") == 1

    def test_lesson_type_is_lowercased_and_stripped(self):
        engine = LessonEngine()
        response = _valid_response(lesson_type="  Entry_Timing  ")
        lesson = self._call(engine, response)
        assert lesson.lesson_type == "entry_timing"

    def test_reviewed_by_chris_defaults_to_zero(self):
        engine = LessonEngine()
        lesson = self._call(engine, _valid_response())
        assert lesson.reviewed_by_chris == 0


class TestNowIso:
    def test_now_iso_format(self):
        iso = LessonEngine.now_iso()
        # "YYYY-MM-DDTHH:MM:SSZ"
        assert len(iso) == 20
        assert iso[4] == "-"
        assert iso[10] == "T"
        assert iso.endswith("Z")
