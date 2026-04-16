"""Tests for BTC vault trade detection, liq gate, and status summary."""
from __future__ import annotations

import time

from trading.heartbeat import (
    btc_liq_gate,
    detect_btc_trade,
    should_send_status_summary,
)


# ── detect_btc_trade ─────────────────────────────────────────────────────────

def test_btc_trade_detected():
    """Detects when BTC vault position changed."""
    last = {"size": 0.10, "side": "long"}
    current = {"size": 0.11, "side": "long", "entry": 68200, "mark": 68420}
    result = detect_btc_trade(current, last)
    assert result["trade_detected"] is True
    assert result["direction"] == "buy"
    assert abs(result["delta"] - 0.01) < 0.001


def test_btc_no_trade():
    last = {"size": 0.10, "side": "long"}
    result = detect_btc_trade(last, last)
    assert result["trade_detected"] is False


def test_btc_trade_sell_detected():
    """Detects a sell (position decrease)."""
    last = {"size": 0.15, "side": "long"}
    current = {"size": 0.10, "side": "long", "entry": 68200, "mark": 68000}
    result = detect_btc_trade(current, last)
    assert result["trade_detected"] is True
    assert result["direction"] == "sell"
    assert abs(result["delta"] - 0.05) < 0.001


def test_btc_trade_empty_positions():
    """Handles empty dicts gracefully."""
    result = detect_btc_trade({}, {})
    assert result["trade_detected"] is False


# ── btc_liq_gate ─────────────────────────────────────────────────────────────

def test_btc_liq_gate_blocks_increase():
    assert btc_liq_gate(liq_distance_pct=12, direction="buy") is False
    assert btc_liq_gate(liq_distance_pct=12, direction="sell") is True
    assert btc_liq_gate(liq_distance_pct=20, direction="buy") is True


def test_btc_liq_gate_exact_threshold():
    """Buy allowed at exactly the threshold."""
    assert btc_liq_gate(liq_distance_pct=15, direction="buy") is True


def test_btc_liq_gate_custom_threshold():
    """Custom min_liq_pct works."""
    assert btc_liq_gate(liq_distance_pct=18, direction="buy", min_liq_pct=20) is False
    assert btc_liq_gate(liq_distance_pct=22, direction="buy", min_liq_pct=20) is True


# ── should_send_status_summary ───────────────────────────────────────────────

def test_should_send_status_summary_due():
    now = int(time.time() * 1000)
    assert should_send_status_summary(last_summary_ms=now - 7 * 3600 * 1000, now_ms=now) is True


def test_should_send_status_summary_not_due():
    now = int(time.time() * 1000)
    assert should_send_status_summary(last_summary_ms=now - 3 * 3600 * 1000, now_ms=now) is False


def test_should_send_status_summary_first_run():
    now = int(time.time() * 1000)
    assert should_send_status_summary(last_summary_ms=0, now_ms=now) is True


def test_should_send_status_summary_exact_boundary():
    """Exactly at the interval boundary should trigger."""
    now = int(time.time() * 1000)
    assert should_send_status_summary(last_summary_ms=now - 6 * 3600 * 1000, now_ms=now) is True
