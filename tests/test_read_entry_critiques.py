"""Unit tests for agent.tool_functions.read_entry_critiques.

Covers:
  - missing file → empty result
  - empty file → empty result
  - malformed lines skipped gracefully
  - limit respected
  - newest-first ordering (by created_at ISO string)
  - market filter: bare name match (BRENTOIL)
  - market filter: xyz: prefixed name match (xyz:BRENTOIL)
  - xyz: prefix normalisation: caller passes BRENTOIL, file has xyz:BRENTOIL
  - market filter returns no results when nothing matches
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


# ── Helpers ────────────────────────────────────────────────────────────

def _make_row(
    instrument: str = "BRENTOIL",
    direction: str = "long",
    overall_label: str = "GOOD ENTRY",
    created_at: str = "2026-04-10T00:00:00Z",
) -> dict:
    return {
        "schema_version": 1,
        "kind": "entry_critique",
        "created_at": created_at,
        "instrument": instrument,
        "direction": direction,
        "entry_price": 75.0,
        "entry_qty": 10.0,
        "leverage": 5.0,
        "notional_usd": 750.0,
        "equity_usd": 1000.0,
        "actual_size_pct": 75.0,
        "grade": {
            "sizing": "OK",
            "sizing_detail": "actual=75.0% target=50%",
            "direction": "ALIGNED",
            "direction_detail": "thesis is long",
            "catalyst_timing": "NEUTRAL",
            "catalyst_detail": "no catalyst",
            "liquidity": "SAFE",
            "liquidity_detail": "no cascade",
            "funding": "CHEAP",
            "funding_detail": "0.02%/8h",
            "pass_count": 3,
            "warn_count": 2,
            "fail_count": 0,
            "overall_label": overall_label,
            "suggestions": ["Check RSI before entry"],
        },
        "signals": {
            "rsi": 55.0,
            "atr_pct": 1.5,
            "liquidation_cushion_pct": 8.0,
            "snapshot_flags": ["below_vwap_4h"],
            "lesson_ids": [1, 2],
        },
        "degraded": {},
    }


def _write_jsonl(path: Path, rows: list[dict], extra_lines: list[str] | None = None) -> None:
    with path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
        for line in (extra_lines or []):
            fh.write(line + "\n")


def _read_critiques(critiques_path: Path, limit: int = 5, market: str | None = None) -> dict:
    """Invoke read_entry_critiques with a patched _ENTRY_CRITIQUES_JSONL."""
    import agent.tool_functions as tf
    original = tf._ENTRY_CRITIQUES_JSONL
    try:
        tf._ENTRY_CRITIQUES_JSONL = critiques_path
        return tf.read_entry_critiques(limit=limit, market=market)
    finally:
        tf._ENTRY_CRITIQUES_JSONL = original


# ── Tests ──────────────────────────────────────────────────────────────

def test_missing_file_returns_empty():
    result = _read_critiques(Path("/nonexistent/path/entry_critiques.jsonl"))
    assert result["critiques"] == []
    assert result["total"] == 0
    assert result["market_filter"] is None


def test_empty_file_returns_empty():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as fh:
        path = Path(fh.name)
    try:
        result = _read_critiques(path)
        assert result["critiques"] == []
        assert result["total"] == 0
    finally:
        path.unlink(missing_ok=True)


def test_malformed_lines_skipped():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as fh:
        path = Path(fh.name)
    try:
        good = _make_row(created_at="2026-04-10T01:00:00Z")
        _write_jsonl(path, [good], extra_lines=["not json", "{broken"])
        result = _read_critiques(path)
        assert result["total"] == 1
        assert len(result["critiques"]) == 1
    finally:
        path.unlink(missing_ok=True)


def test_limit_respected():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as fh:
        path = Path(fh.name)
    try:
        rows = [
            _make_row(created_at=f"2026-04-10T0{i}:00:00Z") for i in range(8)
        ]
        _write_jsonl(path, rows)
        result = _read_critiques(path, limit=3)
        assert result["total"] == 8
        assert len(result["critiques"]) == 3
    finally:
        path.unlink(missing_ok=True)


def test_newest_first_ordering():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as fh:
        path = Path(fh.name)
    try:
        rows = [
            _make_row(created_at="2026-04-10T01:00:00Z"),
            _make_row(created_at="2026-04-10T03:00:00Z"),  # newest
            _make_row(created_at="2026-04-10T02:00:00Z"),
        ]
        _write_jsonl(path, rows)
        result = _read_critiques(path, limit=3)
        timestamps = [r["created_at"] for r in result["critiques"]]
        assert timestamps == sorted(timestamps, reverse=True)
        assert timestamps[0] == "2026-04-10T03:00:00Z"
    finally:
        path.unlink(missing_ok=True)


def test_market_filter_bare_name():
    """Filter by BRENTOIL matches rows with instrument='BRENTOIL'."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as fh:
        path = Path(fh.name)
    try:
        rows = [
            _make_row(instrument="BRENTOIL", created_at="2026-04-10T01:00:00Z"),
            _make_row(instrument="BTC", created_at="2026-04-10T02:00:00Z"),
            _make_row(instrument="BRENTOIL", created_at="2026-04-10T03:00:00Z"),
        ]
        _write_jsonl(path, rows)
        result = _read_critiques(path, limit=10, market="BRENTOIL")
        assert result["total"] == 2
        for r in result["critiques"]:
            assert r["instrument"] == "BRENTOIL"
    finally:
        path.unlink(missing_ok=True)


