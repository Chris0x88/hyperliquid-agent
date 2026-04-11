---
title: Tier System
description: The WATCH / REBALANCE / OPPORTUNISTIC ladder — what each tier can do, how to promote, and how to roll back.
---

The tier system gates what the daemon is allowed to do. Each tier unlocks additional iterators and capabilities. The system starts at WATCH and stays there until the operator explicitly promotes it. Promotion is per-instance and reversible — just restart the daemon at a lower tier to roll back.

## Tier Overview

| Tier | Exchange Writes | Oil Bot Orders | Intelligence |
|------|----------------|----------------|-------------|
| **WATCH** | None | Shadow only | Read-only |
| **REBALANCE** | SL/TP + execution | Yes | Read-only |
| **OPPORTUNISTIC** | Everything | Yes | Full |

## WATCH (Production Today)

The default tier. Zero writes to the exchange. Safe to run indefinitely.

**What runs:**
- All monitoring iterators (price feeds, funding, OI, equity tracking)
- `protection_audit` — **verifies** that SL/TP orders exist on exchange, but does NOT place them. It alerts if orders are missing.
- All Oil Bot-Pattern subsystems (news_ingest, supply_ledger, heatmap, bot_classifier) in read-only mode
- Strategy engine computes signals in shadow mode (logged but not executed)
- Lesson author, entry critic, thesis tracking
- All `/slash` commands that read data

**What does NOT run:**
- No orders placed on exchange
- No SL/TP placed on exchange
- No position modifications
- No rebalancing

## REBALANCE

Adds execution capability. The system can now touch the exchange.

**Additional iterators activated:**

| Iterator | Purpose |
|----------|---------|
| `execution_engine` | Places orders based on conviction engine output |
| `exchange_protection` | **Places** SL/TP orders on exchange (ATR-based stops, thesis-based or 5x-ATR take-profits) |
| `guard` | Monitors positions against invalidation levels |
| `rebalancer` | Adjusts position sizes to match conviction changes |
| `profit_lock` | Locks in profits at configurable thresholds |
| `catalyst_deleverage` | Reduces leverage ahead of known catalysts |

**Oil Bot-Pattern:** The strategy engine can now place orders through the gate chain. Both `enabled` and `short_legs_enabled` must be turned on in `data/config/oil_botpattern.json`.

## OPPORTUNISTIC

Everything from REBALANCE, plus intelligence-driven discovery.

**Additional iterators activated:**

| Iterator | Purpose |
|----------|---------|
| `radar` | Scans for opportunities outside thesis markets |
| `pulse` | Broader market intelligence and correlation tracking |

This tier is for operators who want the system to surface new ideas, not just execute on existing theses.

## Per-Asset Authority

Tier controls what the system *can* do. Authority controls what it *may* do, per asset.

| Command | Effect |
|---------|--------|
| `/delegate <coin>` | Give the AI autonomous control over this asset |
| `/reclaim <coin>` | Take back control — AI stops managing this asset |
| `/authority` | Show current delegation state for all assets |

Even at REBALANCE tier, the system will not trade an asset unless authority has been delegated for it. Delegation is the second lock on the door.

## Promotion Checklist

Before promoting from WATCH to REBALANCE:

1. **Verify SL/TP coverage.** Run `/audit` and confirm every open position has both stop-loss and take-profit orders on exchange (placed manually if currently at WATCH).
2. **Review thesis files.** Run `/thesis` for each market. Confirm targets, invalidation levels, and conviction scores are current.
3. **Check authority.** Run `/authority`. Delegate only the assets you want the AI to manage.
4. **Run readiness check.** `/readiness` runs pre-flight diagnostics: config validation, API connectivity, balance checks, iterator health.
5. **Activate.** `/activate` promotes the daemon to the target tier.

## Rollback

Restart the daemon with the lower tier. No migration needed, no data loss. Iterators that require the higher tier simply stop running. Existing positions and their exchange orders (SL/TP) remain untouched on the exchange.

## Kill Switches

Every major subsystem has an independent kill switch in its config file. Setting `enabled: false` stops that subsystem without affecting anything else.

| Config File | Subsystem |
|-------------|-----------|
| `data/config/oil_botpattern.json` | Oil Bot-Pattern strategy engine (also has `short_legs_enabled`) |
| `data/config/news_ingest.json` | News ingestion |
| `data/config/supply_ledger.json` | Supply ledger |
| `data/config/heatmap.json` | Liquidity heatmap |
| `data/config/bot_classifier.json` | Bot classifier |
| `data/config/oil_botpattern_tune.json` | L1 Bounded Auto-Tune |
| `data/config/oil_botpattern_reflect.json` | L2 Reflect Proposals |
| `data/config/oil_botpattern_patternlib.json` | L3 Pattern Library |
| `data/config/oil_botpattern_shadow.json` | L4 Shadow Eval |
| `data/config/lab.json` | Lab / experimental features |
| `data/config/thesis_updater.json` | Thesis auto-updater |
| `data/config/architect.json` | Architect planner |

All kill switches are OFF by default. Staged activation means you turn on exactly what you need, when you need it.
