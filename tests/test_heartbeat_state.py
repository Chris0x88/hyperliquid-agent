"""Tests for common.heartbeat_state — working state persistence and ATR computation."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from common.heartbeat_state import (
    WorkingState,
    compute_atr,
    load_working_state,
    save_working_state,
)


# ── 1. Round-trip save / load ──────────────────────────────────────────────────

def test_save_and_load_working_state(tmp_path):
    """WorkingState survives a JSON round-trip with all fields intact."""
    p = str(tmp_path / "state.json")
    state = WorkingState(
        last_updated_ms=1000,
        session_peak_equity=50_000.0,
        session_peak_reset_date="2026-03-31",
        positions={"BTC-PERP": {"size": 1.0}},
        escalation_level="L1",
        last_l2_ms=500,
        last_l3_ms=None,
        last_ai_checkin_ms=900,
        heartbeat_consecutive_failures=2,
        atr_cache={"BTC-PERP": {"atr": 1200.5, "ts": 1000}},
        last_prices={"BTC-PERP": 60000.0},
        last_add_ms={"BTC-PERP": 800},
        last_status_summary_ms=700,
    )
    save_working_state(state, path=p)
    loaded = load_working_state(path=p)

    assert loaded.last_updated_ms == 1000
    assert loaded.session_peak_equity == 50_000.0
    assert loaded.session_peak_reset_date == "2026-03-31"
    assert loaded.positions == {"BTC-PERP": {"size": 1.0}}
    assert loaded.escalation_level == "L1"
    assert loaded.last_l2_ms == 500
    assert loaded.last_l3_ms is None
    assert loaded.last_ai_checkin_ms == 900
    assert loaded.heartbeat_consecutive_failures == 2
    assert loaded.atr_cache["BTC-PERP"]["atr"] == 1200.5
    assert loaded.last_prices["BTC-PERP"] == 60000.0
    assert loaded.last_add_ms["BTC-PERP"] == 800
    assert loaded.last_status_summary_ms == 700


# ── 2. Missing file returns fresh default ──────────────────────────────────────

def test_load_working_state_missing_file(tmp_path):
    """Loading from a non-existent path returns a fresh WorkingState."""
    p = str(tmp_path / "no_such_file.json")
    state = load_working_state(path=p)
    assert isinstance(state, WorkingState)
    assert state.last_updated_ms == 0
    assert state.escalation_level == "L0"
    assert state.positions == {}


# ── 3. Atomic save — no .tmp left behind ──────────────────────────────────────

def test_save_working_state_atomic(tmp_path):
    """After save, no .tmp file remains and the JSON is valid on disk."""
    p = str(tmp_path / "state.json")
    save_working_state(WorkingState(), path=p)

    # No .tmp file left
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == [], f"Leftover tmp files: {tmp_files}"

    # Valid JSON on disk
    with open(p) as f:
        data = json.load(f)
    assert "last_updated_ms" in data


# ── 4. ATR computation — correct from 3 candles ───────────────────────────────

def test_compute_atr_from_candles():
    """ATR from 3 candles (period=2) should use 2 true ranges."""
    # Candle 0: h=110, l=100, c=105
    # Candle 1: h=115, l=102, c=108  -> TR = max(13, |115-105|=10, |102-105|=3) = 13
    # Candle 2: h=120, l=106, c=112  -> TR = max(14, |120-108|=12, |106-108|=2) = 14
    candles = [
        {"h": "110", "l": "100", "c": "105"},
        {"h": "115", "l": "102", "c": "108"},
        {"h": "120", "l": "106", "c": "112"},
    ]
    atr = compute_atr(candles, period=2)
    assert atr is not None
    assert atr == pytest.approx(13.5)  # (13 + 14) / 2


# ── 5. ATR — empty candles ────────────────────────────────────────────────────

def test_compute_atr_empty_candles():
    """Empty candle list returns None."""
    assert compute_atr([]) is None


# ── 6. ATR — single candle ────────────────────────────────────────────────────

def test_compute_atr_single_candle():
    """Single candle returns None (need >= 2 for true range)."""
    assert compute_atr([{"h": "110", "l": "100", "c": "105"}]) is None


# ── 7. Session peak resets daily ───────────────────────────────────────────────

def test_session_peak_resets_daily():
    """Peak resets to current equity when date changes."""
    state = WorkingState(
        session_peak_equity=100_000.0,
        session_peak_reset_date="2026-03-30",
    )
    state.maybe_reset_peak("2026-03-31", 80_000.0)
    assert state.session_peak_equity == 80_000.0
    assert state.session_peak_reset_date == "2026-03-31"


# ── 8. Session peak updates on new high, doesn't decrease ─────────────────────

def test_session_peak_updates_on_new_high():
    """Peak increases on new high but doesn't decrease intra-day."""
    state = WorkingState(
        session_peak_equity=90_000.0,
        session_peak_reset_date="2026-03-31",
    )
    # New high
    state.maybe_reset_peak("2026-03-31", 95_000.0)
    assert state.session_peak_equity == 95_000.0

    # Lower equity — peak should NOT decrease
    state.maybe_reset_peak("2026-03-31", 88_000.0)
    assert state.session_peak_equity == 95_000.0
