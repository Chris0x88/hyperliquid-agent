"""Tests for NORTH_STAR P10 / MASTER_PLAN Critical Rule 11 bounds.

Pins the hard upper caps on agent-tool read paths so they can't regress
silently. Triggered by the 2026-04-09 audit (Agent E) which found that
`_tool_get_feedback` and `_tool_trade_journal` accepted unbounded
``limit`` arguments before this fix.

The principle: an agent that asks for ``limit=999999`` should get back
the same bounded result as if it had asked for ``limit=25`` — never a
gigabyte of context-window inflation.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# _tool_get_feedback
# ---------------------------------------------------------------------------


class TestGetFeedbackBounds:
    def test_default_limit_is_10(self):
        """No limit arg → default 10."""
        from cli.agent_tools import _tool_get_feedback

        fake = {"count": 5, "feedback": [
            {"time": "2026-04-09T00:00:00Z", "text": f"row {i}"} for i in range(5)
        ]}
        with patch("common.tools.get_feedback", return_value=fake) as mock:
            _tool_get_feedback({})
            mock.assert_called_once_with(10)

    def test_huge_limit_is_clamped_to_25(self):
        """limit=999999 → clamped to 25 before reaching the loader."""
        from cli.agent_tools import _tool_get_feedback

        fake = {"count": 0, "feedback": []}
        with patch("common.tools.get_feedback", return_value=fake) as mock:
            _tool_get_feedback({"limit": 999999})
            mock.assert_called_once_with(25)

    def test_negative_limit_clamped_to_one(self):
        from cli.agent_tools import _tool_get_feedback

        fake = {"count": 0, "feedback": []}
        with patch("common.tools.get_feedback", return_value=fake) as mock:
            _tool_get_feedback({"limit": -42})
            mock.assert_called_once_with(1)

    def test_invalid_limit_falls_back_to_default(self):
        from cli.agent_tools import _tool_get_feedback

        fake = {"count": 0, "feedback": []}
        with patch("common.tools.get_feedback", return_value=fake) as mock:
            _tool_get_feedback({"limit": "not a number"})
            mock.assert_called_once_with(10)

    def test_per_row_text_truncated_at_500_chars(self):
        """A pasted-article-sized feedback row gets truncated in the
        agent-facing rendering. The on-disk row stays full-length."""
        from cli.agent_tools import _tool_get_feedback

        long_text = "x" * 5000
        fake = {
            "count": 1,
            "feedback": [{"time": "2026-04-09T00:00:00Z", "text": long_text}],
        }
        with patch("common.tools.get_feedback", return_value=fake):
            result = _tool_get_feedback({})

        # The rendered output should not contain the full 5000 chars
        assert len(result) < 1500, f"rendered too long: {len(result)} chars"
        assert "..." in result, "truncation marker missing"

    def test_get_feedback_schema_clamps_limit(self):
        """The JSON schema in TOOL_DEFS should declare maximum=25 so the
        agent's tool-call validation rejects out-of-bounds calls before
        the function body even runs."""
        from cli.agent_tools import TOOL_DEFS

        feedback_def = next(
            d for d in TOOL_DEFS
            if d.get("function", {}).get("name") == "get_feedback"
        )
        params = feedback_def["function"]["parameters"]["properties"]["limit"]
        assert params["maximum"] == 25
        assert params["minimum"] == 1
        assert params["default"] == 10


# ---------------------------------------------------------------------------
# _tool_trade_journal
# ---------------------------------------------------------------------------


class TestTradeJournalBounds:
    def test_default_limit_is_10(self, tmp_path, monkeypatch):
        """Default limit returns at most 10 trades."""
        from cli import agent_tools
        monkeypatch.setattr(agent_tools, "_PROJECT_ROOT", tmp_path)

        # Plant 50 fake trades in journal.jsonl
        journal = tmp_path / "data" / "research" / "journal.jsonl"
        journal.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"trade_id": f"t-{i}", "instrument": "BTC", "direction": "long",
             "entry_price": 94000 + i, "exit_price": 94500 + i, "pnl": 500,
             "timestamp_close": f"2026-04-{i+1:02d}T00:00:00Z"}
            for i in range(50)
        ]
        journal.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

        result = agent_tools._tool_trade_journal({})
        # Default is 10, so the rendered "Last N trades:" header should say 10
        assert "Last 10 trades:" in result

    def test_huge_limit_is_clamped_to_25(self, tmp_path, monkeypatch):
        from cli import agent_tools
        monkeypatch.setattr(agent_tools, "_PROJECT_ROOT", tmp_path)

        journal = tmp_path / "data" / "research" / "journal.jsonl"
        journal.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"trade_id": f"t-{i}", "instrument": "BTC", "direction": "long",
             "entry_price": 94000 + i, "exit_price": 94500 + i, "pnl": 500,
             "timestamp_close": f"2026-04-{(i % 28)+1:02d}T00:00:00Z"}
            for i in range(100)
        ]
        journal.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

        result = agent_tools._tool_trade_journal({"limit": 999999})
        # Even though we asked for ~1M, we got at most 25
        assert "Last 25 trades:" in result

    def test_invalid_limit_falls_back_to_default(self, tmp_path, monkeypatch):
        from cli import agent_tools
        monkeypatch.setattr(agent_tools, "_PROJECT_ROOT", tmp_path)
        # No journal → tool should still respond gracefully without crashing
        result = agent_tools._tool_trade_journal({"limit": "garbage"})
        assert "No trade journal entries." in result

    def test_trade_journal_schema_clamps_limit(self):
        from cli.agent_tools import TOOL_DEFS

        tj_def = next(
            d for d in TOOL_DEFS
            if d.get("function", {}).get("name") == "trade_journal"
        )
        params = tj_def["function"]["parameters"]["properties"]["limit"]
        assert params["maximum"] == 25
        assert params["minimum"] == 1
        assert params["default"] == 10

    def test_streaming_tail_does_not_load_full_giant_journal(self, tmp_path, monkeypatch):
        """Even with a 10k-row journal, the deque tail-read keeps memory
        bounded — the test asserts the result still respects the limit
        and the deque-based tail logic doesn't blow up."""
        from cli import agent_tools
        monkeypatch.setattr(agent_tools, "_PROJECT_ROOT", tmp_path)

        journal = tmp_path / "data" / "research" / "journal.jsonl"
        journal.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"trade_id": f"t-{i}", "instrument": "BTC", "direction": "long",
             "entry_price": 94000 + (i % 100), "exit_price": 94500 + (i % 100),
             "pnl": 500,
             "timestamp_close": f"2026-04-{(i % 28)+1:02d}T00:00:00Z"}
            for i in range(10000)
        ]
        journal.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

        result = agent_tools._tool_trade_journal({"limit": 5})
        assert "Last 5 trades:" in result


