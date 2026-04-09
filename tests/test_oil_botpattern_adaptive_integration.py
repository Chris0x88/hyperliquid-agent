"""Tests for adaptive evaluator wired into sub-system 5 iterator.

These verify the full chain: ShadowPosition captures hypothesis at
entry → adaptive_evaluate runs on each subsequent tick → non-HOLD
actions trigger close/stop mutations + Telegram alerts →
AdaptiveLogEntry rows land in the training log JSONL.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from cli.daemon.iterators.oil_botpattern import BotPatternStrategyIterator
from modules.oil_botpattern_paper import position_from_dict


UTC = timezone.utc


def _now():
    return datetime.now(tz=UTC)


def _write_config(d, *, adaptive_overrides=None, **overrides):
    adapt = {
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
    }
    if adaptive_overrides:
        adapt.update(adaptive_overrides)
    cfg = {
        "enabled": True,
        "short_legs_enabled": False,
        "short_legs_grace_period_s": 3600,
        "decisions_only": True,
        "shadow_seed_balance_usd": 100_000.0,
        "shadow_sl_pct": 2.0,
        "shadow_tp_pct": 5.0,
        "adaptive_expected_reach_hours": 48.0,
        "adaptive_heartbeat_minutes": 15.0,
        "adaptive_log_jsonl": f"{d}/adaptive_log.jsonl",
        "adaptive": adapt,
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
    c = MagicMock()
    c.alerts = []
    c.order_queue = []
    c.balances = {"USDC": Decimal("100000")}
    c.prices = {"BRENTOIL": Decimal(str(brentoil_price))}
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
# Hypothesis capture at entry
# ---------------------------------------------------------------------------

def test_shadow_open_captures_hypothesis_fields(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.78, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx(brentoil_price=67.00)
    it.on_start(ctx)
    it.tick(ctx)

    data = json.loads(Path(f"{tmp_path}/shadow_positions.json").read_text())
    assert len(data["positions"]) == 1
    pos = position_from_dict(data["positions"][0])
    assert pos.entry_classification == "bot_driven_overextension"
    assert pos.entry_confidence == 0.78
    assert pos.entry_pattern_direction == "up"
    assert pos.expected_reach_hours == 48.0


# ---------------------------------------------------------------------------
# Trail to break-even
# ---------------------------------------------------------------------------

def test_adaptive_trails_stop_to_breakeven_mid_window(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))

    # Open shadow at 67.00
    ctx1 = _ctx(brentoil_price=67.00)
    it.on_start(ctx1)
    it.tick(ctx1)

    # Price rises to 69.00 (~60% of the way to tp 70.35) — should trail to breakeven.
    # Using 68.675 (exactly 50%) hits a float-precision edge on the >= 0.5 check.
    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=69.00)
    it.tick(ctx2)

    trail_alerts = [a for a in ctx2.alerts if "TRAIL_BREAKEVEN" in a.message]
    assert len(trail_alerts) == 1

    data = json.loads(Path(f"{tmp_path}/shadow_positions.json").read_text())
    pos = position_from_dict(data["positions"][0])
    # Stop moved from 65.66 (2% below) up to 67.00 (entry)
    assert pos.stop_price == 67.00


# ---------------------------------------------------------------------------
# Adaptive exit on classification drift
# ---------------------------------------------------------------------------

def test_adaptive_exits_on_classification_drift(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))

    ctx1 = _ctx(brentoil_price=67.00)
    it.on_start(ctx1)
    it.tick(ctx1)

    # Write a new pattern with direction FLIPPED — classifier now says down
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.80, direction="down", price=66.90)
    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=66.90)
    it.tick(ctx2)

    exit_alerts = [a for a in ctx2.alerts if "ADAPTIVE EXIT" in a.message]
    assert len(exit_alerts) == 1
    assert "flipped" in exit_alerts[0].data["reason"]

    # Trade recorded
    trades = [
        json.loads(l)
        for l in Path(f"{tmp_path}/shadow_trades.jsonl").read_text().splitlines()
        if l
    ]
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "adaptive_exit"


# ---------------------------------------------------------------------------
# Adaptive exit on adverse catalyst appearing after entry
# ---------------------------------------------------------------------------

def test_adaptive_exits_on_adverse_catalyst(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))

    ctx1 = _ctx(brentoil_price=67.00)
    it.on_start(ctx1)
    it.tick(ctx1)

    # Write an adverse catalyst: bearish, high sev, published now
    catalyst = {
        "severity": 5,
        "direction": "down",
        "category": "opec_surprise",
        "published_at": _now().isoformat(),
    }
    Path(f"{tmp_path}/catalysts.jsonl").write_text(json.dumps(catalyst) + "\n")

    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=67.20)
    it.tick(ctx2)

    exit_alerts = [a for a in ctx2.alerts if "ADAPTIVE EXIT" in a.message]
    assert len(exit_alerts) == 1
    assert "catalyst" in exit_alerts[0].data["reason"]


# ---------------------------------------------------------------------------
# Adaptive log file
# ---------------------------------------------------------------------------

def test_adaptive_log_written_on_non_hold(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))

    ctx1 = _ctx(brentoil_price=67.00)
    it.on_start(ctx1)
    it.tick(ctx1)

    # Trigger a trail-to-breakeven
    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=69.00)
    it.tick(ctx2)

    log_path = Path(f"{tmp_path}/adaptive_log.jsonl")
    assert log_path.exists()
    rows = [json.loads(l) for l in log_path.read_text().splitlines() if l]
    assert len(rows) >= 1
    entry = rows[-1]
    # Schema assertions
    assert "logged_at" in entry
    assert entry["position"]["instrument"] == "BRENTOIL"
    assert entry["position"]["entry_classification"] == "bot_driven_overextension"
    assert "current_price" in entry["snapshot"]
    assert entry["decision"]["action"] == "trail_breakeven"
    assert entry["decision"]["new_stop_price"] == 67.00
    assert "reason" in entry["decision"]
    # Pre-featurized derived metrics present
    assert "price_progress" in entry["decision"]
    assert "time_progress" in entry["decision"]
    assert "velocity_ratio" in entry["decision"]


def test_adaptive_log_schema_has_all_three_sections(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx1 = _ctx(brentoil_price=67.00)
    it.on_start(ctx1)
    it.tick(ctx1)
    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=69.00)
    it.tick(ctx2)

    rows = [
        json.loads(l)
        for l in Path(f"{tmp_path}/adaptive_log.jsonl").read_text().splitlines()
        if l
    ]
    assert len(rows) >= 1
    row = rows[0]
    # Three top-level sections: position + snapshot + decision
    assert set(row.keys()) >= {"logged_at", "position", "snapshot", "decision"}
    # Position features are present
    pos_keys = {
        "instrument", "side", "entry_ts", "entry_price",
        "expected_reach_price", "expected_reach_hours",
        "entry_classification", "entry_confidence", "entry_pattern_direction",
    }
    assert pos_keys.issubset(row["position"].keys())
    # Snapshot features are present
    snap_keys = {
        "current_price",
        "latest_pattern_classification",
        "latest_pattern_direction",
        "latest_pattern_confidence",
        "recent_catalysts_count",
        "adverse_catalysts_count",
        "max_adverse_catalyst_severity",
    }
    assert snap_keys.issubset(row["snapshot"].keys())
    # Decision features are present (the label + derived metrics)
    decision_keys = {
        "action", "reason", "hours_held",
        "price_progress", "time_progress", "velocity_ratio",
    }
    assert decision_keys.issubset(row["decision"].keys())


# ---------------------------------------------------------------------------
# Backward compatibility: live mode unaffected
# ---------------------------------------------------------------------------

def test_live_mode_still_works_without_adaptive_branch(tmp_path):
    cfg = _write_config(str(tmp_path), decisions_only=False)
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx(brentoil_price=67.00)
    it.on_start(ctx)
    it.tick(ctx)

    # Live OrderIntent emitted
    assert len(ctx.order_queue) == 1
    assert ctx.order_queue[0].action == "buy"
    # No adaptive log in live mode (no shadow positions to evaluate)
    assert not Path(f"{tmp_path}/adaptive_log.jsonl").exists()
