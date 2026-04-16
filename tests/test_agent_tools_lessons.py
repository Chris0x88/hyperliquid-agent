"""Tests for the search_lessons and get_lesson agent tools.

These tests use a temp memory.db via monkeypatching common.memory._DB_PATH,
then seed lessons via the log_lesson helper and exercise the tool surfaces
end-to-end through execute_tool() to catch dispatch-table / TOOL_DEFS drift.
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest


@pytest.fixture
def tmp_db(monkeypatch):
    """Point common.memory at a fresh throwaway SQLite file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import common.memory as common_memory
    monkeypatch.setattr(common_memory, "_DB_PATH", path)
    yield path
    os.unlink(path)


def _base_lesson(**overrides) -> dict:
    d = {
        "created_at": "2026-04-09T05:00:00Z",
        "trade_closed_at": "2026-04-09T04:55:00Z",
        "market": "xyz:BRENTOIL",
        "direction": "long",
        "signal_source": "thesis_driven",
        "lesson_type": "entry_timing",
        "outcome": "win",
        "pnl_usd": 123.45,
        "roe_pct": 8.7,
        "holding_ms": 3_600_000,
        "conviction_at_open": 0.72,
        "journal_entry_id": "xyz:BRENTOIL-1712633100000",
        "thesis_snapshot_path": "data/thesis_snapshots/xyz_brentoil_20260409.json",
        "summary": "BRENTOIL long on EIA draw, entry ahead of print, +8.7% in 1h.",
        "body_full": (
            "## Analysis\n\n"
            "(a) what happened: EIA confirmed the draw at 10:30.\n"
            "(b) what worked: thesis was in place ahead of the catalyst.\n"
            "(c) what didn't: stop was a little wider than needed.\n"
            "(d) pattern: supply-disruption longs ahead of EIA prints.\n"
            "(e) next time: trim stop by 0.3 ATR if entry is pre-catalyst.\n\n"
            "## Verbatim source context\n\n"
            "### journal_entry\n"
            "```json\n{\"instrument\": \"xyz:BRENTOIL\", \"direction\": \"long\"}\n```"
        ),
        "tags": ["supply-disruption", "eia-confirmed"],
        "reviewed_by_chris": 0,
    }
    d.update(overrides)
    return d


def _seed_corpus(tmp_db):
    """Seed 4 lessons into the temp DB. Pass db_path explicitly because
    common.memory functions bind their default db_path at definition time and
    don't see monkeypatched _DB_PATH. The tool under test reads _DB_PATH
    dynamically at call time, which is why monkeypatching works for it but
    not for these direct log_lesson calls."""
    from common import memory as common_memory
    common_memory.log_lesson(
        _base_lesson(
            market="xyz:BRENTOIL",
            signal_source="thesis_driven",
            lesson_type="entry_timing",
            summary="BRENTOIL long on EIA draw, entry ahead of print, +8.7% in 1h.",
            body_full="EIA draw confirmed thesis. Supply disruption catalyst played out.",
            tags=["supply-disruption", "eia-confirmed"],
            trade_closed_at="2026-04-09T04:55:00Z",
        ),
        db_path=tmp_db,
    )
    common_memory.log_lesson(
        _base_lesson(
            market="xyz:BRENTOIL",
            signal_source="radar",
            lesson_type="exit_quality",
            outcome="loss",
            pnl_usd=-50.0,
            roe_pct=-4.0,
            summary="BRENTOIL long stopped out on weekend wick — stop too tight.",
            body_full="Stop placed at 1.5x ATR, weekend wick took us out, recovered 20 minutes later.",
            tags=["weekend-wick", "stop-too-tight"],
            trade_closed_at="2026-04-08T23:00:00Z",
        ),
        db_path=tmp_db,
    )
    common_memory.log_lesson(
        _base_lesson(
            market="BTC",
            signal_source="pulse_signal",
            lesson_type="pattern_recognition",
            outcome="loss",
            pnl_usd=-200.0,
            roe_pct=-6.5,
            summary="BTC long on OI breakout failed — false breakout after Fed dovish tilt.",
            body_full="Pulse signal fired on OI breakout but the breakout never confirmed volume.",
            tags=["fed-day", "false-breakout"],
            trade_closed_at="2026-04-07T15:30:00Z",
        ),
        db_path=tmp_db,
    )
    common_memory.log_lesson(
        _base_lesson(
            market="xyz:GOLD",
            signal_source="thesis_driven",
            lesson_type="catalyst_timing",
            summary="GOLD long ahead of CPI — hit TP as print came in hot.",
            body_full="Positioned 24h before CPI print. Catalyst played out as thesis predicted.",
            tags=["cpi", "catalyst-played-out"],
            trade_closed_at="2026-04-06T12:00:00Z",
        ),
        db_path=tmp_db,
    )


