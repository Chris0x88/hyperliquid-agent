"""Tests for modules/oil_botpattern_paper.py — shadow-mode paper trader pure logic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from modules.oil_botpattern_paper import (
    ShadowBalance,
    ShadowPosition,
    ShadowTrade,
    balance_from_dict,
    balance_to_dict,
    check_exit,
    close_shadow_position,
    compute_stop_price,
    compute_tp_price,
    new_balance,
    open_shadow_position,
    position_from_dict,
    position_to_dict,
    realised_pnl,
    roe_pct_on_margin,
    trade_to_dict,
    unrealized_pnl,
    update_balance_on_close,
)


UTC = timezone.utc


def _now() -> datetime:
    return datetime(2026, 4, 9, 10, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Stop + TP price
# ---------------------------------------------------------------------------

def test_compute_stop_price_long():
    assert compute_stop_price(100.0, "long", 2.0) == 98.0


def test_compute_stop_price_short():
    assert compute_stop_price(100.0, "short", 2.0) == 102.0


def test_compute_stop_price_zero_safe():
    assert compute_stop_price(0.0, "long", 2.0) == 0.0
    assert compute_stop_price(100.0, "long", 0.0) == 100.0


def test_compute_tp_price_long():
    assert compute_tp_price(100.0, "long", 5.0) == 105.0


def test_compute_tp_price_short():
    assert compute_tp_price(100.0, "short", 5.0) == 95.0


# ---------------------------------------------------------------------------
# PnL math
# ---------------------------------------------------------------------------

def test_unrealized_pnl_long_winner():
    pos = ShadowPosition(
        instrument="BRENTOIL", side="long", entry_ts="x", entry_price=67.0,
        size=1000, leverage=5, notional_usd=67000, stop_price=0, tp_price=0,
        edge=0.7, rung=2,
    )
    assert unrealized_pnl(pos, 69.0) == pytest.approx(2000)


def test_unrealized_pnl_long_loser():
    pos = ShadowPosition(
        instrument="BRENTOIL", side="long", entry_ts="x", entry_price=67.0,
        size=1000, leverage=5, notional_usd=67000, stop_price=0, tp_price=0,
        edge=0.7, rung=2,
    )
    assert unrealized_pnl(pos, 66.0) == pytest.approx(-1000)


def test_unrealized_pnl_short_winner():
    pos = ShadowPosition(
        instrument="BRENTOIL", side="short", entry_ts="x", entry_price=70.0,
        size=500, leverage=3, notional_usd=35000, stop_price=0, tp_price=0,
        edge=0.7, rung=1,
    )
    assert unrealized_pnl(pos, 68.0) == pytest.approx(1000)


def test_unrealized_pnl_short_loser():
    pos = ShadowPosition(
        instrument="BRENTOIL", side="short", entry_ts="x", entry_price=70.0,
        size=500, leverage=3, notional_usd=35000, stop_price=0, tp_price=0,
        edge=0.7, rung=1,
    )
    assert unrealized_pnl(pos, 72.0) == pytest.approx(-1000)


def test_roe_pct_on_margin():
    # $2000 PnL on $67000 notional at 5x = $13400 margin = 14.93% ROE
    roe = roe_pct_on_margin(2000, 67000, 5.0)
    assert roe == pytest.approx(2000 / (67000 / 5) * 100, rel=1e-6)


def test_roe_pct_zero_safe():
    assert roe_pct_on_margin(100, 0, 5.0) == 0.0
    assert roe_pct_on_margin(100, 67000, 0.0) == 0.0


# ---------------------------------------------------------------------------
# check_exit
# ---------------------------------------------------------------------------

def _long_pos() -> ShadowPosition:
    return ShadowPosition(
        instrument="BRENTOIL", side="long", entry_ts="x", entry_price=67.0,
        size=1000, leverage=5, notional_usd=67000,
        stop_price=65.66,  # ~2% stop
        tp_price=70.35,    # ~5% target
        edge=0.7, rung=2,
    )


def _short_pos() -> ShadowPosition:
    return ShadowPosition(
        instrument="BRENTOIL", side="short", entry_ts="x", entry_price=70.0,
        size=500, leverage=3, notional_usd=35000,
        stop_price=71.40,  # ~2% stop
        tp_price=66.50,    # ~5% target
        edge=0.7, rung=1,
    )


def test_check_exit_long_no_hit():
    reason, price = check_exit(_long_pos(), 68.0)
    assert reason is None
    assert price == 0.0


def test_check_exit_long_sl_hit():
    reason, price = check_exit(_long_pos(), 65.0)
    assert reason == "sl_hit"
    assert price == 65.66  # exit at the stop level


def test_check_exit_long_tp_hit():
    reason, price = check_exit(_long_pos(), 71.0)
    assert reason == "tp_hit"
    assert price == 70.35


def test_check_exit_short_sl_hit():
    reason, price = check_exit(_short_pos(), 72.0)
    assert reason == "sl_hit"
    assert price == 71.40


def test_check_exit_short_tp_hit():
    reason, price = check_exit(_short_pos(), 66.0)
    assert reason == "tp_hit"
    assert price == 66.50


def test_check_exit_zero_price():
    reason, _ = check_exit(_long_pos(), 0.0)
    assert reason is None


# ---------------------------------------------------------------------------
# open_shadow_position + close_shadow_position
# ---------------------------------------------------------------------------

def test_open_shadow_position_computes_levels():
    pos = open_shadow_position(
        instrument="BRENTOIL", side="long",
        entry_price=67.00, size=1000, leverage=5.0,
        sl_pct=2.0, tp_pct=5.0,
        edge=0.7, rung=2, now=_now(),
    )
    assert pos.notional_usd == 67_000
    assert pos.stop_price == pytest.approx(67.0 * 0.98)
    assert pos.tp_price == pytest.approx(67.0 * 1.05)
    assert pos.entry_ts == _now().isoformat()


def test_close_shadow_position_winner():
    pos = open_shadow_position(
        instrument="BRENTOIL", side="long",
        entry_price=67.0, size=1000, leverage=5.0,
        sl_pct=2.0, tp_pct=5.0,
        edge=0.7, rung=2, now=_now(),
    )
    later = _now() + timedelta(hours=3)
    trade = close_shadow_position(pos, exit_price=70.35, exit_reason="tp_hit", now=later)
    assert trade.realised_pnl_usd == pytest.approx(1000 * (70.35 - 67.0))
    assert trade.exit_reason == "tp_hit"
    assert trade.hold_hours == pytest.approx(3.0)
    assert trade.roe_pct > 0


def test_close_shadow_position_loser():
    pos = open_shadow_position(
        instrument="BRENTOIL", side="short",
        entry_price=70.0, size=500, leverage=3.0,
        sl_pct=2.0, tp_pct=5.0,
        edge=0.7, rung=1, now=_now(),
    )
    later = _now() + timedelta(hours=1)
    trade = close_shadow_position(pos, exit_price=71.40, exit_reason="sl_hit", now=later)
    assert trade.realised_pnl_usd == pytest.approx(500 * (70.0 - 71.40))
    assert trade.realised_pnl_usd < 0
    assert trade.roe_pct < 0


def test_close_shadow_position_bad_entry_ts_hold_zero():
    pos = ShadowPosition(
        instrument="BRENTOIL", side="long", entry_ts="garbage",
        entry_price=67.0, size=1000, leverage=5,
        notional_usd=67000, stop_price=66.0, tp_price=70.0,
        edge=0.7, rung=2,
    )
    trade = close_shadow_position(pos, exit_price=68.0, exit_reason="manual", now=_now())
    assert trade.hold_hours == 0.0


# ---------------------------------------------------------------------------
# ShadowBalance
# ---------------------------------------------------------------------------

def test_new_balance_seeds():
    b = new_balance(100_000)
    assert b.seed_balance_usd == 100_000
    assert b.current_balance_usd == 100_000
    assert b.closed_trades == 0
    assert b.win_rate == 0.0
    assert b.pnl_pct == 0.0


def test_update_balance_on_winning_close():
    b = new_balance(100_000)
    pos = open_shadow_position(
        "BRENTOIL", "long", 67.0, 1000, 5.0, 2.0, 5.0, 0.7, 2, _now(),
    )
    trade = close_shadow_position(pos, 70.35, "tp_hit", _now() + timedelta(hours=2))
    b2 = update_balance_on_close(b, trade, _now() + timedelta(hours=2))
    assert b2.closed_trades == 1
    assert b2.wins == 1
    assert b2.losses == 0
    assert b2.realised_pnl_usd == pytest.approx(trade.realised_pnl_usd)
    assert b2.current_balance_usd == pytest.approx(100_000 + trade.realised_pnl_usd)
    # Original untouched
    assert b.closed_trades == 0


def test_update_balance_on_losing_close():
    b = new_balance(100_000)
    pos = open_shadow_position(
        "BRENTOIL", "short", 70.0, 500, 3.0, 2.0, 5.0, 0.7, 1, _now(),
    )
    trade = close_shadow_position(pos, 71.40, "sl_hit", _now() + timedelta(hours=1))
    b2 = update_balance_on_close(b, trade, _now() + timedelta(hours=1))
    assert b2.losses == 1
    assert b2.wins == 0
    assert b2.current_balance_usd < 100_000


def test_balance_win_rate_multiple_closes():
    b = new_balance(100_000)
    for i in range(5):
        pos = open_shadow_position(
            "BRENTOIL", "long", 67.0, 1000, 5.0, 2.0, 5.0, 0.7, 2, _now(),
        )
        exit_price = 70.35 if i < 3 else 65.66
        reason = "tp_hit" if i < 3 else "sl_hit"
        trade = close_shadow_position(pos, exit_price, reason, _now() + timedelta(hours=1))
        b = update_balance_on_close(b, trade, _now())
    assert b.closed_trades == 5
    assert b.wins == 3
    assert b.losses == 2
    assert b.win_rate == 0.6


# ---------------------------------------------------------------------------
# Serialization roundtrips
# ---------------------------------------------------------------------------

def test_position_roundtrip():
    pos = open_shadow_position(
        "BRENTOIL", "long", 67.0, 1000, 5.0, 2.0, 5.0, 0.7, 2, _now(),
    )
    back = position_from_dict(position_to_dict(pos))
    assert back.instrument == "BRENTOIL"
    assert back.entry_price == 67.0
    assert back.stop_price == pytest.approx(67.0 * 0.98)
    assert back.rung == 2


def test_balance_roundtrip():
    b = ShadowBalance(
        seed_balance_usd=100_000,
        current_balance_usd=103_500,
        realised_pnl_usd=3500,
        closed_trades=5, wins=3, losses=2,
        last_updated_at="2026-04-09T10:00:00+00:00",
    )
    d = balance_to_dict(b)
    assert d["win_rate"] == 0.6
    assert d["pnl_pct"] == pytest.approx(3.5)
    back = balance_from_dict(d)
    assert back.seed_balance_usd == 100_000
    assert back.wins == 3


def test_balance_from_dict_defaults():
    back = balance_from_dict({}, default_seed=50_000)
    assert back.seed_balance_usd == 50_000
    assert back.current_balance_usd == 50_000


def test_trade_to_dict_serializable():
    pos = open_shadow_position(
        "BRENTOIL", "long", 67.0, 1000, 5.0, 2.0, 5.0, 0.7, 2, _now(),
    )
    trade = close_shadow_position(pos, 70.35, "tp_hit", _now() + timedelta(hours=1))
    d = trade_to_dict(trade)
    assert d["exit_reason"] == "tp_hit"
    assert d["realised_pnl_usd"] > 0
    assert "hold_hours" in d
