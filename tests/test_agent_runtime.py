"""Tests for cli/agent_runtime.py — the core agent runtime."""
import json
import os
import tempfile
import time
from pathlib import Path

import pytest


class TestBuildSystemPrompt:
    def test_assembles_core_prompt(self):
        from cli.agent_runtime import build_system_prompt
        prompt = build_system_prompt()
        assert "autonomous" in prompt.lower()
        assert "agent" in prompt.lower()

    def test_includes_agent_md(self):
        from cli.agent_runtime import build_system_prompt
        prompt = build_system_prompt(agent_md="CUSTOM_AGENT_INSTRUCTION")
        assert "CUSTOM_AGENT_INSTRUCTION" in prompt

    def test_includes_memory(self):
        from cli.agent_runtime import build_system_prompt
        prompt = build_system_prompt(memory_content="Remember: Chris likes ATR stops")
        assert "Remember: Chris likes ATR stops" in prompt
        assert "AGENT MEMORY" in prompt

    def test_includes_live_context(self):
        from cli.agent_runtime import build_system_prompt
        prompt = build_system_prompt(live_context="--- LIVE CONTEXT ---\nequity=$500")
        assert "equity=$500" in prompt

    def test_includes_lessons_section(self):
        from cli.agent_runtime import build_system_prompt
        section = "## RECENT RELEVANT LESSONS\n\n- #1 test lesson summary"
        prompt = build_system_prompt(lessons_section=section)
        assert "RECENT RELEVANT LESSONS" in prompt
        assert "#1 test lesson summary" in prompt

    def test_empty_lessons_section_is_skipped(self):
        from cli.agent_runtime import build_system_prompt
        prompt = build_system_prompt(lessons_section="")
        assert "RECENT RELEVANT LESSONS" not in prompt

    def test_lessons_between_memory_and_live_context(self):
        """Section ordering: memory → lessons → live_context."""
        from cli.agent_runtime import build_system_prompt
        prompt = build_system_prompt(
            memory_content="MEMORY_MARKER",
            lessons_section="LESSONS_MARKER",
            live_context="LIVE_MARKER",
        )
        assert prompt.index("MEMORY_MARKER") < prompt.index("LESSONS_MARKER") < prompt.index("LIVE_MARKER")