# ---------------------------------------------------------------------------
# _tool_get_signals
# ---------------------------------------------------------------------------


class TestGetSignalsBounds:
    def test_default_limit_is_20(self, tmp_path, monkeypatch):
        from cli import agent_tools
        monkeypatch.setattr(agent_tools, "_PROJECT_ROOT", tmp_path)

        signals_path = tmp_path / "data" / "research" / "signals.jsonl"
        signals_path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"timestamp": f"2026-04-{(i%28)+1:02d}T00:00:00Z",
             "source": "pulse", "coin": "BTC", "score": 0.5}
            for i in range(50)
        ]
        signals_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

        result = agent_tools._tool_get_signals({})
        assert "Last 20 signals:" in result

    def test_huge_limit_clamped_to_50(self, tmp_path, monkeypatch):
        from cli import agent_tools
        monkeypatch.setattr(agent_tools, "_PROJECT_ROOT", tmp_path)

        signals_path = tmp_path / "data" / "research" / "signals.jsonl"
        signals_path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"timestamp": f"2026-04-{(i%28)+1:02d}T00:00:00Z",
             "source": "radar", "coin": "BRENTOIL", "score": 0.7}
            for i in range(200)
        ]
        signals_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

        result = agent_tools._tool_get_signals({"limit": 999999})
        assert "Last 50 signals:" in result

    def test_signals_schema_clamps(self):
        from cli.agent_tools import TOOL_DEFS
        sig_def = next(
            d for d in TOOL_DEFS
            if d.get("function", {}).get("name") == "get_signals"
        )
        params = sig_def["function"]["parameters"]["properties"]["limit"]
        assert params["maximum"] == 50
        assert params["minimum"] == 1


