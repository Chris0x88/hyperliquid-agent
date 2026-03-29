"""Tier definitions — which iterators activate per tier."""
from __future__ import annotations

TIER_ITERATORS = {
    "watch": [
        "connector",
        "liquidity",
        "risk",
        "journal",
        "telegram",
    ],
    "rebalance": [
        "connector",
        "liquidity",
        "risk",
        "guard",
        "rebalancer",
        "profit_lock",
        "journal",
        "telegram",
    ],
    "opportunistic": [
        "connector",
        "liquidity",
        "risk",
        "guard",
        "rebalancer",
        "radar",
        "pulse",
        "profit_lock",
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
