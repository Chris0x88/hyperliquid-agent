"""Tests for friction report builder and writer."""
from __future__ import annotations

import json
from pathlib import Path

from guardian.friction import build_friction_report, write_friction_report


def test_build_report_on_empty_logs(tmp_path: Path):
    report = build_friction_report(
        feedback_path=tmp_path / "nope.jsonl",
        chat_history_path=tmp_path / "nope.jsonl",
    )
    assert report["summary"]["total"] == 0
    assert report["corrections"] == []
    assert report["errors"] == []


def test_build_report_with_signals(tmp_path: Path):
    fb = tmp_path / "feedback.jsonl"
    fb.write_text(
        '\n'.join([
            '{"type":"user_correction","subject":"SL_BRENTOIL","timestamp":"2026-04-01"}',
            '{"type":"user_correction","subject":"SL_BRENTOIL","timestamp":"2026-04-02"}',
            '{"type":"user_correction","subject":"SL_BRENTOIL","timestamp":"2026-04-03"}',
        ]) + '\n'
    )
    report = build_friction_report(
        feedback_path=fb,
        chat_history_path=tmp_path / "nope.jsonl",
    )
    assert report["summary"]["total"] >= 1


def test_write_report_creates_files(tmp_path: Path):
    report = build_friction_report(
        feedback_path=tmp_path / "nope.jsonl",
        chat_history_path=tmp_path / "nope.jsonl",
    )
    out = tmp_path / "state"
    write_friction_report(report, out)
    assert (out / "friction_report.json").exists()
    assert (out / "friction_report.md").exists()
