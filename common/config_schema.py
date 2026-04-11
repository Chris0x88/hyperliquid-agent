"""Typed, validated config models for core configuration files.

Provides Pydantic v2 models for:
  - OilBotPatternConfig  (data/config/oil_botpattern.json)
  - MarketsConfig         (data/config/markets.yaml)
  - WatchlistEntry        (data/config/watchlist.json)
  - RiskCapsConfig        (data/config/risk_caps.json)
  - EscalationConfig      (data/config/escalation_config.json)

Usage:
    from common.config_schema import load_config

    cfg = load_config("oil_botpattern")          # returns OilBotPatternConfig
    cfg = load_config("markets")                  # returns MarketsConfig
    cfg = load_config("watchlist")                # returns list[WatchlistEntry]
    cfg = load_config("risk_caps")                # returns RiskCapsConfig
    cfg = load_config("escalation")               # returns EscalationConfig
"""

from __future__ import annotations

import json
import logging
import warnings
from pathlib import Path
from typing import Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. OilBotPatternConfig
# ---------------------------------------------------------------------------


class SizingRung(BaseModel):
    min_edge: float
    base_pct: float
    leverage: float


class DrawdownBrakes(BaseModel):
    daily_max_loss_pct: float = 3.0
    weekly_max_loss_pct: float = 8.0
    monthly_max_loss_pct: float = 15.0


class AdaptiveConfig(BaseModel):
    stale_time_progress: float = 1.0
    stale_price_progress: float = 0.3
    slow_velocity_ratio: float = 0.25
    slow_velocity_time_floor: float = 0.5
    breakeven_at_progress: float = 0.5
    tighten_at_progress: float = 0.8
    tighten_buffer_pct: float = 0.5
    scale_out_at_progress: float = 2.0
    adverse_catalyst_severity: int = 4
    catalyst_lookback_hours: float = 24.0
    drift_exit_classifications: list[str] = ["informed_flow"]


class OilBotPatternConfig(BaseModel):
    enabled: bool = False
    short_legs_enabled: bool = False
    short_legs_grace_period_s: int = 3600
    decisions_only: bool = True
    shadow_seed_balance_usd: float = 100000.0
    shadow_sl_pct: float = 2.0
    shadow_tp_pct: float = 5.0
    instruments: list[str] = ["BRENTOIL", "CL"]
    tick_interval_s: int = 60
    long_min_edge: float = 0.5
    short_min_edge: float = 0.7
    short_blocking_catalyst_severity: int = 4
    short_blocking_supply_freshness_hours: int = 72
    short_max_hold_hours: int = 24
    short_daily_loss_cap_pct: float = 1.5
    sizing_ladder: list[SizingRung] = []
    drawdown_brakes: DrawdownBrakes = DrawdownBrakes()
    funding_warn_pct: float = 0.5
    funding_exit_pct: float = 1.5
    preferred_sl_atr_mult: float = 0.8
    preferred_tp_atr_mult: float = 2.0
    # File paths
    patterns_jsonl: str = "data/research/bot_patterns.jsonl"
    zones_jsonl: str = "data/heatmap/zones.jsonl"
    cascades_jsonl: str = "data/heatmap/cascades.jsonl"
    supply_state_json: str = "data/supply/state.json"
    catalysts_jsonl: str = "data/news/catalysts.jsonl"
    risk_caps_json: str = "data/config/risk_caps.json"
    thesis_state_path: str = "data/thesis/xyz_brentoil_state.json"
    funding_tracker_jsonl: str = "data/daemon/funding_tracker.jsonl"
    main_journal_jsonl: str = "data/research/journal.jsonl"
    decision_journal_jsonl: str = "data/strategy/oil_botpattern_journal.jsonl"
    state_json: str = "data/strategy/oil_botpattern_state.json"
    shadow_positions_json: str = "data/strategy/oil_botpattern_shadow_positions.json"
    shadow_trades_jsonl: str = "data/strategy/oil_botpattern_shadow_trades.jsonl"
    shadow_balance_json: str = "data/strategy/oil_botpattern_shadow_balance.json"
    adaptive_expected_reach_hours: float = 48.0
    adaptive_heartbeat_minutes: float = 15.0
    adaptive_log_jsonl: str = "data/strategy/oil_botpattern_adaptive_log.jsonl"
    adaptive: AdaptiveConfig = AdaptiveConfig()

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _strip_comments(cls, data: dict) -> dict:
        """Remove JSON comment keys (e.g. '_comment') before validation."""
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if not k.startswith("_")}
        return data


