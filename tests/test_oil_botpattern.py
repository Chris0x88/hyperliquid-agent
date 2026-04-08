"""Tests for modules/oil_botpattern.py — sub-system 5 pure logic."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modules.oil_botpattern import (
    Decision,
    GateResult,
    SizingDecision,
    StrategyState,
    append_decision,
    check_drawdown_brakes,
    compute_edge,
    compute_recent_outcome_bias,
    gate_classification_ok,
    gate_no_blocking_catalyst,
    gate_no_fresh_supply_upgrade,
    gate_short_daily_loss_cap,
    gate_short_grace_period,
    gate_thesis_conflict,
    maybe_reset_daily_window,
    maybe_reset_monthly_window,
    maybe_reset_weekly_window,
    read_decisions,
    read_state,
    short_should_force_close,
    should_exit_on_funding,
    size_from_edge,
    write_state_atomic,
)


def _now():
    return datetime(2026, 4, 9, 22, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# compute_edge
# ---------------------------------------------------------------------------

def test_edge_uses_max_of_classifier_and_thesis():
    assert compute_edge(0.7, 0.5, True) == 0.7
    assert compute_edge(0.4, 0.8, True) == 0.8


def test_edge_zeroes_thesis_when_direction_mismatch():
    assert compute_edge(0.4, 0.9, False) == 0.4


def test_edge_applies_bias():
    assert abs(compute_edge(0.7, 0.0, False, 0.05) - 0.75) < 1e-9
    assert abs(compute_edge(0.7, 0.0, False, -0.05) - 0.65) < 1e-9


def test_edge_clamped_to_unit_interval():
    assert compute_edge(0.95, 0.95, True, 0.5) == 1.0
    assert compute_edge(0.0, 0.0, False, -0.5) == 0.0


# ---------------------------------------------------------------------------
# recent_outcome_bias
# ---------------------------------------------------------------------------

def test_recent_outcome_bias_insufficient_trades():
    assert compute_recent_outcome_bias([]) == 0.0
    assert compute_recent_outcome_bias([{"realised_pnl_usd": 100}]) == 0.0


def test_recent_outcome_bias_winning():
    trades = [{"realised_pnl_usd": v} for v in (100, 50, 75, -10, 200)]
    assert compute_recent_outcome_bias(trades) == 0.05


def test_recent_outcome_bias_losing():
    trades = [{"realised_pnl_usd": v} for v in (-100, -50, -75, 10, -200)]
    assert compute_recent_outcome_bias(trades) == -0.05


def test_recent_outcome_bias_neutral():
    trades = [{"realised_pnl_usd": v} for v in (100, -50, 75, -10)]
    assert compute_recent_outcome_bias(trades) == 0.0


# ---------------------------------------------------------------------------
# Sizing ladder
# ---------------------------------------------------------------------------

LADDER = [
    {"min_edge": 0.50, "base_pct": 0.02, "leverage": 2.0},
    {"min_edge": 0.60, "base_pct": 0.05, "leverage": 3.0},
    {"min_edge": 0.70, "base_pct": 0.10, "leverage": 5.0},
    {"min_edge": 0.80, "base_pct": 0.18, "leverage": 7.0},
    {"min_edge": 0.90, "base_pct": 0.28, "leverage": 10.0},
]


def test_sizing_below_floor_returns_no_trade():
    s = size_from_edge(0.45, LADDER, 1.0, 100_000, 67.42)
    assert s.rung == -1
    assert s.target_size == 0.0


def test_sizing_mid_rung():
    s = size_from_edge(0.65, LADDER, 1.0, 100_000, 67.42)
    assert s.rung == 1
    assert s.base_pct == 0.05
    assert s.leverage == 3.0
    # 100_000 * 0.05 * 1.0 * 3.0 = 15_000 notional
    assert abs(s.target_notional_usd - 15_000) < 0.1


def test_sizing_max_rung():
    s = size_from_edge(0.95, LADDER, 1.0, 100_000, 67.42)
    assert s.rung == 4
    assert s.base_pct == 0.28
    assert s.leverage == 10.0
    # 100_000 * 0.28 * 1.0 * 10 = 280_000 notional (2.8x equity)
    assert abs(s.target_notional_usd - 280_000) < 0.1


def test_sizing_multiplier_reduces_cl():
    s_brent = size_from_edge(0.8, LADDER, 1.0, 100_000, 67.42)
    s_cl = size_from_edge(0.8, LADDER, 0.6, 100_000, 67.42)
    assert abs(s_cl.target_notional_usd - s_brent.target_notional_usd * 0.6) < 0.1


def test_sizing_zero_equity_returns_zero():
    s = size_from_edge(0.95, LADDER, 1.0, 0, 67.42)
    assert s.rung == -1
    assert s.target_size == 0.0


# ---------------------------------------------------------------------------
# Gate: classification
# ---------------------------------------------------------------------------

def test_gate_classification_missing_pattern():
    r = gate_classification_ok("long", None, 0.5, 0.7)
    assert not r.passed
    assert "no BotPattern" in r.reason


def test_gate_classification_long_informed_ok():
    p = {"classification": "informed_move", "confidence": 0.7, "direction": "up"}
    r = gate_classification_ok("long", p, 0.5, 0.7)
    assert r.passed


def test_gate_classification_long_direction_mismatch():
    p = {"classification": "informed_move", "confidence": 0.7, "direction": "down"}
    r = gate_classification_ok("long", p, 0.5, 0.7)
    assert not r.passed


def test_gate_classification_short_requires_bot_driven():
    p = {"classification": "informed_move", "confidence": 0.8, "direction": "down"}
    r = gate_classification_ok("short", p, 0.5, 0.7)
    assert not r.passed
    assert "eligible" in r.reason


def test_gate_classification_short_ok():
    p = {"classification": "bot_driven_overextension", "confidence": 0.75, "direction": "down"}
    r = gate_classification_ok("short", p, 0.5, 0.7)
    assert r.passed


def test_gate_classification_short_conf_too_low():
    p = {"classification": "bot_driven_overextension", "confidence": 0.65, "direction": "down"}
    r = gate_classification_ok("short", p, 0.5, 0.7)
    assert not r.passed


# ---------------------------------------------------------------------------
# Gate: no_blocking_catalyst (shorts only)
# ---------------------------------------------------------------------------

def test_gate_catalyst_pass_when_empty():
    r = gate_no_blocking_catalyst([], 4, "short")
    assert r.passed


def test_gate_catalyst_pass_when_all_below_floor():
    cats = [{"severity": 2, "direction": "up", "category": "eia"}]
    r = gate_no_blocking_catalyst(cats, 4, "short")
    assert r.passed


def test_gate_catalyst_blocks_bullish_high_sev():
    cats = [{"severity": 5, "direction": "up", "category": "opec_cut"}]
    r = gate_no_blocking_catalyst(cats, 4, "short")
    assert not r.passed
    assert "opec_cut" in r.reason


def test_gate_catalyst_blocks_neutral_high_sev():
    cats = [{"severity": 4, "direction": "", "category": "geopolitical"}]
    r = gate_no_blocking_catalyst(cats, 4, "short")
    assert not r.passed


def test_gate_catalyst_allows_bearish():
    cats = [{"severity": 5, "direction": "down", "category": "demand_shock"}]
    r = gate_no_blocking_catalyst(cats, 4, "short")
    assert r.passed


# ---------------------------------------------------------------------------
# Gate: supply freshness
# ---------------------------------------------------------------------------

def test_gate_supply_longs_na():
    r = gate_no_fresh_supply_upgrade(None, 72, "long", _now())
    assert r.passed


def test_gate_supply_no_state_passes():
    r = gate_no_fresh_supply_upgrade(None, 72, "short", _now())
    assert r.passed


def test_gate_supply_fresh_with_disruptions_blocks_short():
    s = {
        "computed_at": (_now() - timedelta(hours=6)).isoformat(),
        "active_disruption_count": 3,
    }
    r = gate_no_fresh_supply_upgrade(s, 72, "short", _now())
    assert not r.passed


def test_gate_supply_stale_passes():
    s = {
        "computed_at": (_now() - timedelta(hours=200)).isoformat(),
        "active_disruption_count": 3,
    }
    r = gate_no_fresh_supply_upgrade(s, 72, "short", _now())
    assert r.passed


def test_gate_supply_fresh_but_zero_disruptions_passes():
    s = {
        "computed_at": (_now() - timedelta(hours=6)).isoformat(),
        "active_disruption_count": 0,
    }
    r = gate_no_fresh_supply_upgrade(s, 72, "short", _now())
    assert r.passed


# ---------------------------------------------------------------------------
# Gate: short grace period
# ---------------------------------------------------------------------------

def test_gate_grace_period_not_set_fails():
    s = StrategyState()
    r = gate_short_grace_period(s, 3600, _now())
    assert not r.passed


def test_gate_grace_period_too_soon_fails():
    s = StrategyState(enabled_since=(_now() - timedelta(minutes=30)).isoformat())
    r = gate_short_grace_period(s, 3600, _now())
    assert not r.passed


def test_gate_grace_period_cleared_passes():
    s = StrategyState(enabled_since=(_now() - timedelta(hours=2)).isoformat())
    r = gate_short_grace_period(s, 3600, _now())
    assert r.passed


# ---------------------------------------------------------------------------
# Gate: short daily loss cap
# ---------------------------------------------------------------------------

def test_gate_daily_loss_under_cap():
    s = StrategyState(daily_realised_pnl_usd=-100)
    r = gate_short_daily_loss_cap(s, 100_000, 1.5)
    assert r.passed


def test_gate_daily_loss_at_cap_blocks():
    s = StrategyState(daily_realised_pnl_usd=-1500)
    r = gate_short_daily_loss_cap(s, 100_000, 1.5)
    assert not r.passed


def test_gate_daily_loss_gain_passes():
    s = StrategyState(daily_realised_pnl_usd=5000)
    r = gate_short_daily_loss_cap(s, 100_000, 1.5)
    assert r.passed


# ---------------------------------------------------------------------------
# Gate: thesis conflict
# ---------------------------------------------------------------------------

def test_gate_thesis_no_thesis_passes():
    r = gate_thesis_conflict("long", None, "BRENTOIL", None, _now())
    assert r.passed


def test_gate_thesis_flat_passes():
    r = gate_thesis_conflict("long", {"direction": "flat"}, "BRENTOIL", None, _now())
    assert r.passed


def test_gate_thesis_same_direction_passes():
    r = gate_thesis_conflict("long", {"direction": "long"}, "BRENTOIL", None, _now())
    assert r.passed


def test_gate_thesis_opposite_direction_blocks():
    r = gate_thesis_conflict("short", {"direction": "long"}, "BRENTOIL", None, _now())
    assert not r.passed
    assert "thesis wins" in r.reason


def test_gate_thesis_lockout_expires():
    last = _now() - timedelta(hours=25)
    r = gate_thesis_conflict("short", {"direction": "long"}, "BRENTOIL", last, _now())
    # Still opposite direction, but lockout expired — result is still False
    # per plan: opposite direction always locks out. Only lockout window
    # counts as "still in lockout" messaging.
    assert not r.passed


# ---------------------------------------------------------------------------
# Drawdown brakes
# ---------------------------------------------------------------------------

def test_brakes_clear_default():
    s = StrategyState()
    blocked, reason = check_drawdown_brakes(s, 100_000, 3.0, 8.0, 15.0)
    assert not blocked


def test_daily_brake_trips():
    s = StrategyState(daily_realised_pnl_usd=-3500)
    blocked, reason = check_drawdown_brakes(s, 100_000, 3.0, 8.0, 15.0)
    assert blocked
    assert "daily brake" in reason


def test_weekly_brake_trips():
    s = StrategyState(weekly_realised_pnl_usd=-8500)
    blocked, reason = check_drawdown_brakes(s, 100_000, 3.0, 8.0, 15.0)
    assert blocked
    assert "weekly brake" in reason


def test_monthly_brake_trips():
    s = StrategyState(monthly_realised_pnl_usd=-16_000)
    blocked, reason = check_drawdown_brakes(s, 100_000, 3.0, 8.0, 15.0)
    assert blocked
    assert "monthly brake" in reason


def test_monthly_brake_manual_tripped_blocks():
    s = StrategyState(
        monthly_brake_tripped_at="2026-04-09T00:00:00+00:00",
        brake_cleared_at=None,
    )
    blocked, reason = check_drawdown_brakes(s, 100_000, 3.0, 8.0, 15.0)
    assert blocked


def test_cleared_brake_allows_trading():
    s = StrategyState(
        monthly_brake_tripped_at="2026-04-01T00:00:00+00:00",
        brake_cleared_at="2026-04-09T20:00:00+00:00",
    )
    blocked, reason = check_drawdown_brakes(s, 100_000, 3.0, 8.0, 15.0)
    assert not blocked


# ---------------------------------------------------------------------------
# Window rollover
# ---------------------------------------------------------------------------

def test_daily_window_rolls_at_utc_midnight():
    s = StrategyState(daily_window_start="2026-04-08",
                      daily_realised_pnl_usd=-500,
                      daily_brake_tripped_at="2026-04-08T23:50:00+00:00")
    reset = maybe_reset_daily_window(s, _now())  # _now = 2026-04-09
    assert reset is True
    assert s.daily_realised_pnl_usd == 0.0
    assert s.daily_brake_tripped_at is None


def test_daily_window_no_reset_same_day():
    s = StrategyState(daily_window_start="2026-04-09", daily_realised_pnl_usd=-500)
    reset = maybe_reset_daily_window(s, _now())
    assert reset is False
    assert s.daily_realised_pnl_usd == -500


def test_weekly_window_rolls():
    s = StrategyState(weekly_window_start="2026-W14", weekly_realised_pnl_usd=-900)
    # _now() is 2026-04-09 → ISO week 15
    reset = maybe_reset_weekly_window(s, _now())
    assert reset is True
    assert s.weekly_realised_pnl_usd == 0.0


def test_monthly_window_rolls():
    s = StrategyState(monthly_window_start="2026-03", monthly_realised_pnl_usd=-2000)
    reset = maybe_reset_monthly_window(s, _now())
    assert reset is True
    assert s.monthly_realised_pnl_usd == 0.0


# ---------------------------------------------------------------------------
# Funding-cost exit
# ---------------------------------------------------------------------------

def test_funding_hold_under_warn():
    action, _ = should_exit_on_funding(100, 100_000, 0.5, 1.5)
    assert action == "hold"


def test_funding_warn_between_warn_and_exit():
    action, _ = should_exit_on_funding(700, 100_000, 0.5, 1.5)
    assert action == "warn"


def test_funding_exit_above_exit():
    action, _ = should_exit_on_funding(2000, 100_000, 0.5, 1.5)
    assert action == "exit"


def test_funding_zero_notional_holds():
    action, _ = should_exit_on_funding(100, 0, 0.5, 1.5)
    assert action == "hold"


# ---------------------------------------------------------------------------
# Short hold cap
# ---------------------------------------------------------------------------

def test_short_hold_under_cap():
    entry = (_now() - timedelta(hours=10)).isoformat()
    closed, _ = short_should_force_close(entry, _now(), 24)
    assert not closed


def test_short_hold_at_cap_closes():
    entry = (_now() - timedelta(hours=25)).isoformat()
    closed, _ = short_should_force_close(entry, _now(), 24)
    assert closed


def test_short_unparseable_closes_defensively():
    closed, _ = short_should_force_close("not a date", _now(), 24)
    assert closed


# ---------------------------------------------------------------------------
# Decision + state I/O
# ---------------------------------------------------------------------------

def _decision():
    return Decision(
        id="BRENTOIL_2026-04-09T22:30:00+00:00",
        instrument="BRENTOIL",
        decided_at=_now(),
        direction="long",
        action="open",
        edge=0.72,
        classification="informed_move",
        classifier_confidence=0.72,
        thesis_conviction=0.6,
        recent_outcome_bias=0.0,
        sizing={"edge": 0.72, "rung": 2, "base_pct": 0.10, "leverage": 5.0,
                "sizing_multiplier": 1.0, "target_notional_usd": 50000,
                "target_size": 741.0},
        gate_results=[{"name": "classification", "passed": True, "reason": "ok"}],
        notes="test",
    )


def test_decision_jsonl_round_trip(tmp_path: Path):
    p = tmp_path / "d.jsonl"
    append_decision(str(p), _decision())
    rows = read_decisions(str(p))
    assert len(rows) == 1
    assert rows[0].action == "open"


def test_state_round_trip_empty(tmp_path: Path):
    p = tmp_path / "s.json"
    s = StrategyState()
    write_state_atomic(str(p), s)
    loaded = read_state(str(p))
    assert loaded.open_positions == {}


def test_state_round_trip_with_position(tmp_path: Path):
    p = tmp_path / "s.json"
    s = StrategyState(
        open_positions={"BRENTOIL": {
            "side": "long", "entry_ts": _now().isoformat(),
            "entry_price": 67.42, "size": 741.0, "leverage": 5.0,
            "cumulative_funding_usd": 0.0, "realised_pnl_today_usd": 0.0,
        }},
        daily_realised_pnl_usd=-500.0,
        daily_window_start="2026-04-09",
        enabled_since=_now().isoformat(),
    )
    write_state_atomic(str(p), s)
    loaded = read_state(str(p))
    assert loaded.open_positions["BRENTOIL"]["leverage"] == 5.0
    assert loaded.daily_realised_pnl_usd == -500.0


def test_state_read_missing_returns_default():
    s = read_state("/nonexistent/path/state.json")
    assert s.open_positions == {}
    assert s.daily_realised_pnl_usd == 0.0