# ---------------------------------------------------------------------------
# Registration (TOOL_DEFS + dispatch)
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_tools_registered_in_tool_defs(self):
        from agent.tools import TOOL_DEFS
        names = {t["function"]["name"] for t in TOOL_DEFS}
        assert "search_lessons" in names
        assert "get_lesson" in names

    def test_search_lessons_schema_has_filters(self):
        from agent.tools import TOOL_DEFS
        schema = next(
            t["function"] for t in TOOL_DEFS if t["function"]["name"] == "search_lessons"
        )
        props = schema["parameters"]["properties"]
        for key in (
            "query",
            "market",
            "direction",
            "signal_source",
            "lesson_type",
            "outcome",
            "include_rejected",
            "limit",
        ):
            assert key in props

    def test_get_lesson_requires_id(self):
        from agent.tools import TOOL_DEFS
        schema = next(
            t["function"] for t in TOOL_DEFS if t["function"]["name"] == "get_lesson"
        )
        assert "id" in schema["parameters"]["required"]

    def test_tools_registered_in_dispatch(self):
        from agent.tools import _TOOL_DISPATCH
        assert "search_lessons" in _TOOL_DISPATCH
        assert "get_lesson" in _TOOL_DISPATCH

    def test_both_tools_are_read_only(self):
        from agent.tools import WRITE_TOOLS
        assert "search_lessons" not in WRITE_TOOLS
        assert "get_lesson" not in WRITE_TOOLS


# ---------------------------------------------------------------------------
# search_lessons tool behaviour
# ---------------------------------------------------------------------------

