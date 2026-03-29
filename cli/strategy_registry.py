"""Maps short strategy names to module:class paths with visibility levels."""
from __future__ import annotations

from typing import Any, Dict, List

# Visibility levels:
#   featured  — shown in README, hl strategies, onboarding, daemon default
#   standard  — shown with hl strategies --all
#   advanced  — shown with hl strategies --advanced

STRATEGY_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ── Featured ──────────────────────────────────────────────
    "power_law_btc": {
        "path": "strategies.power_law_btc:PowerLawBTCStrategy",
        "description": (
            "Bitcoin Power Law rebalancer — floor/ceiling signal drives "
            "BTC-PERP leverage (0-40x). Set --tick 3600 for hourly."
        ),
        "visibility": "featured",
        "params": {
            "max_leverage": 40.0,
            "threshold_percent": 15.0,
            "simulate": True,
        },
    },

    # ── Standard ──────────────────────────────────────────────
    "brent_oil_squeeze": {
        "path": "strategies.brent_oil_squeeze:BrentOilSqueezeStrategy",
        "description": "Long-only Brent Oil supply squeeze — geopolitical thesis + trend following + dip buying",
        "visibility": "standard",
        "params": {"base_size_pct": 0.15, "max_position_pct": 0.50},
    },
    "oil_war_regime": {
        "path": "strategies.oil_war_regime:OilWarRegimeStrategy",
        "description": "War-regime oil: mean-reversion at extremes + regime detection + bullish structural bias",
        "visibility": "standard",
        "params": {},
    },
    "oil_liq_sweep": {
        "path": "strategies.oil_liq_sweep:OilLiqSweepStrategy",
        "description": "Liquidation sweep — buy dips from long cascades, fade short squeezes",
        "visibility": "standard",
        "params": {"base_size_pct": 0.20, "max_size_pct": 0.35},
    },
    "mean_reversion": {
        "path": "strategies.mean_reversion:MeanReversionStrategy",
        "description": "Trade when price deviates from SMA",
        "visibility": "standard",
        "params": {"window": 20, "threshold_bps": 30.0, "size": 1.0},
    },
    "trend_follower": {
        "path": "strategies.trend_follower:TrendFollowerStrategy",
        "description": "EMA crossover + ADX trend strength filter",
        "visibility": "standard",
        "params": {"size": 1.0},
    },
    "funding_arb": {
        "path": "strategies.funding_arb:FundingArbStrategy",
        "description": "Cross-venue funding rate arbitrage",
        "visibility": "standard",
        "params": {"divergence_threshold_bps": 2.0, "max_bias_bps": 5.0},
    },

    # ── Advanced ──────────────────────────────────────────────
    "engine_mm": {
        "path": "strategies.engine_mm:EngineMMStrategy",
        "description": "Production quoting engine MM — composite FV, dynamic spreads, multi-level ladder",
        "visibility": "advanced",
        "params": {"base_size": 1.0, "num_levels": 3},
    },
    "avellaneda_mm": {
        "path": "strategies.avellaneda_mm:AvellanedaStoikovMM",
        "description": "Inventory-aware market maker (Avellaneda-Stoikov model)",
        "visibility": "advanced",
        "params": {"gamma": 0.1, "k": 1.5, "base_size": 1.0},
    },
    "regime_mm": {
        "path": "strategies.regime_mm:RegimeMMStrategy",
        "description": "Vol-regime adaptive MM — switches behavior by volatility regime",
        "visibility": "advanced",
        "params": {"base_size": 1.0},
    },
    "simple_mm": {
        "path": "strategies.simple_mm:SimpleMMStrategy",
        "description": "Symmetric bid/ask quoting around mid price",
        "visibility": "advanced",
        "params": {"spread_bps": 10.0, "size": 1.0},
    },
    "grid_mm": {
        "path": "strategies.grid_mm:GridMMStrategy",
        "description": "Grid market maker — fixed-interval levels above and below mid",
        "visibility": "advanced",
        "params": {"grid_spacing_bps": 10.0, "num_levels": 5, "size_per_level": 0.5},
    },
    "liquidation_mm": {
        "path": "strategies.liquidation_mm:LiquidationMMStrategy",
        "description": "Liquidation flow MM — provides liquidity during cascade events",
        "visibility": "advanced",
        "params": {"oi_drop_threshold_pct": 5.0, "cascade_spread_mult": 2.5},
    },
    "momentum_breakout": {
        "path": "strategies.momentum_breakout:MomentumBreakoutStrategy",
        "description": "Momentum breakout — volume + price breakout detection",
        "visibility": "advanced",
        "params": {"lookback": 20, "breakout_threshold_bps": 50.0, "size": 1.0},
    },
    "aggressive_taker": {
        "path": "strategies.aggressive_taker:AggressiveTaker",
        "description": "Crosses the spread with directional bias",
        "visibility": "advanced",
        "params": {"size": 2.0, "bias_amplitude": 0.35},
    },
    "hedge_agent": {
        "path": "strategies.hedge_agent:HedgeAgent",
        "description": "Reduces excess exposure per deterministic mandate",
        "visibility": "advanced",
        "params": {"notional_threshold": 15000.0},
    },
    "rfq_agent": {
        "path": "strategies.rfq_agent:RFQAgent",
        "description": "Block-size liquidity for dark RFQ flow",
        "visibility": "advanced",
        "params": {"min_size": 0.5, "spread_bps": 15.0},
    },
    "claude_agent": {
        "path": "strategies.claude_agent:ClaudeStrategy",
        "description": "LLM trading agent — Gemini (default), Claude, OpenAI",
        "visibility": "advanced",
        "params": {"model": "gemini-2.0-flash", "base_size": 0.5},
    },
    "basis_arb": {
        "path": "strategies.basis_arb:BasisArbStrategy",
        "description": "Basis arbitrage — trades implied basis from funding rate",
        "visibility": "advanced",
        "params": {"basis_threshold_bps": 5.0, "size": 1.0},
    },
    "simplified_ensemble": {
        "path": "strategies.simplified_ensemble:SimplifiedEnsembleStrategy",
        "description": "6-signal ensemble (4/6 vote)",
        "visibility": "advanced",
        "params": {"size": 1.0},
    },
    "funding_momentum": {
        "path": "strategies.funding_momentum:FundingMomentumStrategy",
        "description": "Funding rate mean-reversion — extreme z-scores with EMA confirmation",
        "visibility": "advanced",
        "params": {"size": 1.0},
    },
    "oi_divergence": {
        "path": "strategies.oi_divergence:OIDivergenceStrategy",
        "description": "OI divergence filter — enter on price/OI agreement, exit on divergence",
        "visibility": "advanced",
        "params": {"size": 1.0},
    },
}


