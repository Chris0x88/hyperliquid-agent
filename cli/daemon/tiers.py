"""Tier definitions — which iterators activate per tier."""
from __future__ import annotations

TIER_ITERATORS = {
    "watch": [
        "connector",
        "risk",
        "journal",
    ],
    "rebalance": [
        "connector",
        "risk",
        "guard",
        "rebalancer",
        "journal",
    ],
    "opportunistic": [
        "connector",
        "risk",
        "guard",
        "rebalancer",
        "radar",
        "pulse",
        "journal",
    ],
}

VALID_TIERS = list(TIER_ITERATORS.keys())


def iterators_for_tier(tier: str) -> list[str]:
    """Return iterator names for a given tier."""
    if tier not in TIER_ITERATORS:
        raise ValueError(f"Unknown tier '{tier}'. Valid: {VALID_TIERS}")
    return TIER_ITERATORS[tier]
