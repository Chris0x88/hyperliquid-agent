"""Tests for common.heartbeat_config — config loading with hardcoded defaults."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from common.heartbeat_config import (
    EscalationConfig,
    HeartbeatConfig,
    MarketMapping,
    ProfitRules,
    SpikeConfig,
    load_config,
)


# ── 1. Defaults when no files exist ──────────────────────────────────────────

def test_load_config_defaults_when_no_files():
    """load_config returns hardcoded defaults when config dir doesn't exist."""
    cfg = load_config(config_dir=Path("/tmp/nonexistent_heartbeat_dir_xyz"))
    assert isinstance(cfg, HeartbeatConfig)
    assert isinstance(cfg.escalation, EscalationConfig)
    assert isinstance(cfg.spike_config, SpikeConfig)
    # Should have default markets
    assert "xyz:BRENTOIL" in cfg.markets
    assert "BTC-PERP" in cfg.markets
    # Should have default profit rules
    assert "xyz:BRENTOIL" in cfg.profit_rules
    assert "BTC-PERP" in cfg.profit_rules


# ── 2. JSON overrides work ───────────────────────────────────────────────────

def test_load_config_from_files(tmp_path: Path):
    """JSON files override hardcoded defaults."""
    esc = {"liq_L1_alert_pct": 15, "drawdown_L1_pct": 7}
    (tmp_path / "escalation_config.json").write_text(json.dumps(esc))

    pr = {"xyz:BRENTOIL": {"quick_profit_pct": 6.5}}
    (tmp_path / "profit_rules.json").write_text(json.dumps(pr))

    mkt = {
        "ETH-PERP": {"canonical_id": "ETH-PERP", "hl_coin": "ETH"}
    }
    (tmp_path / "market_config.json").write_text(json.dumps(mkt))

    cfg = load_config(config_dir=tmp_path)

    # Overridden values
    assert cfg.escalation.liq_L1_alert_pct == 15
    assert cfg.escalation.drawdown_L1_pct == 7
    # Non-overridden values keep defaults
    assert cfg.escalation.liq_L2_deleverage_pct == 4  # widened from 8 to 4 (2026-03-31)

    # Profit rules: overridden field + defaults for rest
    oil_pr = cfg.profit_rules["xyz:BRENTOIL"]
    assert oil_pr.quick_profit_pct == 6.5
    assert oil_pr.quick_profit_window_min == 30  # default kept

    # Market added from file
    assert "ETH-PERP" in cfg.markets
    assert cfg.markets["ETH-PERP"].hl_coin == "ETH"
    # Default markets still present
    assert "BTC-PERP" in cfg.markets


# ── 3. Market config defaults ────────────────────────────────────────────────

def test_market_config_defaults():
    """Default markets have correct API mappings."""
    cfg = load_config(config_dir=Path("/tmp/nonexistent_heartbeat_dir_xyz"))

    oil = cfg.markets["xyz:BRENTOIL"]
    assert oil.canonical_id == "xyz:BRENTOIL"
    assert oil.hl_coin == "BRENTOIL"
    assert oil.dex == "xyz"

    btc = cfg.markets["BTC-PERP"]
    assert btc.canonical_id == "BTC-PERP"
    assert btc.hl_coin == "BTC"
    assert btc.dex is None

    # get_market for known market
    assert cfg.get_market("xyz:BRENTOIL").hl_coin == "BRENTOIL"
    # get_market for unknown returns sensible default
    unknown = cfg.get_market("UNKNOWN-COIN")
    assert unknown.canonical_id == "UNKNOWN-COIN"
    assert unknown.hl_coin == "UNKNOWN-COIN"


# ── 4. Profit rules defaults ────────────────────────────────────────────────

def test_profit_rules_defaults():
    """Per-market profit rules have sensible defaults."""
    cfg = load_config(config_dir=Path("/tmp/nonexistent_heartbeat_dir_xyz"))

    oil_pr = cfg.profit_rules["xyz:BRENTOIL"]
    assert oil_pr.quick_profit_pct == 5.0
    assert oil_pr.quick_profit_window_min == 30
    assert oil_pr.quick_profit_take_pct == 25
    assert oil_pr.extended_profit_pct == 10.0
    assert oil_pr.extended_profit_window_min == 120
    assert oil_pr.extended_profit_take_pct == 25

    btc_pr = cfg.profit_rules["BTC-PERP"]
    assert btc_pr.quick_profit_pct == 8.0
    assert btc_pr.quick_profit_window_min == 60
    assert btc_pr.quick_profit_take_pct == 20
    assert btc_pr.extended_profit_pct == 15.0
    assert btc_pr.extended_profit_window_min == 240
    assert btc_pr.extended_profit_take_pct == 25

    # get_profit_rules for unknown returns generic defaults
    generic = cfg.get_profit_rules("UNKNOWN-COIN")
    assert generic.quick_profit_pct == 5.0


# ── 5. ATR config ───────────────────────────────────────────────────────────

def test_atr_config():
    """ATR defaults: 4h candles, 14-period, 1h cache."""
    cfg = load_config(config_dir=Path("/tmp/nonexistent_heartbeat_dir_xyz"))
    assert cfg.atr_interval == "4h"
    assert cfg.atr_period == 14
    assert cfg.atr_cache_seconds == 3600


# ── 6. Spike config defaults ────────────────────────────────────────────────

def test_spike_config_defaults():
    """Spike/dip thresholds are sensible."""
    cfg = load_config(config_dir=Path("/tmp/nonexistent_heartbeat_dir_xyz"))
    sc = cfg.spike_config

    assert sc.spike_profit_threshold_pct == 3.0
    assert sc.spike_window_min == 10
    assert sc.spike_take_pct == 15
    assert sc.dip_threshold_pct == 2.0
    assert sc.dip_add_pct == 10
    assert sc.dip_add_min_liq_pct == 12
    assert sc.dip_add_max_drawdown_pct == 3
    assert sc.dip_add_cooldown_min == 120


# ── 7. Corrupt JSON uses defaults ───────────────────────────────────────────

def test_corrupt_json_uses_defaults(tmp_path: Path):
    """Corrupt JSON files log warning and fall back to defaults."""
    (tmp_path / "escalation_config.json").write_text("{invalid json!!!")
    cfg = load_config(config_dir=tmp_path)
    # Should still get valid defaults
    assert cfg.escalation.liq_L1_alert_pct == 6  # widened from 10 to 6 (2026-03-31)
    assert isinstance(cfg.escalation, EscalationConfig)
