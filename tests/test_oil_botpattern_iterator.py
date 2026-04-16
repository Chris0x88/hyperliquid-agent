"""Tests for BotPatternStrategyIterator — sub-system 5 wiring."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from daemon.iterators.oil_botpattern import BotPatternStrategyIterator
from trading.oil.engine import read_decisions, read_state


def _now():
    """Real wall-clock to match iterator's datetime.now()."""
    return datetime.now(tz=timezone.utc)


def _write_config(d, *, enabled=True, shorts=False, **overrides):
    cfg = {
        "enabled": enabled,
        "short_legs_enabled": shorts,
        "short_legs_grace_period_s": 3600,
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
        "patterns_jsonl": f"{d}/bot_patterns.jsonl",
        "zones_jsonl": f"{d}/zones.jsonl",
        "cascades_jsonl": f"{d}/cascades.jsonl",
        "supply_state_json": f"{d}/supply.json",
        "catalysts_jsonl": f"{d}/catalysts.jsonl",
        "risk_caps_json": f"{d}/risk_caps.json",
        "thesis_state_path": f"{d}/thesis.json",
        "funding_tracker_jsonl": f"{d}/funding.jsonl",
        "main_journal_jsonl": f"{d}/journal.jsonl",
        "decision_journal_jsonl": f"{d}/decisions.jsonl",
        "state_json": f"{d}/state.json",
    }
    cfg.update(overrides)
    p = Path(d) / "oil_botpattern.json"
    p.write_text(json.dumps(cfg))
    # Minimal risk caps
    Path(f"{d}/risk_caps.json").write_text(json.dumps({
        "oil_botpattern": {
            "BRENTOIL": {"sizing_multiplier": 1.0, "min_atr_buffer_pct": 1.0},
            "CL": {"sizing_multiplier": 0.6, "min_atr_buffer_pct": 1.5},
        }
    }))
    return p


def _ctx(equity_usd=100_000, brentoil_price=67.42):
    from exchange.risk_manager import RiskGate
    c = MagicMock()
    c.alerts = []
    c.order_queue = []
    c.balances = {"USDC": Decimal(str(equity_usd))}
    c.total_equity = float(equity_usd)
    c.prices = {"BRENTOIL": Decimal(str(brentoil_price))}
    c.risk_gate = RiskGate.OPEN  # account-wide brake default
    return c


def _write_pattern(d, *, instrument="BRENTOIL", classification="informed_move",
                    conf=0.72, direction="up", detected_at=None):
    detected_at = detected_at or _now()
    row = {
        "id": f"{instrument}_{detected_at.isoformat()}",
        "instrument": instrument,
        "detected_at": detected_at.isoformat(),
        "lookback_minutes": 60,
        "classification": classification,
        "confidence": conf,
        "direction": direction,
        "price_at_detection": 67.42,
        "price_change_pct": 1.4 if direction == "up" else -1.4,
        "signals": ["test"],
        "notes": "test",
    }
    with Path(f"{d}/bot_patterns.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# Kill switches
# ---------------------------------------------------------------------------

def test_iterator_has_name():
    assert BotPatternStrategyIterator().name == "oil_botpattern"


def test_master_kill_switch_off(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=False)
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx()
    _write_pattern(str(tmp_path))
    it.on_start(ctx)
    it.tick(ctx)
    assert ctx.order_queue == []
    assert not Path(f"{tmp_path}/decisions.jsonl").exists()


def test_iterator_registered_in_all_three_tiers():
    """Sub-system 5 is registered in WATCH + REBALANCE + OPPORTUNISTIC.

    Previously this test asserted oil_botpattern was NOT in WATCH, back
    when the iterator was exit/write-only. With shadow mode
    (decisions_only=true), the iterator needs to tick in WATCH so Rung 1
    (shadow in WATCH) in the activation runbook actually works. WATCH
    has no execution_engine or exchange_protection, so any accidentally-
    emitted OrderIntent has no consumer anyway — double safety.
    """
    from daemon.tiers import iterators_for_tier
    assert "oil_botpattern" in iterators_for_tier("watch")
    assert "oil_botpattern" in iterators_for_tier("rebalance")
    assert "oil_botpattern" in iterators_for_tier("opportunistic")


# ---------------------------------------------------------------------------
# Long entry path
# ---------------------------------------------------------------------------

def test_long_entry_emits_order_with_sltp_meta(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=True)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.72, direction="up")
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx(equity_usd=100_000, brentoil_price=67.42)
    it.on_start(ctx)
    it.tick(ctx)

    # One order emitted
    assert len(ctx.order_queue) == 1
    order = ctx.order_queue[0]
    assert order.strategy_name == "oil_botpattern"
    assert order.instrument == "BRENTOIL"
    assert order.action == "buy"
    assert order.meta["strategy_id"] == "oil_botpattern"
    assert order.meta["intended_hold_hours"] == 12
    assert order.meta["preferred_sl_atr_mult"] == 0.8
    assert order.meta["preferred_tp_atr_mult"] == 2.0
    assert order.meta["rung"] >= 2  # edge 0.72 → rung 2 (min_edge 0.70)

    # Decision journaled
    decisions = read_decisions(f"{tmp_path}/decisions.jsonl")
    assert len(decisions) == 1
    assert decisions[0].action == "open"
    assert decisions[0].direction == "long"

    # State updated
    s = read_state(f"{tmp_path}/state.json")
    assert "BRENTOIL" in s.open_positions
    assert s.open_positions["BRENTOIL"]["side"] == "long"