def test_market_filter_xyz_prefix_in_file():
    """Caller passes BRENTOIL; file has xyz:BRENTOIL — must still match."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as fh:
        path = Path(fh.name)
    try:
        rows = [
            _make_row(instrument="xyz:BRENTOIL", created_at="2026-04-10T01:00:00Z"),
            _make_row(instrument="BTC", created_at="2026-04-10T02:00:00Z"),
        ]
        _write_jsonl(path, rows)
        result = _read_critiques(path, limit=10, market="BRENTOIL")
        assert result["total"] == 1
        assert result["critiques"][0]["instrument"] == "xyz:BRENTOIL"
    finally:
        path.unlink(missing_ok=True)


def test_market_filter_xyz_prefix_in_caller():
    """Caller passes xyz:BRENTOIL; file has BRENTOIL — must still match."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as fh:
        path = Path(fh.name)
    try:
        rows = [
            _make_row(instrument="BRENTOIL", created_at="2026-04-10T01:00:00Z"),
        ]
        _write_jsonl(path, rows)
        result = _read_critiques(path, limit=10, market="xyz:BRENTOIL")
        assert result["total"] == 1
    finally:
        path.unlink(missing_ok=True)


def test_market_filter_no_match():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as fh:
        path = Path(fh.name)
    try:
        rows = [_make_row(instrument="BTC"), _make_row(instrument="GOLD")]
        _write_jsonl(path, rows)
        result = _read_critiques(path, limit=10, market="BRENTOIL")
        assert result["total"] == 0
        assert result["critiques"] == []
        assert result["market_filter"] == "BRENTOIL"
    finally:
        path.unlink(missing_ok=True)


def test_no_filter_returns_all_markets():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as fh:
        path = Path(fh.name)
    try:
        rows = [
            _make_row(instrument="BTC", created_at="2026-04-10T01:00:00Z"),
            _make_row(instrument="xyz:BRENTOIL", created_at="2026-04-10T02:00:00Z"),
            _make_row(instrument="GOLD", created_at="2026-04-10T03:00:00Z"),
        ]
        _write_jsonl(path, rows)
        result = _read_critiques(path, limit=10)
        assert result["total"] == 3
        assert result["market_filter"] is None
    finally:
        path.unlink(missing_ok=True)
