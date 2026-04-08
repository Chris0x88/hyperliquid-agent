"""Tests for the recent-delete-guard gate rule."""
from __future__ import annotations

import os
import time
from pathlib import Path

from guardian.gate import check_tool_use


def test_rule_allows_delete_of_old_file(tmp_path: Path, monkeypatch):
    old = tmp_path / "old.py"
    old.write_text("x")
    # Set ctime/mtime to 30 days ago
    t = time.time() - 30 * 86400
    os.utime(old, (t, t))
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Bash",
        tool_input={"command": f"rm {old}"},
    )
    assert result.allow is True


def test_rule_blocks_delete_of_recent_file(tmp_path: Path, monkeypatch):
    recent = tmp_path / "recent.py"
    recent.write_text("x")
    # Keep mtime as now
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Bash",
        tool_input={"command": f"rm {recent}"},
    )
    assert result.allow is False
    assert "recent.py" in (result.reason or "")


def test_rule_ignores_non_delete_bash_commands(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Bash",
        tool_input={"command": "ls -la"},
    )
    assert result.allow is True


def test_rule_kill_switch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_RULE_RECENT_DELETE", "0")
    recent = tmp_path / "recent.py"
    recent.write_text("x")
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Bash",
        tool_input={"command": f"rm {recent}"},
    )
    assert result.allow is True