def test_long_skipped_when_edge_below_floor(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=True)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.45, direction="up")
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx()
    it.on_start(ctx)
    it.tick(ctx)
    assert ctx.order_queue == []
    decisions = read_decisions(f"{tmp_path}/decisions.jsonl")
    assert len(decisions) == 1
    assert decisions[0].action == "skip"


def test_long_skipped_when_classification_unclear(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=True)
    _write_pattern(str(tmp_path), classification="unclear", conf=0.8, direction="up")
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx()
    it.on_start(ctx)
    it.tick(ctx)
    assert ctx.order_queue == []


# ---------------------------------------------------------------------------
# Short entry path
# ---------------------------------------------------------------------------

def test_short_blocked_when_shorts_disabled(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=True, shorts=False)
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.8, direction="down")
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx()
    it.on_start(ctx)
    it.tick(ctx)
    assert ctx.order_queue == []
    # No decision record either — short path bails before journaling
    assert not Path(f"{tmp_path}/decisions.jsonl").exists()


def test_short_blocked_by_grace_period(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=True, shorts=True)
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.8, direction="down")
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx()
    it.on_start(ctx)  # This seeds enabled_since = now
    it.tick(ctx)      # Grace period NOT cleared (0s elapsed)
    assert ctx.order_queue == []
    decisions = read_decisions(f"{tmp_path}/decisions.jsonl")
    assert any("grace period" in str(r.gate_results) for r in decisions)


def test_short_blocked_by_catalyst(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=True, shorts=True)
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.8, direction="down")
    # Bullish catalyst pending in next 24h
    future_cat = {
        "id": "cat-001", "severity": 5, "direction": "up",
        "category": "opec_cut",
        "scheduled_at": (_now() + timedelta(hours=6)).isoformat(),
    }
    Path(f"{tmp_path}/catalysts.jsonl").write_text(json.dumps(future_cat) + "\n")
    # Clear grace period by seeding enabled_since in state
    Path(f"{tmp_path}/state.json").write_text(json.dumps({
        "open_positions": {}, "daily_realised_pnl_usd": 0.0,
        "weekly_realised_pnl_usd": 0.0, "monthly_realised_pnl_usd": 0.0,
        "daily_window_start": "", "weekly_window_start": "",
        "monthly_window_start": "",
        "daily_brake_tripped_at": None, "weekly_brake_tripped_at": None,
        "monthly_brake_tripped_at": None, "brake_cleared_at": None,
        "enabled_since": (_now() - timedelta(hours=2)).isoformat(),
    }))
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx()
    it.on_start(ctx)
    it.tick(ctx)
    assert ctx.order_queue == []
    decisions = read_decisions(f"{tmp_path}/decisions.jsonl")
    assert len(decisions) == 1
    assert decisions[0].action == "skip"
    assert any("opec_cut" in g.get("reason", "") for g in decisions[0].gate_results)


def test_short_happy_path(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=True, shorts=True)
    _write_pattern(str(tmp_path), classification="bot_driven_overextension",
                    conf=0.85, direction="down")
    # Clear grace period
    Path(f"{tmp_path}/state.json").write_text(json.dumps({
        "open_positions": {}, "daily_realised_pnl_usd": 0.0,
        "weekly_realised_pnl_usd": 0.0, "monthly_realised_pnl_usd": 0.0,
        "daily_window_start": "", "weekly_window_start": "",
        "monthly_window_start": "",
        "daily_brake_tripped_at": None, "weekly_brake_tripped_at": None,
        "monthly_brake_tripped_at": None, "brake_cleared_at": None,
        "enabled_since": (_now() - timedelta(hours=2)).isoformat(),
    }))
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx()
    it.on_start(ctx)
    it.tick(ctx)

    # Must have emitted a sell
    assert len(ctx.order_queue) == 1
    order = ctx.order_queue[0]
    assert order.action == "sell"
    assert order.strategy_name == "oil_botpattern"
    # Warning alert on every short open
    assert any("SHORT" in a.message for a in ctx.alerts)


# ---------------------------------------------------------------------------
# Thesis conflict
# ---------------------------------------------------------------------------

def test_long_blocked_by_opposite_thesis(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=True)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.8, direction="up")
    # Thesis says short
    Path(f"{tmp_path}/thesis.json").write_text(json.dumps({
        "direction": "short", "conviction": 0.7,
    }))
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx()
    it.on_start(ctx)
    it.tick(ctx)
    assert ctx.order_queue == []
    decisions = read_decisions(f"{tmp_path}/decisions.jsonl")
    assert any("thesis wins" in g.get("reason", "") for g in decisions[0].gate_results)


