"""Tests for guardian/sweep.py orchestrator."""
from __future__ import annotations

import json
from pathlib import Path

from guardian.sweep import run_sweep


def test_sweep_on_empty_repo_produces_all_outputs(tmp_repo: Path):
    state_dir = tmp_repo / "guardian" / "state"
    run_sweep(repo_root=tmp_repo, state_dir=state_dir)
    assert (state_dir / "inventory.json").exists()
    assert (state_dir / "drift_report.json").exists()
    assert (state_dir / "friction_report.json").exists()
    assert (state_dir / "sweep.log").exists()


def test_sweep_returns_summary(tmp_repo: Path):
    state_dir = tmp_repo / "guardian" / "state"
    summary = run_sweep(repo_root=tmp_repo, state_dir=state_dir)
    assert "modules" in summary
    assert "drift_p0" in summary
    assert "friction_p0" in summary
    assert "duration_s" in summary


def test_sweep_respects_global_kill_switch(tmp_repo: Path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_ENABLED", "0")
    state_dir = tmp_repo / "guardian" / "state"
    summary = run_sweep(repo_root=tmp_repo, state_dir=state_dir)
    assert summary.get("skipped") is True