# ---------------------------------------------------------------------------
# 2. MarketsConfig
# ---------------------------------------------------------------------------


class MarketSpec(BaseModel):
    direction_bias: Literal["long_only", "short_only", "neutral"] = "neutral"
    asset_class: str
    sub_class: str = ""
    thesis_required: bool = True
    max_leverage: int = 10
    roll_calendar: str = ""
    exception_subsystems: list[str] = []


class MarketsConfig(BaseModel):
    version: int = 1
    markets: dict[str, MarketSpec]

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# 3. WatchlistEntry (top-level is a list)
# ---------------------------------------------------------------------------


class WatchlistEntry(BaseModel):
    display: str
    coin: str
    aliases: list[str] = []
    category: str = ""


WatchlistConfig = list[WatchlistEntry]

# TypeAdapter for validating the top-level list
_watchlist_adapter = TypeAdapter(list[WatchlistEntry])

# ---------------------------------------------------------------------------
# 4. RiskCapsConfig
# ---------------------------------------------------------------------------


class InstrumentCap(BaseModel):
    sizing_multiplier: float = 1.0
    min_atr_buffer_pct: float = 1.0
    notes: str = ""


class RiskCapsConfig(BaseModel):
    oil_botpattern: dict[str, InstrumentCap] = {}

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _strip_comments(cls, data: dict) -> dict:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if not k.startswith("_")}
        return data


# ---------------------------------------------------------------------------
# 5. EscalationConfig
# ---------------------------------------------------------------------------


class EscalationConfig(BaseModel):
    liq_L1_alert_pct: float = 6.0
    liq_L2_deleverage_pct: float = 4.0
    liq_L2_deleverage_amount: float = 1.0
    liq_L3_emergency_pct: float = 2.0
    liq_L3_target_leverage: float = 3.0
    liq_L2_cooldown_min: int = 30
    liq_L3_cooldown_min: int = 60
    drawdown_L1_pct: float = 5.0
    drawdown_L2_pct: float = 8.0
    drawdown_L2_cut_size_pct: float = 25.0
    drawdown_L3_pct: float = 12.0
    drawdown_L3_cut_size_pct: float = 50.0

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Registry + loader
# ---------------------------------------------------------------------------

CONFIG_REGISTRY: dict[str, type[BaseModel]] = {
    "oil_botpattern": OilBotPatternConfig,
    "markets": MarketsConfig,
    "watchlist": WatchlistEntry,  # sentinel — actual loading uses TypeAdapter
    "risk_caps": RiskCapsConfig,
    "escalation": EscalationConfig,
}

_FILE_MAP: dict[str, str] = {
    "oil_botpattern": "oil_botpattern.json",
    "markets": "markets.yaml",
    "watchlist": "watchlist.json",
    "risk_caps": "risk_caps.json",
    "escalation": "escalation_config.json",
}


def load_config(
    name: str,
    config_dir: str = "data/config",
) -> Union[BaseModel, list[WatchlistEntry]]:
    """Load and validate a config file by name.

    Supports: oil_botpattern, markets, watchlist, risk_caps, escalation.
    Returns a typed Pydantic model (or list[WatchlistEntry] for watchlist).
    Warns on unknown keys via ``extra="forbid"`` (raises on truly unknown).
    """
    if name not in CONFIG_REGISTRY:
        raise ValueError(
            f"Unknown config '{name}'. "
            f"Available: {sorted(CONFIG_REGISTRY.keys())}"
        )

    filename = _FILE_MAP[name]
    path = Path(config_dir) / filename

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw_text = path.read_text(encoding="utf-8")

    # Parse raw data
    if filename.endswith((".yaml", ".yml")):
        raw = yaml.safe_load(raw_text)
    else:
        raw = json.loads(raw_text)

    # Validate
    try:
        if name == "watchlist":
            return _watchlist_adapter.validate_python(raw)
        model_cls = CONFIG_REGISTRY[name]
        return model_cls.model_validate(raw)
    except Exception as exc:
        # Log and re-raise with context
        logger.error("Config validation failed for '%s' (%s): %s", name, path, exc)
        raise
