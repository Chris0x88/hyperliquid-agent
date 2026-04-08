"""Tests for friction pattern detection."""
from __future__ import annotations

import json
from pathlib import Path

from guardian.friction import (
    detect_repeated_corrections,
    detect_recurring_errors,
    read_jsonl,
)


def test_read_jsonl_handles_missing_file(tmp_path: Path):
    result = read_jsonl(tmp_path / "does_not_exist.jsonl")
    assert result == []


def test_read_jsonl_parses_valid_entries(tmp_path: Path):
    f = tmp_path / "log.jsonl"
    f.write_text('{"a": 1}\n{"a": 2}\n')
    result = read_jsonl(f)
    assert result == [{"a": 1}, {"a": 2}]


def test_read_jsonl_skips_malformed_lines(tmp_path: Path):
    f = tmp_path / "log.jsonl"
    f.write_text('{"a": 1}\nNOT JSON\n{"a": 2}\n')
    result = read_jsonl(f)
    assert result == [{"a": 1}, {"a": 2}]


def test_detects_repeated_corrections():
    entries = [
        {"type": "user_correction", "subject": "SL_BRENTOIL", "timestamp": "2026-04-01T10:00:00Z"},
        {"type": "user_correction", "subject": "SL_BRENTOIL", "timestamp": "2026-04-02T10:00:00Z"},
        {"type": "user_correction", "subject": "SL_BRENTOIL", "timestamp": "2026-04-03T10:00:00Z"},
        {"type": "user_correction", "subject": "TP_BTC", "timestamp": "2026-04-03T11:00:00Z"},
    ]
    findings = detect_repeated_corrections(entries, threshold=3)
    subjects = {f["subject"] for f in findings}
    assert "SL_BRENTOIL" in subjects
    assert "TP_BTC" not in subjects


def test_detects_recurring_errors():
    entries = [
        {"level": "error", "message": "connection timeout", "timestamp": "2026-04-01T10:00:00Z"},
        {"level": "error", "message": "connection timeout", "timestamp": "2026-04-02T10:00:00Z"},
        {"level": "error", "message": "connection timeout", "timestamp": "2026-04-03T10:00:00Z"},
        {"level": "error", "message": "unrelated error", "timestamp": "2026-04-03T11:00:00Z"},
    ]
    findings = detect_recurring_errors(entries, threshold=3)
    msgs = {f["message"] for f in findings}
    assert "connection timeout" in msgs
    assert "unrelated error" not in msgs