def test_long_stacks_on_same_direction_thesis(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=True)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.75, direction="up")
    Path(f"{tmp_path}/thesis.json").write_text(json.dumps({
        "direction": "long", "conviction": 0.8,
    }))
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx()
    it.on_start(ctx)
    it.tick(ctx)
    assert len(ctx.order_queue) == 1
    assert ctx.order_queue[0].action == "buy"


# ---------------------------------------------------------------------------
# Drawdown brakes
# ---------------------------------------------------------------------------

def test_daily_brake_blocks_new_entries(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=True)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.8, direction="up")
    # Seed state with daily loss > 3%
    Path(f"{tmp_path}/state.json").write_text(json.dumps({
        "open_positions": {}, "daily_realised_pnl_usd": -3500.0,
        "weekly_realised_pnl_usd": -3500.0, "monthly_realised_pnl_usd": -3500.0,
        "daily_window_start": _now().strftime("%Y-%m-%d"),
        "weekly_window_start": "", "monthly_window_start": "",
        "daily_brake_tripped_at": None, "weekly_brake_tripped_at": None,
        "monthly_brake_tripped_at": None, "brake_cleared_at": None,
        "enabled_since": (_now() - timedelta(hours=5)).isoformat(),
    }))
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx(equity_usd=100_000)
    it.on_start(ctx)
    it.tick(ctx)
    assert ctx.order_queue == []


# ---------------------------------------------------------------------------
# Existing position management
# ---------------------------------------------------------------------------

def test_short_force_close_on_hold_cap(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=True, shorts=True)
    # Short opened 25h ago
    Path(f"{tmp_path}/state.json").write_text(json.dumps({
        "open_positions": {
            "BRENTOIL": {
                "side": "short",
                "entry_ts": (_now() - timedelta(hours=25)).isoformat(),
                "entry_price": 68.50, "size": 500.0, "leverage": 5.0,
                "cumulative_funding_usd": 0.0,
                "realised_pnl_today_usd": 0.0,
            }
        },
        "daily_realised_pnl_usd": 0.0, "weekly_realised_pnl_usd": 0.0,
        "monthly_realised_pnl_usd": 0.0,
        "daily_window_start": "", "weekly_window_start": "",
        "monthly_window_start": "",
        "daily_brake_tripped_at": None, "weekly_brake_tripped_at": None,
        "monthly_brake_tripped_at": None, "brake_cleared_at": None,
        "enabled_since": (_now() - timedelta(hours=30)).isoformat(),
    }))
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx()
    it.on_start(ctx)
    it.tick(ctx)
    # Close order emitted
    close_orders = [o for o in ctx.order_queue if o.action == "close"]
    assert len(close_orders) == 1
    assert close_orders[0].reduce_only


def test_long_funding_exit(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=True)
    Path(f"{tmp_path}/state.json").write_text(json.dumps({
        "open_positions": {
            "BRENTOIL": {
                "side": "long",
                "entry_ts": (_now() - timedelta(days=10)).isoformat(),
                "entry_price": 67.00, "size": 1000.0, "leverage": 5.0,
                "cumulative_funding_usd": 0.0,
                "realised_pnl_today_usd": 0.0,
            }
        },
        "daily_realised_pnl_usd": 0.0, "weekly_realised_pnl_usd": 0.0,
        "monthly_realised_pnl_usd": 0.0,
        "daily_window_start": "", "weekly_window_start": "",
        "monthly_window_start": "",
        "daily_brake_tripped_at": None, "weekly_brake_tripped_at": None,
        "monthly_brake_tripped_at": None, "brake_cleared_at": None,
        "enabled_since": (_now() - timedelta(days=11)).isoformat(),
    }))
    # Funding tracker says we've paid 2% of notional (67000 * 0.02 = 1340)
    Path(f"{tmp_path}/funding.jsonl").write_text(json.dumps({
        "instrument": "BRENTOIL",
        "cumulative_usd": 1400.0,
    }) + "\n")
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx()
    it.on_start(ctx)
    it.tick(ctx)
    # Exit triggered by funding
    close_orders = [o for o in ctx.order_queue if o.action == "close"]
    assert len(close_orders) == 1


# ---------------------------------------------------------------------------
# Decision journal always written
# ---------------------------------------------------------------------------

def test_decision_journaled_even_on_skip(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=True)
    _write_pattern(str(tmp_path), classification="informed_move", conf=0.45, direction="up")
    it = BotPatternStrategyIterator(config_path=str(cfg))
    ctx = _ctx()
    it.on_start(ctx)
    it.tick(ctx)
    decisions = read_decisions(f"{tmp_path}/decisions.jsonl")
    assert len(decisions) == 1
    assert decisions[0].action == "skip"
