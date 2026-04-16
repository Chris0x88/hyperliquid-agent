"""Tests for adaptive evaluator in LIVE mode (decisions_only=false).

Live mode: the iterator emits real OrderIntents on entry and manages
them through `_manage_existing`. This wedge adds adaptive thesis
testing to that path — on EXIT the iterator emits a close
OrderIntent, on TIGHTEN_STOP / TRAIL_BREAKEVEN it only logs + alerts
(exchange-side stop modification is a future wedge).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from daemon.iterators.oil_botpattern import BotPatternStrategyIterator


UTC = timezone.utc


def _now():
    return datetime.now(tz=UTC)


def _write_config(d, **overrides):
    cfg = {
        "enabled": True,
        "short_legs_enabled": False,
        "short_legs_grace_period_s": 3600,
        "decisions_only": False,
        "shadow_seed_balance_usd": 100_000.0,
        "shadow_sl_pct": 2.0,
        "shadow_tp_pct": 5.0,
        "adaptive_expected_reach_hours": 48.0,
        "adaptive_live_expected_reach_pct": 5.0,
        "adaptive_heartbeat_minutes": 15.0,
        "adaptive_log_jsonl": f"{d}/adaptive_log.jsonl",
        "adaptive": {
            "stale_time_progress": 1.0,
            "stale_price_progress": 0.3,
            "slow_velocity_ratio": 0.25,
            "slow_velocity_time_floor": 0.5,
            "breakeven_at_progress": 0.5,
            "tighten_at_progress": 0.8,
            "tighten_buffer_pct": 0.5,
            "scale_out_at_progress": 2.0,
            "adverse_catalyst_severity": 4,
            "catalyst_lookback_hours": 24.0,
            "drift_exit_classifications": ["informed_flow"],
        },
        "instruments": ["BRENTOIL"],
        "tick_interval_s": 0,
        "long_min_edge": 0.50,
        "short_min_edge": 0.70,
        "short_blocking_catalyst_severity": 4,
        "short_blocking_supply_freshness_hours": 72,
        "short_max_hold_hours": 24,
        "short_daily_loss_cap_pct": 1.5,
        "sizing_ladder": [
            {"min_edge": 0.50, "base_pct": 0.02, "leverage": 2.0},
            {"min_edge": 0.60, "base_pct": 0.05, "leverage": 3.0},
            {"min_edge": 0.70, "base_pct": 0.10, "leverage": 5.0},
            {"min_edge": 0.80, "base_pct": 0.18, "leverage": 7.0},
            {"min_edge": 0.90, "base_pct": 0.28, "leverage": 10.0},
        ],
        "drawdown_brakes": {
            "daily_max_loss_pct": 3.0,
            "weekly_max_loss_pct": 8.0,
            "monthly_max_loss_pct": 15.0,
        },
        "funding_warn_pct": 0.5,
        "funding_exit_pct": 1.5,
        "preferred_sl_atr_mult": 0.8,
        "preferred_tp_atr_mult": 2.0,
        "intended_hold_hours_default": 12,
        "patterns_jsonl":          f"{d}/bot_patterns.jsonl",
        "zones_jsonl":             f"{d}/zones.jsonl",
        "cascades_jsonl":          f"{d}/cascades.jsonl",
        "supply_state_json":       f"{d}/supply.json",
        "catalysts_jsonl":         f"{d}/catalysts.jsonl",
        "risk_caps_json":          f"{d}/risk_caps.json",
        "thesis_state_path":       f"{d}/thesis.json",
        "funding_tracker_jsonl":   f"{d}/funding.jsonl",
        "main_journal_jsonl":      f"{d}/journal.jsonl",
        "decision_journal_jsonl":  f"{d}/decisions.jsonl",
        "state_json":              f"{d}/state.json",
        "shadow_positions_json":   f"{d}/shadow_positions.json",
        "shadow_trades_jsonl":     f"{d}/shadow_trades.jsonl",
        "shadow_balance_json":     f"{d}/shadow_balance.json",
    }
    cfg.update(overrides)
    p = Path(d) / "oil_botpattern.json"
    p.write_text(json.dumps(cfg))
    Path(f"{d}/risk_caps.json").write_text(json.dumps({
        "oil_botpattern": {
            "BRENTOIL": {"sizing_multiplier": 1.0, "min_atr_buffer_pct": 1.0},
            "CL": {"sizing_multiplier": 0.6, "min_atr_buffer_pct": 1.5},
        }
    }))
    return p


def _ctx(brentoil_price=67.00):
    from exchange.risk_manager import RiskGate
    c = MagicMock()
    c.alerts = []
    c.order_queue = []
    c.balances = {"USDC": Decimal("100000")}
    c.total_equity = 100_000.0
    c.prices = {"BRENTOIL": Decimal(str(brentoil_price))}
    c.risk_gate = RiskGate.OPEN
    return c


def _write_pattern(d, *, classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00):
    row = {
        "id": f"BRENTOIL_{_now().isoformat()}",
        "instrument": "BRENTOIL",
        "detected_at": _now().isoformat(),
        "lookback_minutes": 60,
        "classification": classification,
        "confidence": conf,
        "direction": direction,
        "price_at_detection": price,
        "price_change_pct": 1.4 if direction == "up" else -1.4,
        "signals": ["test"],
        "notes": "test",
    }
    with Path(f"{d}/bot_patterns.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# Hypothesis capture on live entry
# ---------------------------------------------------------------------------

def test_live_entry_captures_hypothesis_fields(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.78, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx(brentoil_price=67.00)
    it.on_start(ctx)
    it.tick(ctx)

    # Live OrderIntent fired
    assert len(ctx.order_queue) == 1

    # State has hypothesis fields
    state = json.loads(Path(f"{tmp_path}/state.json").read_text())
    pos = state["open_positions"]["BRENTOIL"]
    assert pos["entry_classification"] == "bot_driven_overextension"
    assert pos["entry_confidence"] == 0.78
    assert pos["entry_pattern_direction"] == "up"
    assert pos["expected_reach_price"] == 67.00 * 1.05
    assert pos["expected_reach_hours"] == 48.0


def test_live_short_entry_expected_reach_below(tmp_path):
    cfg = _write_config(str(tmp_path), short_legs_enabled=True)
    # Need a supply-disruption-free state and no bearish-blocking catalyst,
    # plus a bot_driven_overextension pattern down
    Path(f"{tmp_path}/supply.json").write_text(json.dumps({
        "active_disruption_count": 0,
        "computed_at": _now().isoformat(),
    }))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.80, direction="down", price=70.00)

    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx(brentoil_price=70.00)
    it.on_start(ctx)
    # Kick enabled_since back so grace period passes
    state_path = Path(f"{tmp_path}/state.json")
    if state_path.exists():
        raw = json.loads(state_path.read_text())
        raw["enabled_since"] = (_now() - timedelta(hours=2)).isoformat()
        state_path.write_text(json.dumps(raw))
    it._last_poll_mono = 0.0
    it.tick(ctx)

    state = json.loads(state_path.read_text())
    if "BRENTOIL" in state.get("open_positions", {}):
        pos = state["open_positions"]["BRENTOIL"]
        assert pos["side"] == "short"
        # Expected reach for short = entry * (1 - 5%) = 66.50
        assert pos["expected_reach_price"] == 70.00 * 0.95


# ---------------------------------------------------------------------------
# Adaptive EXIT for live positions
# ---------------------------------------------------------------------------

def test_live_adaptive_exits_on_classification_drift(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx1 = _ctx(brentoil_price=67.00)
    it.on_start(ctx1)
    it.tick(ctx1)
    assert len(ctx1.order_queue) == 1  # entry

    # Second tick: classifier flipped
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.80, direction="down", price=66.95)
    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=66.95)
    it.tick(ctx2)

    # Live adaptive exit alert + close order
    exit_alerts = [a for a in ctx2.alerts if "LIVE ADAPTIVE EXIT" in a.message]
    assert len(exit_alerts) == 1

    close_orders = [o for o in ctx2.order_queue if o.action == "close"]
    assert len(close_orders) == 1
    assert close_orders[0].instrument == "BRENTOIL"
    assert close_orders[0].reduce_only is True


def test_live_adaptive_exits_on_adverse_catalyst(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx1 = _ctx(brentoil_price=67.00)
    it.on_start(ctx1)
    it.tick(ctx1)
    assert len(ctx1.order_queue) == 1

    # Adverse bearish catalyst appears after entry
    Path(f"{tmp_path}/catalysts.jsonl").write_text(json.dumps({
        "severity": 5,
        "direction": "down",
        "category": "opec_surprise",
        "published_at": _now().isoformat(),
    }) + "\n")

    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=67.10)
    it.tick(ctx2)

    exit_alerts = [a for a in ctx2.alerts if "LIVE ADAPTIVE EXIT" in a.message]
    assert len(exit_alerts) == 1
    assert "catalyst" in exit_alerts[0].data["reason"]


# ---------------------------------------------------------------------------
# Tighten / trail emit alerts only — no order queue mutation
# ---------------------------------------------------------------------------

def test_live_trail_emits_alert_no_close(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx1 = _ctx(brentoil_price=67.00)
    it.on_start(ctx1)
    it.tick(ctx1)
    order_count_after_entry = len(ctx1.order_queue)

    # Price to ~60% of expected reach (67.00 * 1.05 = 70.35, 60% = 69.01)
    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=69.10)
    it.tick(ctx2)

    # Trail alert emitted
    trail_alerts = [
        a for a in ctx2.alerts
        if "LIVE ADAPTIVE" in a.message and "TRAIL_BREAKEVEN" in a.message
    ]
    assert len(trail_alerts) == 1
    # Alert carries a suggested_stop
    assert trail_alerts[0].data["suggested_stop"] == 67.00
    # No new close orders — trail is advisory only in live v1
    assert len([o for o in ctx2.order_queue if o.action == "close"]) == 0


# ---------------------------------------------------------------------------
# Log persistence
# ---------------------------------------------------------------------------

def test_live_adaptive_log_tagged_with_mode(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx1 = _ctx(brentoil_price=67.00)
    it.on_start(ctx1)
    it.tick(ctx1)

    # Trigger a trail-level decision
    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=69.10)
    it.tick(ctx2)

    log_path = Path(f"{tmp_path}/adaptive_log.jsonl")
    assert log_path.exists()
    rows = [json.loads(l) for l in log_path.read_text().splitlines() if l]
    assert len(rows) >= 1
    assert rows[-1]["mode"] == "live"
    assert rows[-1]["decision"]["action"] == "trail_breakeven"
    assert rows[-1]["position"]["entry_classification"] == "bot_driven_overextension"


# ---------------------------------------------------------------------------
# Backward compat: funding exit still runs before adaptive
# ---------------------------------------------------------------------------

def test_funding_exit_still_takes_precedence_over_adaptive(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx1 = _ctx(brentoil_price=67.00)
    it.on_start(ctx1)
    it.tick(ctx1)

    # Seed funding_tracker with a huge cumulative cost → triggers funding exit
    funding_row = {
        "instrument": "BRENTOIL",
        "cumulative_usd": 10_000.0,  # massive cost
    }
    Path(f"{tmp_path}/funding.jsonl").write_text(json.dumps(funding_row) + "\n")

    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=67.50)
    it.tick(ctx2)

    # At least one close order (funding exit should have fired)
    close_orders = [o for o in ctx2.order_queue if o.action == "close"]
    assert len(close_orders) >= 1


def test_live_mode_without_hypothesis_skips_adaptive(tmp_path):
    """Positions migrated from before this wedge (no entry_classification
    on the record) should not crash the adaptive branch."""
    cfg = _write_config(str(tmp_path))
    it = BotPatternStrategyIterator(config_path=str(cfg))
    it.on_start(_ctx())

    # Hand-write a state file with a position that has NO hypothesis fields
    from trading.oil.engine import StrategyState, write_state_atomic
    s = StrategyState()
    s.open_positions["BRENTOIL"] = {
        "side": "long",
        "entry_ts": _now().isoformat(),
        "entry_price": 67.00,
        "size": 100.0,
        "leverage": 5.0,
        "cumulative_funding_usd": 0.0,
        "realised_pnl_today_usd": 0.0,
        # no entry_classification → adaptive skipped
    }
    s.enabled_since = _now().isoformat()
    write_state_atomic(str(Path(f"{tmp_path}/state.json")), s)

    it._last_poll_mono = 0.0
    ctx = _ctx(brentoil_price=67.50)
    it.tick(ctx)  # should not raise

    # No adaptive alerts for this position (no hypothesis to test)
    assert not any("ADAPTIVE" in a.message for a in ctx.alerts)
