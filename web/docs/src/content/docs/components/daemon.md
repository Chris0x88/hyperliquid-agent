---
title: Daemon & Iterators
description: The tick-based engine that runs in the background, enforcing risk rules and managing positions every ~120 seconds.
---

## Overview

The daemon is a Hummingbot-inspired tick engine running via launchd. Every ~120 seconds it fires a clock tick, builds a `TickContext` with live account state, and calls each active iterator in sequence.

**Production status:** Running in WATCH tier on mainnet via launchd.

Source: `cli/daemon/clock.py` (Clock class), `cli/daemon/context.py` (TickContext)

---

## Tick Sequence

Each tick runs this sequence:

1. Check control file for runtime commands (pause, stop, tier change)
2. Rebuild active iterator set for the current tier
3. Call `iterator.tick(ctx)` for each active iterator in order
4. Execute queued `OrderIntent`s (if any)
5. Persist state via `StateStore`

---

## Tiers and Iterator Sets

| Tier | Purpose | Key additions |
|------|---------|---------------|
| `watch` | Monitor-only, no autonomous entries | account_collector, thesis_engine, risk, telegram |
| `rebalance` | Active position management | execution_engine, exchange_protection, guard, rebalancer, profit_lock |
| `opportunistic` | Full autonomous trading | radar, pulse (opportunity scanners) |

See `TIER_ITERATORS` in `cli/daemon/tiers.py` for the exact iterator sets.

---

## Key Iterators

All iterators live in `cli/daemon/iterators/`. Each implements `on_start(ctx)`, `tick(ctx)`, and `on_stop()`.

| Iterator | What it does |
|----------|-------------|
| `account_collector` | Always first; fetches live account state from both clearinghouses |
| `connector` | Market data connection; failure aborts the daemon |
| `market_structure` | Computes `MarketSnapshot` for all watchlist markets |
| `thesis_engine` | Reads AI thesis files into `ctx.thesis_states` |
| `exchange_protection` | Mandatory SL/TP enforcement — places missing stops |
| `execution_engine` | Conviction-based sizing (REBALANCE tier+) |
| `risk` | Wires the `ProtectionChain` into the tick loop |
| `telegram` | Severity-aware alert routing with dedup cooldowns |
| `news_ingest` | Oil Bot-Pattern sub-system 1 — RSS/iCal catalyst ingestion (kill switch) |

---

## Health Window

`HealthWindow` (from `common/telemetry.py`) tracks errors in a 15-minute sliding window:

- If errors exceed the budget (10 per window), the daemon auto-downgrades tier
- The `Clock` circuit-breaks individual iterators after 5 consecutive failures
- Failed iterators are skipped rather than crashing the tick

---

## Process Management

- **Single instance:** PID file at `data/daemon/daemon.pid`
- **Startup:** SIGTERM → sleep → SIGKILL for any existing process
- **launchd plist:** `com.hyperliquid.daemon` with `KeepAlive=true`

---

## Start / Stop

```bash
# Production (launchd):
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.daemon.plist

# Testing (mock data, 10 ticks):
python -m cli.main daemon start --tier watch --mock --max-ticks 10

# Direct (mainnet, 120s ticks):
python -m cli.main daemon start --tier watch --tick 120
```
