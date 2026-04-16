"""Tests for sub-system 5's account-wide risk_gate integration.

The existing `risk` iterator runs a composable ProtectionChain
(MaxDrawdown + DailyLoss + StoplossGuard + Ruin) and sets
ctx.risk_gate to OPEN/COOLDOWN/CLOSED. Before this wedge, sub-system 5
ignored the gate entirely — a daily-loss trip in another strategy
wouldn't stop oil_botpattern from opening new positions. These tests
verify the fix.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from cli.daemon.iterators.oil_botpattern import BotPatternStrategyIterator
from exchange.risk_manager import RiskGate


def _now():
    return datetime.now(tz=timezone.utc)


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
        "adaptive_heartbeat_minutes": 15.0,
        "adaptive_log_jsonl": f"{d}/adaptive_log.jsonl",
        "adaptive": {},
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


def _ctx(brentoil_price=67.00, risk_gate=RiskGate.OPEN, equity_usd=100_000):
    c = MagicMock()
    c.alerts = []
    c.order_queue = []
    c.balances = {"USDC": Decimal(str(equity_usd))}
    c.total_equity = float(equity_usd)
    c.prices = {"BRENTOIL": Decimal(str(brentoil_price))}
    c.risk_gate = risk_gate
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
# _risk_gate_blocks helper
# ---------------------------------------------------------------------------

def test_risk_gate_open_does_not_block(tmp_path):
    cfg = _write_config(str(tmp_path))
    it = BotPatternStrategyIterator(config_path=str(cfg))
    it._reload_config()
    ctx = _ctx(risk_gate=RiskGate.OPEN)
    blocked, reason = it._risk_gate_blocks(ctx)
    assert blocked is False
    assert reason == ""


def test_risk_gate_cooldown_blocks(tmp_path):
    cfg = _write_config(str(tmp_path))
    it = BotPatternStrategyIterator(config_path=str(cfg))
    it._reload_config()
    ctx = _ctx(risk_gate=RiskGate.COOLDOWN)
    blocked, reason = it._risk_gate_blocks(ctx)
    assert blocked is True
    assert "COOLDOWN" in reason


def test_risk_gate_closed_blocks(tmp_path):
    cfg = _write_config(str(tmp_path))
    it = BotPatternStrategyIterator(config_path=str(cfg))
    it._reload_config()
    ctx = _ctx(risk_gate=RiskGate.CLOSED)
    blocked, reason = it._risk_gate_blocks(ctx)
    assert blocked is True
    assert "CLOSED" in reason


def test_risk_gate_missing_does_not_block(tmp_path):
    cfg = _write_config(str(tmp_path))
    it = BotPatternStrategyIterator(config_path=str(cfg))
    it._reload_config()
    c = MagicMock()
    # no risk_gate attr
    delattr(c, "risk_gate") if hasattr(c, "risk_gate") else None
    c.risk_gate = None
    blocked, _reason = it._risk_gate_blocks(c)
    assert blocked is False


# ---------------------------------------------------------------------------
# Tick-level integration: COOLDOWN blocks new entries
# ---------------------------------------------------------------------------

def test_cooldown_blocks_live_entry_emission(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))

    ctx = _ctx(brentoil_price=67.00, risk_gate=RiskGate.COOLDOWN)
    it.on_start(ctx)
    it.tick(ctx)

    # No OrderIntent emitted — gate should have blocked
    assert ctx.order_queue == []

    # Decision journal: no row written because _evaluate_entry short-circuits
    # on the brakes_blocked path BEFORE reaching append_decision. Verify with
    # the journal file.
    journal = Path(f"{tmp_path}/decisions.jsonl")
    assert not journal.exists() or journal.read_text() == ""


def test_closed_blocks_live_entry_emission(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))

    ctx = _ctx(risk_gate=RiskGate.CLOSED)
    it.on_start(ctx)
    it.tick(ctx)

    assert ctx.order_queue == []


def test_open_gate_allows_normal_entry(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))

    ctx = _ctx(risk_gate=RiskGate.OPEN)
    it.on_start(ctx)
    it.tick(ctx)

    # OrderIntent should fire (gate open, other gates should pass on this
    # synthetic pattern). At minimum: we expect at least one entry attempt
    # in the decision journal.
    from modules.oil_botpattern import read_decisions
    decisions = read_decisions(f"{tmp_path}/decisions.jsonl")
    assert len(decisions) == 1
    # Could be open or skip depending on other gates, but the gate check
    # did not block the pipeline — we got a decision row.


def test_cooldown_blocks_shadow_mode_entry_too(tmp_path):
    cfg = _write_config(str(tmp_path), decisions_only=True)
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))

    ctx = _ctx(brentoil_price=67.00, risk_gate=RiskGate.COOLDOWN)
    it.on_start(ctx)
    it.tick(ctx)

    # Shadow entry should also be blocked — paper trades mirror real
    # decisions, and the real decision here would be "don't open".
    assert not Path(f"{tmp_path}/shadow_positions.json").exists() or \
           json.loads(Path(f"{tmp_path}/shadow_positions.json").read_text())["positions"] == []
    # No shadow-open alert
    assert not any("SHADOW OPEN" in a.message for a in ctx.alerts)


def test_existing_position_management_unaffected_by_cooldown(tmp_path):
    """Gate blocks NEW entries but existing positions keep being managed
    (funding exits, adaptive exits, etc.)."""
    cfg = _write_config(str(tmp_path))
    it = BotPatternStrategyIterator(config_path=str(cfg))
    # Seed state with an open position
    from modules.oil_botpattern import StrategyState, write_state_atomic
    s = StrategyState()
    s.open_positions["BRENTOIL"] = {
        "side": "long",
        "entry_ts": _now().isoformat(),
        "entry_price": 67.00,
        "size": 100.0,
        "leverage": 5.0,
        "cumulative_funding_usd": 0.0,
        "realised_pnl_today_usd": 0.0,
        "entry_classification": "bot_driven_overextension",
        "entry_confidence": 0.72,
        "entry_pattern_direction": "up",
        "expected_reach_price": 70.35,
        "expected_reach_hours": 48.0,
        "adaptive_last_heartbeat_ts": None,
    }
    s.enabled_since = _now().isoformat()
    write_state_atomic(str(Path(f"{tmp_path}/state.json")), s)

    ctx = _ctx(risk_gate=RiskGate.COOLDOWN, brentoil_price=67.50)
    it.on_start(ctx)
    it.tick(ctx)

    # No NEW OrderIntent for entry (gate blocks)
    # But _manage_existing should have run (may or may not emit close,
    # depending on whether adaptive triggers). The important thing is
    # no crash + the existing position is still in state.
    state = json.loads(Path(f"{tmp_path}/state.json").read_text())
    assert "BRENTOIL" in state["open_positions"]