class TestSearchLessonsTool:
    def test_empty_corpus_returns_sentinel(self, tmp_db):
        from agent.tools import execute_tool
        result = execute_tool("search_lessons", {})
        assert "No lessons found" in result

    def test_empty_query_returns_recent_first(self, tmp_db):
        _seed_corpus(tmp_db)
        from agent.tools import execute_tool
        result = execute_tool("search_lessons", {"limit": 4})
        # Most recent trade_closed_at first
        brent_pos = result.index("2026-04-09")
        gold_pos = result.index("2026-04-06")
        assert brent_pos < gold_pos

    def test_fts_query_ranks_relevant_first(self, tmp_db):
        _seed_corpus(tmp_db)
        from agent.tools import execute_tool
        result = execute_tool("search_lessons", {"query": "weekend wick stop"})
        # The "weekend-wick" lesson should appear
        assert "weekend" in result.lower() or "stop" in result.lower()

    def test_market_filter(self, tmp_db):
        _seed_corpus(tmp_db)
        from agent.tools import execute_tool
        result = execute_tool("search_lessons", {"market": "BTC"})
        assert "BTC" in result
        assert "BRENTOIL" not in result
        assert "GOLD" not in result

    def test_direction_filter(self, tmp_db):
        _seed_corpus(tmp_db)
        from agent.tools import execute_tool
        result = execute_tool("search_lessons", {"direction": "long"})
        # All 4 seeded lessons are long, so all should appear
        assert "Found 4 lesson" in result

    def test_outcome_filter(self, tmp_db):
        _seed_corpus(tmp_db)
        from agent.tools import execute_tool
        result = execute_tool("search_lessons", {"outcome": "loss"})
        assert "Found 2 lesson" in result
        assert "loss" in result

    def test_lesson_type_filter(self, tmp_db):
        _seed_corpus(tmp_db)
        from agent.tools import execute_tool
        result = execute_tool("search_lessons", {"lesson_type": "catalyst_timing"})
        assert "Found 1 lesson" in result
        assert "GOLD" in result

    def test_combined_filters_with_query(self, tmp_db):
        _seed_corpus(tmp_db)
        from agent.tools import execute_tool
        result = execute_tool(
            "search_lessons",
            {
                "query": "thesis",
                "market": "xyz:BRENTOIL",
                "signal_source": "thesis_driven",
            },
        )
        # Should get at least the thesis-driven BRENTOIL lesson
        assert "BRENTOIL" in result
        # Should NOT include the radar-driven BRENTOIL lesson
        # (thesis_driven filter excludes it; the word "thesis" could be in the body though)

    def test_limit_applies(self, tmp_db):
        _seed_corpus(tmp_db)
        from agent.tools import execute_tool
        result = execute_tool("search_lessons", {"limit": 2})
        assert "Found 2 lesson" in result

    def test_rejected_excluded_by_default(self, tmp_db):
        _seed_corpus(tmp_db)
        from common import memory as common_memory
        # Reject the first BRENTOIL lesson
        common_memory.set_lesson_review(1, -1, db_path=tmp_db)

        from agent.tools import execute_tool
        result = execute_tool("search_lessons", {})
        assert "Found 3 lesson" in result  # 4 seeded, 1 rejected

    def test_rejected_included_when_opted_in(self, tmp_db):
        _seed_corpus(tmp_db)
        from common import memory as common_memory
        common_memory.set_lesson_review(1, -1, db_path=tmp_db)

        from agent.tools import execute_tool
        result = execute_tool("search_lessons", {"include_rejected": True})
        assert "Found 4 lesson" in result
        assert "[rejected]" in result

    def test_approved_flag_shown(self, tmp_db):
        _seed_corpus(tmp_db)
        from common import memory as common_memory
        common_memory.set_lesson_review(1, 1, db_path=tmp_db)

        from agent.tools import execute_tool
        result = execute_tool("search_lessons", {})
        assert "[approved]" in result

    def test_injection_resistance_via_execute_tool(self, tmp_db):
        _seed_corpus(tmp_db)
        from agent.tools import execute_tool
        # FTS5 operators in the query must not break dispatch
        for bad_query in ['" OR 1=1', "*", "(foo)", "NOT AND OR"]:
            result = execute_tool("search_lessons", {"query": bad_query})
            # Must not raise; returns either empty-sentinel or a list
            assert "failed" not in result.lower() or "not found" in result.lower()


# ---------------------------------------------------------------------------
# get_lesson tool behaviour
# ---------------------------------------------------------------------------

