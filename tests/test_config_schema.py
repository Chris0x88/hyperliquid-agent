"""Tests for common.config_schema — validates all 5 real config files."""

from __future__ import annotations

import pytest

from common.config_schema import (
    CONFIG_REGISTRY,
    EscalationConfig,
    MarketsConfig,
    OilBotPatternConfig,
    RiskCapsConfig,
    WatchlistEntry,
    load_config,
)

CONFIG_DIR = "data/config"


class TestOilBotPattern:
    def test_loads_and_validates(self):
        cfg = load_config("oil_botpattern", config_dir=CONFIG_DIR)
        assert isinstance(cfg, OilBotPatternConfig)

    def test_sizing_ladder_populated(self):
        cfg = load_config("oil_botpattern", config_dir=CONFIG_DIR)
        assert len(cfg.sizing_ladder) > 0
        assert cfg.sizing_ladder[0].min_edge > 0

    def test_adaptive_defaults(self):
        cfg = load_config("oil_botpattern", config_dir=CONFIG_DIR)
        assert cfg.adaptive.stale_time_progress == 1.0

    def test_instruments(self):
        cfg = load_config("oil_botpattern", config_dir=CONFIG_DIR)
        assert "BRENTOIL" in cfg.instruments


class TestMarkets:
    def test_loads_and_validates(self):
        cfg = load_config("markets", config_dir=CONFIG_DIR)
        assert isinstance(cfg, MarketsConfig)

    def test_has_core_markets(self):
        cfg = load_config("markets", config_dir=CONFIG_DIR)
        for sym in ("BTC", "BRENTOIL", "GOLD", "SILVER"):
            assert sym in cfg.markets, f"{sym} missing from markets config"

    def test_direction_bias_valid(self):
        cfg = load_config("markets", config_dir=CONFIG_DIR)
        for sym, spec in cfg.markets.items():
            assert spec.direction_bias in ("long_only", "short_only", "neutral")


class TestWatchlist:
    def test_loads_and_validates(self):
        entries = load_config("watchlist", config_dir=CONFIG_DIR)
        assert isinstance(entries, list)
        assert len(entries) > 0
        assert isinstance(entries[0], WatchlistEntry)

    def test_has_btc(self):
        entries = load_config("watchlist", config_dir=CONFIG_DIR)
        coins = [e.coin for e in entries]
        assert "BTC" in coins


class TestRiskCaps:
    def test_loads_and_validates(self):
        cfg = load_config("risk_caps", config_dir=CONFIG_DIR)
        assert isinstance(cfg, RiskCapsConfig)

    def test_has_brentoil(self):
        cfg = load_config("risk_caps", config_dir=CONFIG_DIR)
        assert "BRENTOIL" in cfg.oil_botpattern


class TestEscalation:
    def test_loads_and_validates(self):
        cfg = load_config("escalation", config_dir=CONFIG_DIR)
        assert isinstance(cfg, EscalationConfig)

    def test_values_match_file(self):
        cfg = load_config("escalation", config_dir=CONFIG_DIR)
        assert cfg.liq_L1_alert_pct == 6.0
        assert cfg.liq_L2_cooldown_min == 30


class TestLoadConfigErrors:
    def test_unknown_name_raises(self):
        with pytest.raises(ValueError, match="Unknown config"):
            load_config("nonexistent")

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config("oil_botpattern", config_dir="/tmp/no_such_dir")


class TestRegistry:
    def test_all_five_present(self):
        expected = {"oil_botpattern", "markets", "watchlist", "risk_caps", "escalation"}
        assert expected == set(CONFIG_REGISTRY.keys())
