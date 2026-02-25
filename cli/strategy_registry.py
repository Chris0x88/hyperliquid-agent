"""Maps short strategy names to module:class paths."""
from __future__ import annotations

from typing import Any, Dict

STRATEGY_REGISTRY: Dict[str, Dict[str, Any]] = {
    "simple_mm": {
        "path": "strategies.simple_mm:SimpleMMStrategy",
        "description": "Symmetric bid/ask quoting around mid price",
        "params": {"spread_bps": 10.0, "size": 1.0},
    },
    "avellaneda_mm": {
        "path": "strategies.avellaneda_mm:AvellanedaStoikovMM",
        "description": "Inventory-aware market maker (Avellaneda-Stoikov model)",
        "params": {"gamma": 0.1, "k": 1.5, "base_size": 1.0},
    },
    "mean_reversion": {
        "path": "strategies.mean_reversion:MeanReversionStrategy",
        "description": "Trade when price deviates from SMA",
        "params": {"window": 20, "threshold_bps": 30.0, "size": 1.0},
    },
    "hedge_agent": {
        "path": "strategies.hedge_agent:HedgeAgent",
        "description": "Reduces excess exposure per deterministic mandate",
        "params": {"notional_threshold": 15000.0},
    },
    "rfq_agent": {
        "path": "strategies.rfq_agent:RFQAgent",
        "description": "Block-size liquidity for dark RFQ flow",
        "params": {"min_size": 0.5, "spread_bps": 15.0},
    },
    "aggressive_taker": {
        "path": "strategies.aggressive_taker:AggressiveTaker",
        "description": "Crosses the spread with directional bias",
        "params": {"size": 2.0, "bias_amplitude": 0.35},
    },
    "claude_agent": {
        "path": "strategies.claude_agent:ClaudeStrategy",
        "description": "LLM trading agent — Gemini (default) or Claude",
        "params": {"model": "gemini-2.0-flash", "base_size": 0.5},
    },
}

# YEX market definitions — Nunchi HIP-3 yield perpetuals
YEX_MARKETS: Dict[str, Dict[str, str]] = {
    "VXX-USDYP": {
        "hl_coin": "yex:VXX",
        "description": "Volatility index (VXX) yield perpetual",
    },
    "US3M-USDYP": {
        "hl_coin": "yex:US3M",
        "description": "US 3-month Treasury rate yield perpetual",
    },
}


def resolve_strategy_path(name_or_path: str) -> str:
    """Resolve a short name to a full module:class path.

    Accepts either a short name ('avellaneda_mm') or
    a full path ('strategies.avellaneda_mm:AvellanedaStoikovMM').
    """
    if ":" in name_or_path:
        return name_or_path
    entry = STRATEGY_REGISTRY.get(name_or_path)
    if entry is None:
        available = ", ".join(sorted(STRATEGY_REGISTRY.keys()))
        raise ValueError(f"Unknown strategy '{name_or_path}'. Available: {available}")
    return entry["path"]


def resolve_instrument(name: str) -> str:
    """Resolve an instrument name to the HL coin symbol.

    Handles:
      - Standard perps: 'ETH-PERP' -> 'ETH-PERP' (unchanged, HLProxy maps internally)
      - YEX markets: 'VXX-USDYP' -> 'VXX-USDYP' (DirectHLProxy maps to yex:VXX)
      - Direct HL coins: 'yex:VXX' -> 'VXX-USDYP' (reverse lookup)
    """
    # Direct YEX coin reference -> canonical name
    for name_key, info in YEX_MARKETS.items():
        if name.lower() == info["hl_coin"].lower():
            return name_key
    # Already a known YEX market or standard perp
    return name
