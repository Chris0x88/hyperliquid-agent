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
    # Phase 5: the hook now lazily runs a sweep when state is missing.
    # With a valid repo_root the sweep creates state/current_report.md and
    # the hook returns that fresh report. The key guarantee is that the
    # hook produces Guardian-prefixed output without raising.
    mod = _load_hook()
    result = mod.build_summary(state_dir=tmp_path / "does_not_exist", repo_root=tmp_path)
    assert "Guardian" in result
    assert result.strip() != ""


def test_hook_reads_current_report(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "current_report.md").write_text("# Test Report\nP0: orphan X\n")
    mod = _load_hook()
    result = mod.build_summary(state_dir=state, repo_root=tmp_path)
    assert "Test Report" in result or "orphan X" in result


def test_hook_reports_staleness(tmp_path: Path, monkeypatch):
    # Phase 5: a stale report normally triggers a lazy re-sweep which
    # replaces it with a fresh mtime. To verify the staleness-marker
    # branch still works, disable the lazy sweep by pointing repo_root
    # at a directory without importable guardian modules (the import
    # inside _maybe_run_sweep fails silently) — but that only works if
    # guardian isn't already cached. Simpler: monkeypatch _maybe_run_sweep
    # to a no-op so the stale report survives into the read path.
    state = tmp_path / "state"
    state.mkdir()
    report = state / "current_report.md"
    report.write_text("# Old Report\n")
    # Set mtime to 48 hours ago
    old = time.time() - 48 * 3600
    os.utime(report, (old, old))
    mod = _load_hook()
    monkeypatch.setattr(mod, "_maybe_run_sweep", lambda *a, **kw: None)
    result = mod.build_summary(state_dir=state, repo_root=tmp_path)
    assert "stale" in result.lower() or "hours" in result.lower() or "48" in result


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
