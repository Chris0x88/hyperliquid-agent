"""Tests for the SessionStart hook (read-only mode)."""
from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path

import pytest


HOOK_PATH = Path(__file__).parent.parent / "hooks" / "session_start.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("guardian_session_start_hook", HOOK_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_hook_handles_missing_state_dir(tmp_path: Path):
    mod = _load_hook()
    result = mod.build_summary(state_dir=tmp_path / "does_not_exist", repo_root=tmp_path)
    assert "Guardian" in result
    assert "no report" in result.lower() or "not yet" in result.lower() or "state directory" in result.lower()


def test_hook_reads_current_report(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "current_report.md").write_text("# Test Report\nP0: orphan X\n")
    mod = _load_hook()
    result = mod.build_summary(state_dir=state, repo_root=tmp_path)
    assert "Test Report" in result or "orphan X" in result


def test_hook_reports_staleness(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    report = state / "current_report.md"
    report.write_text("# Old Report\n")
    # Set mtime to 48 hours ago
    old = time.time() - 48 * 3600
    os.utime(report, (old, old))
    mod = _load_hook()
    result = mod.build_summary(state_dir=state, repo_root=tmp_path)
    assert "stale" in result.lower() or "hours" in result.lower() or "48" in result


def test_hook_respects_global_kill_switch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_ENABLED", "0")
    mod = _load_hook()
    result = mod.build_summary(state_dir=tmp_path, repo_root=tmp_path)
    assert result == ""
