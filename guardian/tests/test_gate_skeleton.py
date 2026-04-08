"""Tests for gate.py skeleton."""
from __future__ import annotations

from guardian.gate import GateResult, check_tool_use


def test_gate_allows_unknown_tool():
    result = check_tool_use(tool_name="Unknown", tool_input={})
    assert isinstance(result, GateResult)
    assert result.allow is True


def test_gate_allows_when_globally_disabled(monkeypatch):
    monkeypatch.setenv("GUARDIAN_GATE_ENABLED", "0")
    result = check_tool_use(tool_name="Edit", tool_input={"file_path": "anything"})
    assert result.allow is True
    assert "disabled" in (result.reason or "").lower()


def test_gate_result_can_block():
    result = GateResult(allow=False, reason="test block", rule="test-rule")
    assert result.allow is False
    assert result.reason == "test block"
    assert result.rule == "test-rule"