# ---------------------------------------------------------------------------
# build_lessons_section — pulls the top lessons from data/memory/memory.db
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_lessons_db(monkeypatch):
    """Point common.memory at a throwaway SQLite file for lesson injection tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import common.memory as common_memory
    monkeypatch.setattr(common_memory, "_DB_PATH", path)
    yield path
    os.unlink(path)


def _seed_lesson(**overrides):
    """Seed one lesson into whatever _DB_PATH is monkeypatched to."""
    from common import memory as common_memory
    base = {
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
        "thesis_snapshot_path": None,
        "summary": "BRENTOIL long on EIA draw, entry ahead of print, +8.7% in 1h.",
        "body_full": "verbatim body",
        "tags": ["supply-disruption"],
        "reviewed_by_chris": 0,
    }
    base.update(overrides)
    return common_memory.log_lesson(base)


class TestBuildLessonsSection:
    def test_empty_corpus_returns_empty_string(self, tmp_lessons_db):
        from cli.agent_runtime import build_lessons_section
        assert build_lessons_section() == ""

    def test_hits_formatted_as_markdown_section(self, tmp_lessons_db):
        _seed_lesson()
        from cli.agent_runtime import build_lessons_section
        out = build_lessons_section()
        assert out.startswith("## RECENT RELEVANT LESSONS")
        assert "get_lesson(id)" in out
        assert "#1" in out
        assert "xyz:BRENTOIL" in out
        assert "long" in out
        assert "thesis_driven" in out
        assert "win" in out
        assert "+8.7%" in out
        assert "BRENTOIL long on EIA draw" in out

    def test_recency_ordering_on_empty_query(self, tmp_lessons_db):
        _seed_lesson(summary="first", trade_closed_at="2026-04-09T12:00:00Z")
        _seed_lesson(summary="second", trade_closed_at="2026-04-08T12:00:00Z")
        _seed_lesson(summary="third", trade_closed_at="2026-04-07T12:00:00Z")
        from cli.agent_runtime import build_lessons_section
        out = build_lessons_section(limit=3)
        assert out.index("first") < out.index("second") < out.index("third")

    def test_limit_applied(self, tmp_lessons_db):
        for i in range(10):
            _seed_lesson(
                summary=f"lesson number {i}",
                trade_closed_at=f"2026-04-0{i % 9 + 1}T12:00:00Z",
            )
        from cli.agent_runtime import build_lessons_section
        out = build_lessons_section(limit=3)
        assert out.count("\n- #") == 3

    def test_bm25_query_ranks_relevant_first(self, tmp_lessons_db):
        _seed_lesson(
            summary="BRENTOIL weekend wick stopped us out",
            body_full="Weekend wick took the stop, price recovered 20 minutes later.",
            tags=["weekend-wick", "stop-too-tight"],
            trade_closed_at="2026-04-08T00:00:00Z",
        )
        _seed_lesson(
            summary="GOLD CPI catalyst played out",
            body_full="Positioned 24h before CPI. Thesis confirmed.",
            tags=["cpi"],
            market="xyz:GOLD",
            trade_closed_at="2026-04-07T12:00:00Z",
        )
        from cli.agent_runtime import build_lessons_section
        out = build_lessons_section(query="weekend wick")
        # BM25 MATCH filters to rows that contain the query terms — only the
        # weekend-wick lesson should appear. CPI lesson is filtered out.
        assert "weekend wick stopped" in out
        assert "CPI catalyst" not in out

    def test_market_filter(self, tmp_lessons_db):
        _seed_lesson(market="xyz:BRENTOIL", summary="brent lesson")
        _seed_lesson(market="BTC", summary="btc lesson")
        from cli.agent_runtime import build_lessons_section
        out = build_lessons_section(market="BTC")
        assert "btc lesson" in out
        assert "brent lesson" not in out

    def test_direction_filter(self, tmp_lessons_db):
        _seed_lesson(direction="long", summary="long lesson")
        _seed_lesson(direction="short", summary="short lesson")
        from cli.agent_runtime import build_lessons_section
        out = build_lessons_section(direction="short")
        assert "short lesson" in out
        assert "long lesson" not in out

    def test_signal_source_filter(self, tmp_lessons_db):
        _seed_lesson(signal_source="radar", summary="radar lesson")
        _seed_lesson(signal_source="thesis_driven", summary="thesis lesson")
        from cli.agent_runtime import build_lessons_section
        out = build_lessons_section(signal_source="radar")
        assert "radar lesson" in out
        assert "thesis lesson" not in out

    def test_lesson_type_filter(self, tmp_lessons_db):
        _seed_lesson(lesson_type="exit_quality", summary="exit lesson")
        _seed_lesson(lesson_type="entry_timing", summary="entry lesson")
        from cli.agent_runtime import build_lessons_section
        out = build_lessons_section(lesson_type="exit_quality")
        assert "exit lesson" in out
        assert "entry lesson" not in out

    def test_approved_flagged(self, tmp_lessons_db):
        from common import memory as common_memory
        rid = _seed_lesson(summary="approved lesson")
        common_memory.set_lesson_review(rid, 1)
        from cli.agent_runtime import build_lessons_section
        assert "[approved]" in build_lessons_section()

    def test_rejected_excluded(self, tmp_lessons_db):
        from common import memory as common_memory
        rid = _seed_lesson(summary="rejected lesson")
        common_memory.set_lesson_review(rid, -1)
        from cli.agent_runtime import build_lessons_section
        assert "rejected lesson" not in build_lessons_section()

    def test_disabled_flag_returns_empty(self, tmp_lessons_db, monkeypatch):
        _seed_lesson()
        import cli.agent_runtime as agent_runtime
        monkeypatch.setattr(agent_runtime, "_LESSON_INJECTION_ENABLED", False)
        assert agent_runtime.build_lessons_section() == ""

    def test_db_error_swallowed(self, tmp_lessons_db, monkeypatch):
        """If search_lessons raises, section returns '' — agent must not break."""
        def boom(*a, **kw):
            raise RuntimeError("simulated db failure")
        import common.memory as common_memory
        monkeypatch.setattr(common_memory, "search_lessons", boom)
        from cli.agent_runtime import build_lessons_section
        assert build_lessons_section() == ""

    def test_section_is_compact(self, tmp_lessons_db):
        """~150 token cap discipline proxy: 5 entries under ~1500 chars."""
        for i in range(5):
            _seed_lesson(
                summary=f"lesson {i} summary",
                trade_closed_at=f"2026-04-0{i + 1}T12:00:00Z",
            )
        from cli.agent_runtime import build_lessons_section
        out = build_lessons_section(limit=5)
        assert len(out) < 1500, f"lessons section is {len(out)} chars, expected <1500"


class TestParallelToolExecution:
    def test_concurrent_read_tools(self):
        """READ tools should run in parallel (all complete, order preserved)."""
        from cli.agent_runtime import execute_tools_parallel

        call_order = []
        def mock_execute(name, args):
            call_order.append(name)
            return f"result_{name}"

        tool_calls = [
            {"id": "1", "function": {"name": "market_brief", "arguments": '{"market": "BTC"}'}},
            {"id": "2", "function": {"name": "live_price", "arguments": '{"market": "all"}'}},
            {"id": "3", "function": {"name": "check_funding", "arguments": '{"coin": "BTC"}'}},
        ]

        results = execute_tools_parallel(tool_calls, mock_execute)
        assert len(results) == 3
        assert results[0] == ("1", "market_brief", "result_market_brief")
        assert results[1] == ("2", "live_price", "result_live_price")
        assert results[2] == ("3", "check_funding", "result_check_funding")

    def test_write_tool_blocks_queue(self):
        """WRITE tools should run sequentially (blocking)."""
        from cli.agent_runtime import execute_tools_parallel

        results_order = []
        def mock_execute(name, args):
            results_order.append(name)
            return f"result_{name}"

        tool_calls = [
            {"id": "1", "function": {"name": "read_file", "arguments": '{"path": "test.py"}'}},
            {"id": "2", "function": {"name": "edit_file", "arguments": '{"path": "x", "old_str": "a", "new_str": "b"}'}},
            {"id": "3", "function": {"name": "read_file", "arguments": '{"path": "other.py"}'}},
        ]

        results = execute_tools_parallel(tool_calls, mock_execute)
        assert len(results) == 3
        # edit_file should have run in its own batch (sequential)
        # Results should be in order regardless
        assert results[0][1] == "read_file"
        assert results[1][1] == "edit_file"
        assert results[2][1] == "read_file"

    def test_empty_tool_calls(self):
        from cli.agent_runtime import execute_tools_parallel
        results = execute_tools_parallel([], lambda n, a: "")
        assert results == []


class TestSSEParsing:
    def test_parse_text_delta(self):
        from cli.agent_runtime import parse_sse_line
        line = 'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}}'
        event = parse_sse_line(line)
        assert event is not None
        assert event.event_type == "content_block_delta"
        assert event.data["delta"]["text"] == "Hello"

    def test_parse_done(self):
        from cli.agent_runtime import parse_sse_line
        event = parse_sse_line("data: [DONE]")
        assert event is not None
        assert event.event_type == "done"

    def test_parse_empty_line(self):
        from cli.agent_runtime import parse_sse_line
        assert parse_sse_line("") is None
        assert parse_sse_line("  ") is None
        assert parse_sse_line(": comment") is None

    def test_parse_invalid_json(self):
        from cli.agent_runtime import parse_sse_line
        assert parse_sse_line("data: {invalid}") is None


class TestStreamResult:
    def test_defaults(self):
        from cli.agent_runtime import StreamResult
        r = StreamResult()
        assert r.text == ""
        assert r.tool_calls == []
        assert r.thinking == ""
        assert r.stop_reason == ""


class TestContextCompaction:
    def test_short_conversation_no_compact(self):
        from cli.agent_runtime import should_compact
        messages = [{"role": "user", "content": "hello"}]
        assert should_compact(messages, "opus") is False

    def test_long_conversation_triggers_compact(self):
        from cli.agent_runtime import should_compact
        # Create messages that exceed the threshold
        big_content = "x" * 800_000  # ~200K tokens, exceeds any model
        messages = [{"role": "user", "content": big_content}]
        assert should_compact(messages, "opus") is True

    def test_context_window_varies_by_model(self):
        from cli.agent_runtime import get_context_window
        assert get_context_window("claude-opus-4-6") == 200_000
        assert get_context_window("some-random-model") == 128_000


class TestDream:
    def test_should_dream_no_lock(self, tmp_path, monkeypatch):
        """Without a lock file and no history, dream should return False."""
        from cli import agent_runtime
        monkeypatch.setattr(agent_runtime, "_MEMORY_DIR", tmp_path)
        monkeypatch.setattr(agent_runtime, "_DREAM_LOCK", tmp_path / ".last_dream")
        monkeypatch.setattr(agent_runtime, "_PROJECT_ROOT", tmp_path)
        # No lock file and no history file → False
        assert agent_runtime.should_dream() is False

    def test_mark_dream_complete(self, tmp_path, monkeypatch):
        from cli import agent_runtime
        monkeypatch.setattr(agent_runtime, "_MEMORY_DIR", tmp_path)
        monkeypatch.setattr(agent_runtime, "_DREAM_LOCK", tmp_path / ".last_dream")
        agent_runtime.mark_dream_complete()
        assert (tmp_path / ".last_dream").exists()


class TestConcurrentSafeTools:
    def test_read_tools_are_safe(self):
        from cli.agent_runtime import CONCURRENT_SAFE_TOOLS
        safe_reads = ["market_brief", "account_summary", "live_price", "read_file", "search_code", "web_search", "memory_read"]
        for tool in safe_reads:
            assert tool in CONCURRENT_SAFE_TOOLS, f"{tool} should be concurrent-safe"

    def test_write_tools_not_safe(self):
        from cli.agent_runtime import CONCURRENT_SAFE_TOOLS
        writes = ["edit_file", "run_bash", "memory_write", "place_trade"]
        for tool in writes:
            assert tool not in CONCURRENT_SAFE_TOOLS, f"{tool} should NOT be concurrent-safe"