def resolve_strategy_path(name_or_path: str) -> str:
    """Resolve a short name to a full module:class path."""
    if ":" in name_or_path:
        return name_or_path
    entry = STRATEGY_REGISTRY.get(name_or_path)
    if entry is None:
        available = ", ".join(sorted(STRATEGY_REGISTRY.keys()))
        raise ValueError(f"Unknown strategy '{name_or_path}'. Available: {available}")
    return entry["path"]


# Legacy YEX market definitions — kept for backwards compatibility with hl_adapter
YEX_MARKETS: Dict[str, Dict[str, str]] = {
    "VXX-USDYP": {"hl_coin": "yex:VXX", "description": "Volatility index yield perpetual"},
    "US3M-USDYP": {"hl_coin": "yex:US3M", "description": "US 3-month Treasury rate yield perpetual"},
    "BTCSWP-USDYP": {"hl_coin": "yex:BTCSWP", "description": "BTC interest rate swap yield perpetual"},
}


def resolve_instrument(name: str) -> str:
    """Resolve an instrument name to the HL coin symbol."""
    for name_key, info in YEX_MARKETS.items():
        if name.lower() == info["hl_coin"].lower():
            return name_key
    return name


def list_strategies(visibility: str = "featured") -> List[Dict[str, Any]]:
    """List strategies filtered by visibility level.

    visibility: "featured" | "all" (featured+standard) | "advanced" (everything)
    """
    levels = {"featured"}
    if visibility == "all":
        levels = {"featured", "standard"}
    elif visibility == "advanced":
        levels = {"featured", "standard", "advanced"}

    result = []
    for name, entry in STRATEGY_REGISTRY.items():
        if entry.get("visibility", "advanced") in levels:
            result.append({"name": name, **entry})
    return result