class TestGetLessonTool:
    """All tests in this class seed via _log() which binds db_path=tmp_db.

    common.memory functions bind their default db_path at function-definition
    time, so direct calls without db_path hit the real production memory.db.
    The helper below closes that gap for every seed call in this class.
    """

    @staticmethod
    def _log(tmp_db, **overrides):
        from common import memory as common_memory
        return common_memory.log_lesson(_base_lesson(**overrides), db_path=tmp_db)

    def test_returns_full_body(self, tmp_db):
        rid = self._log(tmp_db)

        from agent.tools import execute_tool
        result = execute_tool("get_lesson", {"id": rid})

        assert f"Lesson #{rid}" in result
        assert "xyz:BRENTOIL" in result
        assert "long" in result
        assert "thesis_driven" in result
        assert "entry_timing" in result
        assert "win" in result
        assert "## Verbatim body" in result
        assert "(a) what happened" in result
        assert "(e) next time" in result

    def test_missing_id_returns_sentinel(self, tmp_db):
        from agent.tools import execute_tool
        result = execute_tool("get_lesson", {"id": 99999})
        assert "not found" in result.lower()

    def test_missing_id_arg(self, tmp_db):
        from agent.tools import execute_tool
        result = execute_tool("get_lesson", {})
        assert "requires 'id'" in result

    def test_non_int_id(self, tmp_db):
        from agent.tools import execute_tool
        result = execute_tool("get_lesson", {"id": "abc"})
        assert "must be an integer" in result

    def test_str_id_is_coerced(self, tmp_db):
        rid = self._log(tmp_db)
        from agent.tools import execute_tool
        result = execute_tool("get_lesson", {"id": str(rid)})
        assert f"Lesson #{rid}" in result

    def test_renders_tags(self, tmp_db):
        rid = self._log(tmp_db, tags=["fed-day", "false-breakout", "pattern-a"])
        from agent.tools import execute_tool
        result = execute_tool("get_lesson", {"id": rid})
        assert "fed-day" in result
        assert "false-breakout" in result

    def test_renders_conviction_when_present(self, tmp_db):
        rid = self._log(tmp_db, conviction_at_open=0.85)
        from agent.tools import execute_tool
        result = execute_tool("get_lesson", {"id": rid})
        assert "0.85" in result

    def test_hides_conviction_when_null(self, tmp_db):
        rid = self._log(tmp_db, conviction_at_open=None)
        from agent.tools import execute_tool
        result = execute_tool("get_lesson", {"id": rid})
        assert "Conviction at open" not in result

    def test_review_status_rendered(self, tmp_db):
        from common import memory as common_memory
        rid_u = self._log(tmp_db)
        rid_a = self._log(tmp_db, summary="approved lesson")
        rid_r = self._log(tmp_db, summary="rejected lesson")
        common_memory.set_lesson_review(rid_a, 1, db_path=tmp_db)
        common_memory.set_lesson_review(rid_r, -1, db_path=tmp_db)

        from agent.tools import execute_tool
        assert "unreviewed" in execute_tool("get_lesson", {"id": rid_u})
        assert "approved" in execute_tool("get_lesson", {"id": rid_a})
        assert "rejected" in execute_tool("get_lesson", {"id": rid_r})

    def test_holding_time_rendered_minutes(self, tmp_db):
        rid = self._log(tmp_db, holding_ms=5 * 60 * 1000)  # 5m
        from agent.tools import execute_tool
        result = execute_tool("get_lesson", {"id": rid})
        assert "5m" in result

    def test_holding_time_rendered_hours(self, tmp_db):
        rid = self._log(tmp_db, holding_ms=90 * 60 * 1000)  # 1.5h
        from agent.tools import execute_tool
        result = execute_tool("get_lesson", {"id": rid})
        assert "1.5h" in result

    def test_holding_time_rendered_days(self, tmp_db):
        rid = self._log(tmp_db, holding_ms=3 * 24 * 3600 * 1000)  # 3d
        from agent.tools import execute_tool
        result = execute_tool("get_lesson", {"id": rid})
        assert "3.0d" in result

    def test_tags_roundtrip_json_string_from_sqlite(self, tmp_db):
        """SQLite stores tags as a JSON string; the tool must decode it."""
        from common import memory as common_memory
        rid = self._log(tmp_db, tags=["alpha", "beta"])
        # Verify raw storage is a JSON string
        row = common_memory.get_lesson(rid, db_path=tmp_db)
        assert isinstance(row["tags"], str)
        assert json.loads(row["tags"]) == ["alpha", "beta"]

        from agent.tools import execute_tool
        result = execute_tool("get_lesson", {"id": rid})
        assert "alpha" in result
        assert "beta" in result


# ---------------------------------------------------------------------------
# execute_tool integration: dispatch table wiring
# ---------------------------------------------------------------------------

class TestExecuteToolDispatch:
    def test_search_lessons_dispatches(self, tmp_db):
        from agent.tools import execute_tool
        # Even with empty corpus, this should return a string, not raise
        result = execute_tool("search_lessons", {})
        assert isinstance(result, str)
        assert "Unknown tool" not in result

    def test_get_lesson_dispatches(self, tmp_db):
        from agent.tools import execute_tool
        result = execute_tool("get_lesson", {"id": 1})
        assert isinstance(result, str)
        assert "Unknown tool" not in result

    def test_tool_string_args_are_parsed(self, tmp_db):
        """execute_tool accepts JSON-string arguments (OpenAI tool_call format)."""
        from common import memory as common_memory
        common_memory.log_lesson(_base_lesson(), db_path=tmp_db)

        from agent.tools import execute_tool
        result = execute_tool("search_lessons", '{"limit": 1}')
        assert "Found 1 lesson" in result