# ---------------------------------------------------------------------------
# _tool_search_lessons + _tool_get_lesson
# ---------------------------------------------------------------------------


class TestLessonToolBounds:
    def test_search_lessons_huge_limit_clamped_to_20(self):
        from cli.agent_tools import _tool_search_lessons
        from unittest.mock import patch

        captured = {}
        def fake_search(**kwargs):
            captured.update(kwargs)
            return []

        with patch("common.memory.search_lessons", side_effect=fake_search):
            _tool_search_lessons({"limit": 999999})

        assert captured["limit"] == 20

    def test_search_lessons_default_is_5(self):
        from cli.agent_tools import _tool_search_lessons
        from unittest.mock import patch

        captured = {}
        def fake_search(**kwargs):
            captured.update(kwargs)
            return []

        with patch("common.memory.search_lessons", side_effect=fake_search):
            _tool_search_lessons({})

        assert captured["limit"] == 5

    def test_search_lessons_schema_clamps(self):
        from cli.agent_tools import TOOL_DEFS
        sl_def = next(
            d for d in TOOL_DEFS
            if d.get("function", {}).get("name") == "search_lessons"
        )
        params = sl_def["function"]["parameters"]["properties"]["limit"]
        assert params["maximum"] == 20
        assert params["minimum"] == 1
        assert params["default"] == 5

    def test_get_lesson_body_truncated_at_6kb(self):
        """A bloated lesson body_full gets truncated before reaching the
        agent's tool result, so a single lesson can't consume the entire
        prompt budget."""
        from cli.agent_tools import _tool_get_lesson
        from unittest.mock import patch

        long_body = "x" * 20000  # 20KB body
        fake_row = {
            "id": 99,
            "trade_closed_at": "2026-04-09T00:00:00Z",
            "market": "BTC",
            "direction": "long",
            "signal_source": "thesis_driven",
            "lesson_type": "exit_quality",
            "outcome": "win",
            "pnl_usd": 100.0,
            "roe_pct": 1.5,
            "holding_ms": 3600000,
            "tags": "[]",
            "summary": "test",
            "body_full": long_body,
            "reviewed_by_chris": 0,
        }

        with patch("common.memory.get_lesson", return_value=fake_row):
            result = _tool_get_lesson({"id": 99})

        # Body should be truncated. Total result < 8KB (6KB body + ~1KB header).
        assert len(result) < 8500
        assert "TRUNCATED at 6KB cap" in result


# ---------------------------------------------------------------------------
# memory_read cap
# ---------------------------------------------------------------------------


class TestMemoryReadBounds:
    def test_memory_read_caps_oversized_index(self, tmp_path, monkeypatch):
        """A 100KB MEMORY.md (e.g. from a runaway dream cycle) gets
        truncated at 20KB before the agent sees it."""
        from common import tools as common_tools
        monkeypatch.setattr(common_tools, "_MEMORY_DIR", tmp_path)

        memory_md = tmp_path / "MEMORY.md"
        memory_md.write_text("y" * 100000)  # 100KB

        result = common_tools.memory_read("index")
        assert "content" in result
        assert len(result["content"]) <= 25000  # 20KB + truncation marker
        assert "TRUNCATED at 20KB cap" in result["content"]

    def test_memory_read_topic_cap(self, tmp_path, monkeypatch):
        from common import tools as common_tools
        monkeypatch.setattr(common_tools, "_MEMORY_DIR", tmp_path)

        topic_md = tmp_path / "feedback.md"
        topic_md.write_text("z" * 50000)

        result = common_tools.memory_read("feedback")
        assert "content" in result
        assert len(result["content"]) <= 25000
        assert "TRUNCATED at 20KB cap" in result["content"]

    def test_memory_read_small_file_unchanged(self, tmp_path, monkeypatch):
        from common import tools as common_tools
        monkeypatch.setattr(common_tools, "_MEMORY_DIR", tmp_path)

        memory_md = tmp_path / "MEMORY.md"
        memory_md.write_text("# small index\n\n- item one\n- item two\n")

        result = common_tools.memory_read("index")
        assert result["content"] == "# small index\n\n- item one\n- item two\n"
        assert "TRUNCATED" not in result["content"]


