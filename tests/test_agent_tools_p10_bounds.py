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
