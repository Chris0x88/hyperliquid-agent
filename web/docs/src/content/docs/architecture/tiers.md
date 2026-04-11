---
title: Tier State Machine
description: WATCH, REBALANCE, and OPPORTUNISTIC — what each tier runs, what it can do, and how to promote safely.
---

import { Aside } from '@astrojs/starlight/components';

## The Tier Ladder

The daemon operates in exactly one tier at a time. Each tier controls which iterators run and whether the system can place orders.

| Tier | Trade placement | Summary |
|------|----------------|---------|
| **WATCH** | None — read-only monitoring | All analysis and research iterators. protection_audit verifies SL/TP exist but does NOT place them. |
| **REBALANCE** | Yes — execution iterators active | Adds execution_engine, exchange_protection, guard, rebalancer, profit_lock, catalyst_deleverage. Drops radar and pulse. |
| **OPPORTUNISTIC** | Yes — full signal-driven | Everything from both WATCH and REBALANCE. Radar and pulse restored alongside execution. |

**Production today: WATCH.** The system ships in WATCH and stays there until explicitly promoted.

---

## WATCH Tier (37 iterators)

WATCH is the default. It runs all monitoring, analysis, and research iterators but cannot place any orders.

### Iterator List

| Category | Iterators |
|----------|-----------|
| **Data collection** | `account_collector`, `connector`, `funding_tracker` |
| **Risk monitoring** | `liquidation_monitor`, `protection_audit`, `risk` |
| **Market analysis** | `market_structure`, `thesis_engine`, `radar`, `pulse`, `liquidity`, `heatmap`, `bot_classifier` |
| **Oil bot-pattern** | `oil_botpattern` (shadow mode only), `oil_botpattern_tune`, `oil_botpattern_reflect`, `oil_botpattern_shadow`, `oil_botpattern_patternlib` |
| **News and supply** | `news_ingest`, `supply_ledger` |
| **Research** | `autoresearch`, `journal`, `entry_critic`, `lesson_author`, `memory_consolidation`, `memory_backup` |
| **Thesis management** | `thesis_engine`, `thesis_challenger`, `thesis_updater` |
| **Advisory** | `apex_advisor`, `lab`, `architect` |
| **Rollover** | `brent_rollover_monitor` |
| **Infrastructure** | `action_queue`, `telegram` |

<Aside type="caution" title="protection_audit is READ-ONLY">
In WATCH tier, `protection_audit` verifies that open positions have SL/TP on exchange — but it does NOT place missing orders. It only alerts. The iterator that actually places protective orders is `exchange_protection`, which only runs at REBALANCE tier and above.
</Aside>

### What WATCH Cannot Do

- Place any orders (entry, exit, SL, TP, or rebalance)
- Resize positions
- Execute on oil bot-pattern signals (shadow mode evaluates but does not trade)
- Act on catalyst deleverage triggers

---

## REBALANCE Tier

REBALANCE adds execution capability. It includes everything from WATCH plus the execution iterators, but drops `radar` and `pulse` (which are scan-oriented, not execution-oriented).

### Added Iterators (6)

| Iterator | Purpose |
|----------|---------|
| `execution_engine` | Converts OrderIntents to exchange orders. The only path to the exchange. |
| `exchange_protection` | Places missing SL/TP orders. The active counterpart to protection_audit. |
| `guard` | Position guard — enforces max drawdown, kills runaway positions. |
| `rebalancer` | Adjusts position sizes toward thesis conviction targets. |
| `profit_lock` | Trails stops on winning positions to lock in profit. |
| `catalyst_deleverage` | Reduces exposure when negative catalysts fire (news_ingest feeds this). |

### Removed from WATCH set (2)

| Iterator | Why removed |
|----------|-------------|
| `radar` | Scans for new opportunities — not needed when execution is thesis-driven |
| `pulse` | Market pulse scoring — overlaps with thesis_engine at REBALANCE |

### What REBALANCE Can Do

