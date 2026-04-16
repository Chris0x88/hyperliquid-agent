"""Regression tests for the readiness thesis-timestamp fallback.

The BRENTOIL thesis file uses `last_evaluation_ts` as a Unix epoch in
MILLISECONDS (written by the AI agent's thesis-write path). The
/readiness check previously only looked for ISO strings in
updated_at / last_updated / timestamp, so a thesis that had ONLY
last_evaluation_ts would render as 🟡 "no timestamp" even when the
file was minutes old.

These tests guarantee the epoch-ms fallback stays wired.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from telegram.commands.readiness import check_heatmap, check_thesis, compute_readiness


UTC = timezone.utc


def _patch_paths(tmp: Path):
    patchers = [
        patch("telegram.commands.readiness.BRENTOIL_THESIS_JSON",
              str(tmp / "thesis.json")),
        patch("telegram.commands.readiness.HEATMAP_ZONES_JSONL",
              str(tmp / "zones.jsonl")),
    ]
    for p in patchers:
        p.start()
    return patchers


def _stop(patchers):
    for p in patchers:
        p.stop()


def _now() -> datetime:
    return datetime(2026, 4, 9, 10, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# check_thesis — last_evaluation_ts fallback
# ---------------------------------------------------------------------------

def test_thesis_last_evaluation_ts_millis_fresh(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        # 2 hours ago in ms
        ts_ms = int((_now() - timedelta(hours=2)).timestamp() * 1000)
        (tmp_path / "thesis.json").write_text(json.dumps({
            "market": "xyz:BRENTOIL",
            "direction": "short",
            "conviction": 0.25,
            "last_evaluation_ts": ts_ms,
        }))
        sym, _name, verdict, sev = check_thesis(_now())
        assert sym == "🟢"
        assert sev == "green"
        assert "conviction=0.25" in verdict
    finally:
        _stop(patchers)


def test_thesis_last_evaluation_ts_millis_aging(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        ts_ms = int((_now() - timedelta(hours=96)).timestamp() * 1000)  # 4 days
        (tmp_path / "thesis.json").write_text(json.dumps({
            "market": "xyz:BRENTOIL",
            "conviction": 0.25,
            "last_evaluation_ts": ts_ms,
        }))
        _sym, _name, _verdict, sev = check_thesis(_now())
        assert sev == "yellow"
    finally:
        _stop(patchers)


def test_thesis_last_evaluation_ts_millis_stale(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        ts_ms = int((_now() - timedelta(hours=200)).timestamp() * 1000)
        (tmp_path / "thesis.json").write_text(json.dumps({
            "market": "xyz:BRENTOIL",
            "conviction": 0.25,
            "last_evaluation_ts": ts_ms,
        }))
        _sym, _name, _verdict, sev = check_thesis(_now())
        assert sev == "red"
    finally:
        _stop(patchers)


def test_thesis_last_evaluation_ts_seconds_also_works(tmp_path):
    """Heuristic: epoch < 1e12 is treated as seconds, not millis."""
    patchers = _patch_paths(tmp_path)
    try:
        ts_s = int((_now() - timedelta(hours=1)).timestamp())
        (tmp_path / "thesis.json").write_text(json.dumps({
            "market": "xyz:BRENTOIL",
            "conviction": 0.25,
            "last_evaluation_ts": ts_s,
        }))
        _sym, _name, _verdict, sev = check_thesis(_now())
        assert sev == "green"
    finally:
        _stop(patchers)


def test_thesis_iso_path_still_works(tmp_path):
    """Existing ISO-string path must remain backward-compatible."""
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "thesis.json").write_text(json.dumps({
            "market": "xyz:BRENTOIL",
            "conviction": 0.7,
            "updated_at": (_now() - timedelta(hours=6)).isoformat(),
        }))
        _sym, _name, _verdict, sev = check_thesis(_now())
        assert sev == "green"
    finally:
        _stop(patchers)


def test_thesis_missing_timestamp_still_yellow(tmp_path):
    """A thesis file with NO timestamp field at all stays yellow."""
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "thesis.json").write_text(json.dumps({
            "market": "xyz:BRENTOIL",
            "conviction": 0.7,
            # no timestamp at all
        }))
        sym, _name, verdict, sev = check_thesis(_now())
        assert sym == "🟡"
        assert "no timestamp" in verdict
    finally:
        _stop(patchers)


def test_thesis_bad_epoch_falls_back_to_yellow(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        (tmp_path / "thesis.json").write_text(json.dumps({
            "market": "xyz:BRENTOIL",
            "conviction": 0.7,
            "last_evaluation_ts": "not a number",
        }))
        _sym, _name, _verdict, sev = check_thesis(_now())
        assert sev == "yellow"
    finally:
        _stop(patchers)


# ---------------------------------------------------------------------------
# check_heatmap — snapshot_at field
# ---------------------------------------------------------------------------

def test_heatmap_reads_snapshot_at_field(tmp_path):
    """Heatmap zones rows use `snapshot_at`, not `detected_at`.
    Ensure the readiness check reads the right field."""
    patchers = _patch_paths(tmp_path)
    try:
        row = {
            "instrument": "BRENTOIL",
            "snapshot_at": (_now() - timedelta(hours=1)).isoformat(),
            "mid": 95.0,
            "side": "bid",
        }
        (tmp_path / "zones.jsonl").write_text(json.dumps(row) + "\n")
        sym, _name, _verdict, sev = check_heatmap(_now())
        assert sym == "🟢"
        assert sev == "green"
    finally:
        _stop(patchers)


def test_heatmap_stale_snapshot_at(tmp_path):
    patchers = _patch_paths(tmp_path)
    try:
        row = {
            "snapshot_at": (_now() - timedelta(hours=20)).isoformat(),
        }
        (tmp_path / "zones.jsonl").write_text(json.dumps(row) + "\n")
        _sym, _name, _verdict, sev = check_heatmap(_now())
        assert sev == "red"
    finally:
        _stop(patchers)