# ---------------------------------------------------------------------------
# _build_system_prompt input cap (CRITICAL)
# ---------------------------------------------------------------------------


class TestSystemPromptInputCap:
    """The highest-leverage surface in the codebase. AGENT.md, SOUL.md,
    and MEMORY.md feed the system prompt directly. MEMORY.md is
    agent-writable via the dream cycle, so the cap is the safety net
    against a runaway dream inflating the prompt unbounded."""

    def test_read_capped_returns_full_text_under_cap(self, tmp_path):
        from cli.telegram_agent import _read_capped

        small = tmp_path / "small.md"
        small.write_text("# Small File\n\nA few lines.\n")
        result = _read_capped(small, "small.md")
        assert result == "# Small File\n\nA few lines."

    def test_read_capped_truncates_over_cap(self, tmp_path, caplog):
        import logging
        from cli.telegram_agent import _read_capped, _SYSTEM_PROMPT_INPUT_CAP

        big = tmp_path / "MEMORY.md"
        big.write_text("x" * (_SYSTEM_PROMPT_INPUT_CAP + 5000))

        with caplog.at_level(logging.WARNING):
            result = _read_capped(big, "MEMORY.md")

        # Truncated to cap + a marker
        assert len(result) <= _SYSTEM_PROMPT_INPUT_CAP + 200
        assert "TRUNCATED at 20KB cap" in result
        # Warning logged
        assert any("MEMORY.md" in r.message and "TRUNCATED" in r.message for r in caplog.records)

    def test_read_capped_missing_file_returns_empty(self, tmp_path):
        from cli.telegram_agent import _read_capped

        missing = tmp_path / "doesnotexist.md"
        result = _read_capped(missing, "doesnotexist.md")
        assert result == ""

    def test_system_prompt_cap_constant_is_20kb(self):
        from cli.telegram_agent import _SYSTEM_PROMPT_INPUT_CAP
        assert _SYSTEM_PROMPT_INPUT_CAP == 20_000


# ---------------------------------------------------------------------------
# _load_chat_history streaming tail-read
# ---------------------------------------------------------------------------


class TestLoadChatHistoryTailRead:
    def test_tail_read_returns_last_n_rows(self, tmp_path, monkeypatch):
        from cli import telegram_agent
        history_path = tmp_path / "chat_history.jsonl"
        rows = [
            {"ts": i, "role": "user", "text": f"msg {i}"}
            for i in range(100)
        ]
        history_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        monkeypatch.setattr(telegram_agent, "_HISTORY_FILE", history_path)

        result = telegram_agent._load_chat_history(limit=10)
        assert len(result) == 10
        # Most recent 10 rows
        texts = [r["text"] for r in result]
        assert "msg 99" in texts
        assert "msg 90" in texts
        assert "msg 0" not in texts

    def test_tail_read_handles_giant_file(self, tmp_path, monkeypatch):
        """A 10k-row chat history file should still load in O(limit*5)
        memory via the deque tail."""
        from cli import telegram_agent
        history_path = tmp_path / "chat_history.jsonl"
        rows = [
            {"ts": i, "role": "user", "text": f"msg {i}"}
            for i in range(10000)
        ]
        history_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        monkeypatch.setattr(telegram_agent, "_HISTORY_FILE", history_path)

        result = telegram_agent._load_chat_history(limit=5)
        # Should return at most 5 (after limit + char-budget trim)
        assert 1 <= len(result) <= 5
        # Newest rows
        if result:
            assert result[-1]["text"] == "msg 9999"
