"""Tier definitions — which iterators activate per tier."""
from __future__ import annotations

TIER_ITERATORS = {
    "watch": [
        "account_collector",   # always first — injects live account state
        "connector",
        "liquidation_monitor", # tiered cushion alerts on every position (audit F6)
        "funding_tracker",     # cumulative funding cost tracker (C2 — read-only)
        "market_structure",    # pre-compute technicals before thesis/execution
        "thesis_engine",       # reads AI thesis files into ctx
        "radar",               # opportunity scanner (read-only intelligence)
        "pulse",               # capital inflow detector (read-only intelligence)
        "liquidity",
        "risk",
        "autoresearch",        # learning loop
        "memory_consolidation", # compress old events hourly
        "journal",
        "telegram",
    ],
    "rebalance": [
        "account_collector",
        "connector",
        "liquidation_monitor", # tiered cushion alerts on every position (audit F6)
        "market_structure",
        "thesis_engine",
        "execution_engine",    # conviction-based sizing
        "exchange_protection", # ruin prevention only (SL near liq)
        "liquidity",
        "risk",
        "guard",
        "rebalancer",
        "profit_lock",
        "funding_tracker",
        "catalyst_deleverage",
        "autoresearch",
        "memory_consolidation",
        "journal",
        "telegram",
    ],
    "opportunistic": [
        "account_collector",
        "connector",
        "liquidation_monitor", # tiered cushion alerts on every position (audit F6)
        "market_structure",
        "thesis_engine",
        "execution_engine",
        "exchange_protection",
        "liquidity",
        "risk",
        "guard",
        "rebalancer",
        "radar",
        "pulse",
        "profit_lock",
        "funding_tracker",
        "catalyst_deleverage",
        "autoresearch",
        "memory_consolidation",
        "journal",
        "telegram",
    ],
}

VALID_TIERS = list(TIER_ITERATORS.keys())


def iterators_for_tier(tier: str) -> list[str]:
    """Return iterator names for a given tier."""
    if tier not in TIER_ITERATORS:
        raise ValueError(f"Unknown tier '{tier}'. Valid: {VALID_TIERS}")
    return TIER_ITERATORS[tier]
