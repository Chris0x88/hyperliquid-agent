"""Tests for common/diagnostics.py."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# Diagnostics logger tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDiagnosticsLogger:
    @pytest.fixture
    def diag(self, tmp_path):
        from common.diagnostics import DiagnosticsLogger
        return DiagnosticsLogger(diag_dir=tmp_path)

    def test_log_tool_call(self, diag, tmp_path):
        diag.log_tool_call("account", args={"mainnet": True}, result="ok", duration_ms=42)
        log_file = tmp_path / "tool_calls.jsonl"
        assert log_file.exists()
        entry = json.loads(log_file.read_text().strip())
        assert entry["cat"] == "tool_call"
        assert entry["event"] == "ok:account"
        assert entry["dur_ms"] == 42
        assert entry["data"]["tool"] == "account"

    def test_log_tool_error(self, diag, tmp_path):
        diag.log_tool_call("status", error="Connection refused", duration_ms=100)
        # Should appear in both tool_calls and errors
        assert (tmp_path / "tool_calls.jsonl").exists()
        assert (tmp_path / "errors.jsonl").exists()

        error_entry = json.loads((tmp_path / "errors.jsonl").read_text().strip())
        assert "Connection refused" in error_entry["data"]["error"]

    def test_log_chat(self, diag, tmp_path):
        diag.log_chat("user", "How's my oil?", channel="telegram")
        diag.log_chat("agent", "BRENTOIL is long 20 @ 107.5", channel="telegram")
        log_file = tmp_path / "chat_log.jsonl"
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["data"]["role"] == "user"
        assert json.loads(lines[1])["data"]["role"] == "agent"

    def test_log_error(self, diag, tmp_path):
        diag.log_error("mcp", "Tool timed out", details={"tool": "status"})
        log_file = tmp_path / "errors.jsonl"
        entry = json.loads(log_file.read_text().strip())
        assert entry["data"]["source"] == "mcp"

    def test_get_summary(self, diag):
        diag.log_tool_call("a", result="ok")
        diag.log_tool_call("b", result="ok")
        diag.log_tool_call("a", error="fail")
        summary = diag.get_summary()
        assert summary["total_tool_calls"] == 3
        assert summary["total_errors"] == 1
        assert summary["tool_calls"]["a"] == 2
        assert summary["tool_calls"]["b"] == 1

    def test_get_recent_errors(self, diag):
        for i in range(5):
            diag.log_error("test", f"error {i}")
        errors = diag.get_recent_errors(limit=3)
        assert len(errors) == 3

    def test_get_recent_chats(self, diag):
        for i in range(5):
            diag.log_chat("user", f"message {i}")
        chats = diag.get_recent_chats(limit=3)
        assert len(chats) == 3

    def test_truncation(self, diag, tmp_path):
        """Large results should be truncated."""
        diag.log_tool_call("big", result="x" * 1000)
        log_file = tmp_path / "tool_calls.jsonl"
        entry = json.loads(log_file.read_text().strip())
        assert len(entry["data"]["result"]) <= 500

