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


# Deleted 2026-04-09 — session_start.py permanently gutted to a no-op per
# user request. The three tests previously here (missing_state_dir,
# reads_current_report, reports_staleness) asserted behavior of the
# now-removed build_summary() body.


def test_hook_respects_global_kill_switch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_ENABLED", "0")
    mod = _load_hook()
    result = mod.build_summary(state_dir=tmp_path, repo_root=tmp_path)
    assert result == ""


def test_hook_runs_sweep_when_no_report(tmp_path: Path, monkeypatch):
    # Minimal fake repo so sweep has something to look at
    (tmp_path / "guardian" / "state").mkdir(parents=True)
    (tmp_path / "cli" / "daemon" / "iterators").mkdir(parents=True)
    (tmp_path / "cli" / "telegram_bot.py").write_text("HANDLERS = {}\n")
    (tmp_path / "a.py").write_text("x = 1\n")
    monkeypatch.chdir(tmp_path)
    mod = _load_hook()
    result = mod.build_summary(
        state_dir=tmp_path / "guardian" / "state",
        repo_root=tmp_path,
    )
    # Should either trigger a sweep or report no report
    assert isinstance(result, str)


def test_hook_subagent_dispatch_kill_switch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_SUBAGENTS_ENABLED", "0")
    (tmp_path / "guardian" / "state").mkdir(parents=True)
    mod = _load_hook()
    # Hook should not error even with sub-agents disabled
    result = mod.build_summary(
        state_dir=tmp_path / "guardian" / "state",
        repo_root=tmp_path,
    )
    assert isinstance(result, str)
