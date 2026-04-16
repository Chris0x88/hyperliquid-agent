"""Tier definitions — which iterators activate per tier."""
from __future__ import annotations

TIER_ITERATORS = {
    "watch": [
        "account_collector",   # always first — injects live account state
        "connector",
        "liquidation_monitor", # tiered cushion alerts on every position (audit F6)
        "funding_tracker",     # cumulative funding cost tracker (C2 — read-only)
        "protection_audit",    # read-only verifier that every position has a sane exchange stop (C1')
        "brent_rollover_monitor", # alerts at T-7/T-3/T-1 days before each Brent contract roll (C7)
        "market_structure",    # pre-compute technicals before thesis/execution
        "thesis_engine",       # reads AI thesis files into ctx
        "radar",               # opportunity scanner (read-only intelligence)
        "news_ingest",         # sub-system 1: RSS → catalysts (read-only, safe in WATCH)
        "supply_ledger",       # sub-system 2: supply disruption ledger (read-only, safe in WATCH)
        "heatmap",             # sub-system 3: stop/liquidity heatmap (read-only, safe in WATCH)
        "bot_classifier",      # sub-system 4: bot-pattern classifier (read-only, safe in WATCH)
        "oil_botpattern",      # sub-system 5: strategy engine — SAFE IN WATCH because (a)
                               # WATCH has no execution_engine/exchange_protection so OrderIntents
                               # accumulate with no consumer, AND (b) decisions_only=true puts the
                               # iterator in shadow mode which emits zero OrderIntents by design.
                               # This tier slot is what makes Rung 1 (shadow in WATCH) actually
                               # work — without it, sub-system 5 doesn't tick in WATCH.
        "oil_botpattern_tune",    # sub-system 6 L1: bounded auto-tune (kill switch OFF at ship)
        "oil_botpattern_reflect", # sub-system 6 L2: weekly reflect proposals (kill switch OFF at ship)
        "oil_botpattern_shadow",  # sub-system 6 L4: counterfactual shadow eval (kill switch OFF at ship)
        "pulse",               # capital inflow detector (read-only intelligence)
        "liquidity",
        "risk",
        "apex_advisor",        # dry-run APEX advisor — proposes only (C3)
        "autoresearch",        # learning loop
        "memory_consolidation", # compress old events hourly
        "journal",
        "lesson_author",       # wedge 5: closed-position → lesson candidate writer (no AI)
        "entry_critic",        # Trade Entry Critic — deterministic grading on every new entry (no AI)
        "oil_botpattern_patternlib",  # sub-system 6 L3: pattern library growth (read-only observational, safe in WATCH)
        "memory_backup",       # hourly atomic snapshot of memory.db (read-only, safe everywhere)
        "action_queue",        # daily sweep of operator-ritual queue (read-only, safe everywhere)
        "thesis_challenger",   # catalyst vs invalidation condition matcher (read-only, safe everywhere)
        "thesis_updater",      # Haiku-powered news → conviction adjustment (kill switch OFF at ship)
        "lab",                 # strategy development pipeline (read-only + paper trading, kill switch OFF at ship)
        "architect",           # mechanical self-improvement (read-only, 12h cadence, kill switch OFF at ship)
        "telegram",
    ],
    "rebalance": [
        "account_collector",
        "connector",
        "liquidation_monitor", # tiered cushion alerts on every position (audit F6)
        "protection_audit",    # read-only verifier that every position has a sane exchange stop (C1')
        "brent_rollover_monitor", # alerts at T-7/T-3/T-1 days before each Brent contract roll (C7)
        "market_structure",
        "thesis_engine",
        "execution_engine",    # conviction-based sizing
        "exchange_protection", # ruin prevention only (SL near liq)
        "liquidity",
        "risk",
        "guard",
        "rebalancer",
        "news_ingest",         # sub-system 1: RSS → catalysts (read-only, safe in REBALANCE)
        "supply_ledger",       # sub-system 2: supply disruption ledger (read-only, safe in REBALANCE)
        "heatmap",             # sub-system 3: stop/liquidity heatmap (read-only, safe in REBALANCE)
        "bot_classifier",      # sub-system 4: bot-pattern classifier (read-only, safe in REBALANCE)
        "oil_botpattern",      # sub-system 5: strategy engine (ONLY place oil shorting is legal; kill switches OFF at ship)
        "oil_botpattern_tune",       # sub-system 6 L1: bounded auto-tune for #5 params (kill switch OFF at ship)
        "oil_botpattern_reflect",    # sub-system 6 L2: weekly reflect proposals for #5 (kill switch OFF at ship)
        "oil_botpattern_patternlib", # sub-system 6 L3: pattern library growth (kill switch OFF at ship)
        "oil_botpattern_shadow",     # sub-system 6 L4: counterfactual shadow eval (kill switch OFF at ship)
        "profit_lock",
        "funding_tracker",
        "catalyst_deleverage",
        "autoresearch",
        "memory_consolidation",
        "journal",
        "lesson_author",       # wedge 5: closed-position → lesson candidate writer (no AI)
        "entry_critic",        # Trade Entry Critic — deterministic grading on every new entry (no AI)
        "memory_backup",       # hourly atomic snapshot of memory.db (read-only, safe everywhere)
        "action_queue",        # daily sweep of operator-ritual queue (read-only, safe everywhere)
        "thesis_challenger",   # catalyst vs invalidation condition matcher (read-only, safe everywhere)
        "thesis_updater",      # Haiku-powered news → conviction adjustment (kill switch OFF at ship)
        "lab",                 # strategy development pipeline (read-only + paper trading, kill switch OFF at ship)
        "architect",           # mechanical self-improvement (read-only, 12h cadence, kill switch OFF at ship)
        "telegram",
    ],
    "opportunistic": [
        "account_collector",
        "connector",
        "liquidation_monitor", # tiered cushion alerts on every position (audit F6)
        "protection_audit",    # read-only verifier that every position has a sane exchange stop (C1')
        "brent_rollover_monitor", # alerts at T-7/T-3/T-1 days before each Brent contract roll (C7)
        "market_structure",
        "thesis_engine",
        "execution_engine",
        "exchange_protection",
        "liquidity",
        "risk",
        "guard",
        "rebalancer",
        "radar",
        "news_ingest",         # sub-system 1: RSS → catalysts (read-only, safe in OPPORTUNISTIC)
        "supply_ledger",       # sub-system 2: supply disruption ledger (read-only, safe in OPPORTUNISTIC)
        "heatmap",             # sub-system 3: stop/liquidity heatmap (read-only, safe in OPPORTUNISTIC)
        "bot_classifier",      # sub-system 4: bot-pattern classifier (read-only, safe in OPPORTUNISTIC)
        "oil_botpattern",      # sub-system 5: strategy engine (ONLY place oil shorting is legal; kill switches OFF at ship)
        "oil_botpattern_tune",       # sub-system 6 L1: bounded auto-tune for #5 params (kill switch OFF at ship)
        "oil_botpattern_reflect",    # sub-system 6 L2: weekly reflect proposals for #5 (kill switch OFF at ship)
        "oil_botpattern_patternlib", # sub-system 6 L3: pattern library growth (kill switch OFF at ship)
        "oil_botpattern_shadow",     # sub-system 6 L4: counterfactual shadow eval (kill switch OFF at ship)
        "pulse",
        "profit_lock",
        "funding_tracker",
        "catalyst_deleverage",
        "autoresearch",
        "memory_consolidation",
        "journal",
        "lesson_author",       # wedge 5: closed-position → lesson candidate writer (no AI)
        "entry_critic",        # Trade Entry Critic — deterministic grading on every new entry (no AI)
        "memory_backup",       # hourly atomic snapshot of memory.db (read-only, safe everywhere)
        "action_queue",        # daily sweep of operator-ritual queue (read-only, safe everywhere)
        "thesis_challenger",   # catalyst vs invalidation condition matcher (read-only, safe everywhere)
        "thesis_updater",      # Haiku-powered news → conviction adjustment (kill switch OFF at ship)
        "lab",                 # strategy development pipeline (read-only + paper trading, kill switch OFF at ship)
        "architect",           # mechanical self-improvement (read-only, 12h cadence, kill switch OFF at ship)
        "telegram",
    ],
}

VALID_TIERS = list(TIER_ITERATORS.keys())


def iterators_for_tier(tier: str) -> list[str]:
    """Return iterator names for a given tier."""
    if tier not in TIER_ITERATORS:
        raise ValueError(f"Unknown tier '{tier}'. Valid: {VALID_TIERS}")
    return TIER_ITERATORS[tier]
