"""Tests for sub-system 5 iterator's shadow (decisions_only) mode.

Shadow mode runs the full gate chain + sizing but never emits
OrderIntents. Instead it opens paper positions, marks them to market
each tick against ctx.prices, closes on SL/TP hits, and emits Telegram
alerts on every open + close with PnL + running balance.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from cli.daemon.iterators.oil_botpattern import BotPatternStrategyIterator
from modules.oil_botpattern_paper import balance_from_dict, position_from_dict


def _now():
    return datetime.now(tz=timezone.utc)


def _write_config(d, *, decisions_only=True, brentoil_price=67.42, **overrides):
    cfg = {
        "enabled": True,
        "short_legs_enabled": False,
        "short_legs_grace_period_s": 3600,
        "decisions_only": decisions_only,
        "shadow_seed_balance_usd": 100_000.0,
        "shadow_sl_pct": 2.0,
        "shadow_tp_pct": 5.0,
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


def _ctx(*, equity_usd=100_000, brentoil_price=67.42):
    c = MagicMock()
    c.alerts = []
    c.order_queue = []
    c.balances = {"USDC": Decimal(str(equity_usd))}
    c.prices = {"BRENTOIL": Decimal(str(brentoil_price))}
    return c


def _write_pattern(d, *, classification="informed_move", conf=0.72,
                    direction="up", price=67.42):
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
# Shadow mode entry — no OrderIntent, opens paper position, emits alert
# ---------------------------------------------------------------------------

def test_shadow_mode_does_not_emit_order_intent(tmp_path):
    cfg = _write_config(str(tmp_path), decisions_only=True)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.72, direction="up")
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx(brentoil_price=67.42)
    it.on_start(ctx)
    it.tick(ctx)

    # No real orders
    assert ctx.order_queue == []

    # But a shadow-open alert WAS emitted
    open_alerts = [a for a in ctx.alerts if "SHADOW OPEN" in a.message]
    assert len(open_alerts) == 1
    assert "BRENTOIL" in open_alerts[0].message
    assert open_alerts[0].data.get("shadow") is True
    assert open_alerts[0].data.get("instrument") == "BRENTOIL"


def test_shadow_mode_persists_position_file(tmp_path):
    cfg = _write_config(str(tmp_path), decisions_only=True)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.72, direction="up")
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx(brentoil_price=67.42)
    it.on_start(ctx)
    it.tick(ctx)

    # Shadow positions file written
    pos_path = Path(f"{tmp_path}/shadow_positions.json")
    assert pos_path.exists()
    data = json.loads(pos_path.read_text())
    assert len(data["positions"]) == 1
    pos = position_from_dict(data["positions"][0])
    assert pos.instrument == "BRENTOIL"
    assert pos.side == "long"
    assert pos.entry_price == 67.42
    # Stop/TP computed from fixed pct
    assert pos.stop_price == round(67.42 * 0.98, 10) or abs(pos.stop_price - 67.42 * 0.98) < 1e-6
    assert abs(pos.tp_price - 67.42 * 1.05) < 1e-6


def test_shadow_mode_does_not_stack_same_instrument(tmp_path):
    cfg = _write_config(str(tmp_path), decisions_only=True)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.72, direction="up")
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx(brentoil_price=67.42)
    it.on_start(ctx)
    it.tick(ctx)

    # Second tick with a new pattern — should NOT open a second shadow
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.80, direction="up")
    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=68.00)
    it.tick(ctx2)

    data = json.loads(Path(f"{tmp_path}/shadow_positions.json").read_text())
    assert len(data["positions"]) == 1


# ---------------------------------------------------------------------------
# Shadow mode exits — SL hit, TP hit
# ---------------------------------------------------------------------------

def test_shadow_mode_closes_on_tp_hit(tmp_path):
    cfg = _write_config(str(tmp_path), decisions_only=True)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))

    # First tick: open shadow at 67.00
    ctx1 = _ctx(brentoil_price=67.00)
    it.on_start(ctx1)
    it.tick(ctx1)
    assert any("SHADOW OPEN" in a.message for a in ctx1.alerts)

    # Second tick: price rips up past TP (5% ≈ 70.35)
    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=71.00)
    it.tick(ctx2)

    close_alerts = [a for a in ctx2.alerts if "SHADOW TP" in a.message]
    assert len(close_alerts) == 1
    assert "BRENTOIL" in close_alerts[0].message
    # Winning close
    assert close_alerts[0].data["exit_reason"] == "tp_hit"
    assert close_alerts[0].data["realised_pnl_usd"] > 0

    # Shadow trade appended
    trades_path = Path(f"{tmp_path}/shadow_trades.jsonl")
    assert trades_path.exists()
    rows = [json.loads(l) for l in trades_path.read_text().splitlines() if l]
    assert len(rows) == 1
    assert rows[0]["exit_reason"] == "tp_hit"

    # Balance updated
    balance = balance_from_dict(json.loads(Path(f"{tmp_path}/shadow_balance.json").read_text()))
    assert balance.closed_trades == 1
    assert balance.wins == 1
    assert balance.current_balance_usd > 100_000


def test_shadow_mode_closes_on_sl_hit(tmp_path):
    cfg = _write_config(str(tmp_path), decisions_only=True)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))

    ctx1 = _ctx(brentoil_price=67.00)
    it.on_start(ctx1)
    it.tick(ctx1)

    # Price drops past SL (2% below ≈ 65.66)
    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=65.00)
    it.tick(ctx2)

    close_alerts = [a for a in ctx2.alerts if "SHADOW SL" in a.message]
    assert len(close_alerts) == 1
    assert close_alerts[0].severity == "warning"
    assert close_alerts[0].data["realised_pnl_usd"] < 0

    balance = balance_from_dict(json.loads(Path(f"{tmp_path}/shadow_balance.json").read_text()))
    assert balance.closed_trades == 1
    assert balance.losses == 1
    assert balance.current_balance_usd < 100_000


def test_shadow_mode_balance_included_in_alerts(tmp_path):
    cfg = _write_config(str(tmp_path), decisions_only=True)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))

    ctx1 = _ctx(brentoil_price=67.00)
    it.on_start(ctx1)
    it.tick(ctx1)

    open_alert = [a for a in ctx1.alerts if "SHADOW OPEN" in a.message][0]
    assert "balance:" in open_alert.message
    assert "$100,000" in open_alert.message  # seed balance in open alert

    # Close at TP
    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=71.00)
    it.tick(ctx2)
    close_alert = [a for a in ctx2.alerts if "SHADOW TP" in a.message][0]
    assert "balance:" in close_alert.message
    assert "WR" in close_alert.message  # win rate in close alert


# ---------------------------------------------------------------------------
# Mode coexistence
# ---------------------------------------------------------------------------

def test_live_mode_still_emits_order_when_decisions_only_false(tmp_path):
    cfg = _write_config(str(tmp_path), decisions_only=False)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.72, direction="up")
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx(brentoil_price=67.42)
    it.on_start(ctx)
    it.tick(ctx)

    # Live OrderIntent emitted
    assert len(ctx.order_queue) == 1
    assert ctx.order_queue[0].action == "buy"
    # No shadow position file
    assert not Path(f"{tmp_path}/shadow_positions.json").exists()


def test_shadow_positions_continue_to_be_managed_after_mode_flip(tmp_path):
    """If an operator flips decisions_only off while a shadow position is
    open, the iterator should still mark + potentially close it (not
    orphan it forever)."""
    cfg = _write_config(str(tmp_path), decisions_only=True)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.72, direction="up", price=67.00)
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx1 = _ctx(brentoil_price=67.00)
    it.on_start(ctx1)
    it.tick(ctx1)
    assert Path(f"{tmp_path}/shadow_positions.json").exists()

    # Flip to live mode
    raw = json.loads(cfg.read_text())
    raw["decisions_only"] = False
    cfg.write_text(json.dumps(raw))

    # Price rips past TP — shadow should still close
    it._last_poll_mono = 0.0
    ctx2 = _ctx(brentoil_price=71.00)
    it.tick(ctx2)

    close_alerts = [a for a in ctx2.alerts if "SHADOW" in a.message]
    assert len(close_alerts) >= 1


# ---------------------------------------------------------------------------
# Decision journal still written regardless of mode
# ---------------------------------------------------------------------------

def test_decision_journal_written_in_shadow_mode(tmp_path):
    cfg = _write_config(str(tmp_path), decisions_only=True)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.72, direction="up")
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx(brentoil_price=67.42)
    it.on_start(ctx)
    it.tick(ctx)

    from modules.oil_botpattern import read_decisions
    decisions = read_decisions(f"{tmp_path}/decisions.jsonl")
    assert len(decisions) == 1
    assert decisions[0].action == "open"
