"""Tests for the parallel-track-warning gate rule."""
from __future__ import annotations

from pathlib import Path

from guardian.gate import check_tool_use


def test_rule_allows_new_distinct_file(tmp_path: Path, monkeypatch):
    (tmp_path / "cartographer.py").write_text("# cartographer")
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(tmp_path / "risk_manager.py"), "content": "# risk"},
    )
    assert result.allow is True


def test_rule_blocks_near_duplicate(tmp_path: Path, monkeypatch):
    (tmp_path / "memory_manager.py").write_text('"""manages memory"""')
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Write",
        tool_input={
            "file_path": str(tmp_path / "memory_manager_v2.py"),
            "content": '"""manages memory better"""',
        },
    )
    assert result.allow is False
    assert "memory_manager" in (result.reason or "")
    assert result.rule == "parallel-track-warning"


def test_rule_kill_switch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_RULE_PARALLEL_TRACK", "0")
    (tmp_path / "memory_manager.py").write_text("x")
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(tmp_path / "memory_manager_v2.py"), "content": "y"},
    )
    assert result.allow is True
