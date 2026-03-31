"""Heartbeat config — hardcoded defaults with optional JSON file overrides."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("heartbeat.config")


# ── Sub-configs ──────────────────────────────────────────────────────────────

@dataclass
class EscalationConfig:
    liq_L1_alert_pct: float = 10
    liq_L2_deleverage_pct: float = 8
    liq_L2_deleverage_amount: float = 1
    liq_L3_emergency_pct: float = 5
    liq_L3_target_leverage: float = 3
    liq_L2_cooldown_min: int = 30
    liq_L3_cooldown_min: int = 60
    drawdown_L1_pct: float = 5
    drawdown_L2_pct: float = 8
    drawdown_L2_cut_size_pct: float = 25
    drawdown_L3_pct: float = 12
    drawdown_L3_cut_size_pct: float = 50


@dataclass
class ProfitRules:
    quick_profit_pct: float = 5.0
    quick_profit_window_min: int = 30
    quick_profit_take_pct: float = 25
    extended_profit_pct: float = 10.0
    extended_profit_window_min: int = 120
    extended_profit_take_pct: float = 25


@dataclass
class SpikeConfig:
    spike_profit_threshold_pct: float = 3.0
    spike_window_min: int = 10
    spike_take_pct: float = 15
    dip_threshold_pct: float = 2.0
    dip_add_pct: float = 10
    dip_add_min_liq_pct: float = 12
    dip_add_max_drawdown_pct: float = 3
    dip_add_cooldown_min: int = 120


@dataclass
class MarketMapping:
    canonical_id: str
    hl_coin: str
    dex: Optional[str] = None
    wallet_address: Optional[str] = None


# ── Defaults ─────────────────────────────────────────────────────────────────

def _default_markets() -> dict[str, MarketMapping]:
    return {
        "xyz:BRENTOIL": MarketMapping(
            canonical_id="xyz:BRENTOIL", hl_coin="BRENTOIL", dex="xyz",
        ),
        "BTC-PERP": MarketMapping(
            canonical_id="BTC-PERP", hl_coin="BTC",
        ),
    }


def _default_profit_rules() -> dict[str, ProfitRules]:
    return {
        "xyz:BRENTOIL": ProfitRules(
            quick_profit_pct=5.0,
            quick_profit_window_min=30,
            quick_profit_take_pct=25,
            extended_profit_pct=10.0,
            extended_profit_window_min=120,
            extended_profit_take_pct=25,
        ),
        "BTC-PERP": ProfitRules(
            quick_profit_pct=8.0,
            quick_profit_window_min=60,
            quick_profit_take_pct=20,
            extended_profit_pct=15.0,
            extended_profit_window_min=240,
            extended_profit_take_pct=25,
        ),
    }


# ── Main config ──────────────────────────────────────────────────────────────

@dataclass
class HeartbeatConfig:
    escalation: EscalationConfig = field(default_factory=EscalationConfig)
    profit_rules: dict[str, ProfitRules] = field(default_factory=_default_profit_rules)
    spike_config: SpikeConfig = field(default_factory=SpikeConfig)
    markets: dict[str, MarketMapping] = field(default_factory=_default_markets)
    atr_interval: str = "4h"
    atr_period: int = 14
    atr_cache_seconds: int = 3600

    def get_market(self, canonical_id: str) -> MarketMapping:
        """Return MarketMapping for *canonical_id*, or a sensible default."""
        if canonical_id in self.markets:
            return self.markets[canonical_id]
        # Derive a best-effort mapping from the id itself
        return MarketMapping(
            canonical_id=canonical_id,
            hl_coin=canonical_id.split(":")[-1].replace("-PERP", ""),
        )

    def get_profit_rules(self, canonical_id: str) -> ProfitRules:
        """Return ProfitRules for *canonical_id*, or generic defaults."""
        if canonical_id in self.profit_rules:
            return self.profit_rules[canonical_id]
        return ProfitRules()


# ── JSON helpers ─────────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict | None:
    """Read a JSON file, returning None on missing/corrupt."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("corrupt config %s — using defaults: %s", path, exc)
        return None


def _apply_escalation(cfg: HeartbeatConfig, data: dict) -> None:
    for k, v in data.items():
        if hasattr(cfg.escalation, k):
            setattr(cfg.escalation, k, v)


def _apply_profit_rules(cfg: HeartbeatConfig, data: dict) -> None:
    for market_id, overrides in data.items():
        if not isinstance(overrides, dict):
            continue
        base = cfg.profit_rules.get(market_id, ProfitRules())
        for k, v in overrides.items():
            if hasattr(base, k):
                setattr(base, k, v)
        cfg.profit_rules[market_id] = base


def _apply_markets(cfg: HeartbeatConfig, data: dict) -> None:
    for market_id, info in data.items():
        if not isinstance(info, dict):
            continue
        cfg.markets[market_id] = MarketMapping(
            canonical_id=info.get("canonical_id", market_id),
            hl_coin=info.get("hl_coin", market_id),
            dex=info.get("dex"),
            wallet_address=info.get("wallet_address"),
        )


# ── Public loader ────────────────────────────────────────────────────────────

def load_config(config_dir: Path | None = None) -> HeartbeatConfig:
    """Build a HeartbeatConfig from hardcoded defaults + optional JSON overrides.

    If *config_dir* is ``None``, look in ``<project_root>/data/config/``.
    Missing or corrupt files are silently ignored (defaults used).
    """
    if config_dir is None:
        config_dir = Path(__file__).resolve().parent.parent / "data" / "config"

    cfg = HeartbeatConfig()

    esc_data = _read_json(config_dir / "escalation_config.json")
    if esc_data:
        _apply_escalation(cfg, esc_data)

    pr_data = _read_json(config_dir / "profit_rules.json")
    if pr_data:
        _apply_profit_rules(cfg, pr_data)

    mkt_data = _read_json(config_dir / "market_config.json")
    if mkt_data:
        _apply_markets(cfg, mkt_data)

    return cfg