- Place SL/TP orders via exchange_protection
- Rebalance position sizes toward thesis targets
- Execute catalyst-driven deleverage
- Lock profits with trailing stops
- Guard against max drawdown

### What REBALANCE Still Requires

- **Per-asset delegation** — the AI agent needs `/delegate <ASSET>` authority to act on each market
- **Thesis files** — positions without a thesis file get no execution (the engine has nothing to target)

---

## OPPORTUNISTIC Tier

OPPORTUNISTIC runs everything. All 42+ iterators from both WATCH and REBALANCE, plus radar and pulse are restored alongside execution.

This is the full autonomous mode: the system scans for opportunities (radar + pulse), evaluates them against thesis, and executes if conviction is high enough.

### Iterator Set

All WATCH iterators + all REBALANCE additions. Nothing is removed. Radar and pulse run alongside the execution engine.

---

## Promotion Checklist

Before promoting from WATCH to REBALANCE:

1. **All open positions have SL and TP on exchange.** Run `/pos` to verify. Every position MUST have both — no exceptions.
2. **Thesis files are fresh.** Check `data/thesis/*.json` — each active market needs a current thesis with direction, conviction, SL/TP prices, and invalidation conditions.
3. **Per-asset authority is set.** Run `/delegate <ASSET>` for each market you want the agent to act on.
4. **Daemon health is green.** The HealthWindow circuit breaker (`common/telemetry.py`) must not be tripped.
5. **You understand the risk.** REBALANCE can place real orders with real money. Start with one asset.

### Promoting via Telegram

```
/activate rebalance
```

### Demoting Back to WATCH

```
/activate watch
```

Or restart the daemon — it always starts in the configured default tier (WATCH).

<Aside type="tip">
Promotion is per-system, not per-asset. But execution is per-asset (via delegation). So you can promote to REBALANCE and only delegate BRENTOIL — the system will only execute on BRENTOIL while monitoring everything else in read-only mode.
</Aside>

---

## Kill Switches

Individual subsystems have kill switches independent of tier. Each is a boolean flag inside its config file.

| Subsystem | Config file | Key | Default |
|-----------|------------|-----|---------|
| Oil Bot-Pattern | `data/config/oil_botpattern.json` | `enabled` | `false` |
| News ingestion | `data/config/news_ingest.json` | `enabled` | `false` |
| Thesis updater | `data/config/thesis_updater.json` | `enabled` | `false` |
| Lab engine | `data/config/lab.json` | `enabled` | `false` |
| Conviction bands | Inside each `data/thesis/*.json` | `conviction_bands.enabled` | `false` |

All kill switches default to **off** (disabled). Flip them manually when ready.

<Aside type="caution">
Kill switches are independent of tier. A subsystem can be enabled in WATCH (where it runs in shadow/advisory mode) or disabled in REBALANCE (where it simply does not run even though the tier allows it). Tier controls what CAN run; kill switches control what DOES run.
</Aside>

---

## Tier Summary Matrix

| Capability | WATCH | REBALANCE | OPPORTUNISTIC |
|-----------|-------|-----------|---------------|
| Account monitoring | Yes | Yes | Yes |
| Liquidation alerts | Yes | Yes | Yes |
| Thesis evaluation | Yes | Yes | Yes |
| SL/TP verification (alert only) | Yes | Yes | Yes |
| SL/TP placement | No | Yes | Yes |
| Position rebalancing | No | Yes | Yes |
| Catalyst deleverage | No | Yes | Yes |
| Profit trailing | No | Yes | Yes |
| Drawdown guard | No | Yes | Yes |
| Opportunity scanning (radar/pulse) | Yes (advisory) | No | Yes (with execution) |
| Oil bot-pattern signals | Shadow only | Live (if enabled) | Live (if enabled) |
| News ingestion | Yes (if enabled) | Yes (if enabled) | Yes (if enabled) |
| Memory and research | Yes | Yes | Yes |
