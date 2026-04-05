"""Tests for cli/agent_runtime.py — the core agent runtime."""
import json
import time
from pathlib import Path

import pytest


class TestBuildSystemPrompt:
    def test_assembles_all_sections(self):
        from cli.agent_runtime import build_system_prompt
        prompt = build_system_prompt()
        assert "autonomous" in prompt.lower()
        assert "Doing tasks" in prompt
        assert "Executing actions" in prompt
        assert "Using your tools" in prompt
        assert "Tone and style" in prompt

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
