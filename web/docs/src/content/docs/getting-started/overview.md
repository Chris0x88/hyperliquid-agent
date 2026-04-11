---
title: Overview
description: What HyperLiquid Bot is, who it's for, core markets, design principles, and architecture at a glance.
---

## What Is HyperLiquid Bot?

A personal AI trading co-pilot for HyperLiquid perpetuals. You bring domain expertise and write a thesis. The system enforces discipline: conviction-driven sizing, mandatory stop losses, autonomous risk management, and 42 daemon iterators running 24/7.

Telegram is the dashboard. Claude Code is the brain. Thesis files are the shared contract.

---

## Who It's For

- You have real domain knowledge in at least one market (oil, macro, metals)
- You want autonomous risk management that respects your thesis
- You do NOT want AI making up trades — the agent supports your thinking, challenges it, and executes when you delegate authority
- You want zero external fees, zero telemetry, and full control of your keys

---

## Core Thesis Markets

The conviction engine, thesis JSONs, and Druckenmiller-style sizing operate on these four markets:

| Market | Clearinghouse | Notes |
|--------|--------------|-------|
| **BTC** | Native | `btc_perp_state.json` |
| **BRENTOIL** | xyz | `xyz_brentoil_state.json` — Long-only rule enforced |
| **GOLD** | xyz | `xyz_gold_state.json` |
| **SILVER** | xyz | `xyz_silver_state.json` |

xyz perps require `dex='xyz'` in all API calls. The xyz clearinghouse returns names with the `xyz:` prefix (e.g., `xyz:BRENTOIL`).

Other markets (CL, SP500, NATGAS) can be traded manually and will appear in tracking via the auto-watchlist, but they are not thesis-driven and receive no autonomous management.

---

## Design Principles

**Telegram is the dashboard.** Every metric is one slash command away, hitting the HyperLiquid API directly. Zero AI credits per slash command.

**Thesis-driven.** You write thesis JSON files in `data/thesis/`. The conviction engine reads them to size positions. Stale theses (>7d) auto-clamp leverage. Very stale (>14d) clamp harder.

**Mandatory SL & TP.** Every position MUST have both a stop loss and a take profit on the exchange. The daemon checks every tick and places them if missing. Stops are ATR-based. TPs come from thesis `take_profit_price` or mechanical 5x ATR fallback.

**Autonomous but gated.** The AI agent can place trades only when you've delegated authority per-asset via `/delegate` AND promoted the tier beyond WATCH.

**No external parties.** No Nunchi. No builder fees. No telemetry. No third-party code in the critical path. Session tokens only — never API keys. API wallets cannot withdraw funds.

---

## Three Tiers

| Tier | Behavior |
|------|----------|
| **WATCH** | Monitoring only. All iterators run, all alerts fire, but no autonomous trade placement. This is the default. |
| **REBALANCE** | Can adjust existing positions (size, stops, take-profits) within thesis parameters. |
| **OPPORTUNISTIC** | Full autonomous entry/exit within delegated markets and conviction bands. |

Promotion is per-asset and reversible. See [Tiers & Promotion](/operations/tiers/) for the full ladder and checklists.

---

## Architecture at a Glance

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Claude Code │     │   Telegram Bot   │     │  Web Dashboard  │
│  (the brain) │     │  (the dashboard) │     │  (local only)   │
└──────┬───────┘     └────────┬─────────┘     └────────┬────────┘
       │                      │                        │
       │    Shared filesystem state:                   │
       │    thesis/, memory.db, working_state.json     │
       │                      │                        │
       ▼                      ▼                        ▼
┌──────────────────────────────────────────────────────────────┐
│                    Daemon (42 iterators)                      │
│  account_collector · liquidation_monitor · funding_tracker    │
│  protection_audit · thesis_engine · execution_engine          │
│  market_structure · risk · guard · radar · pulse · heatmap    │
│  news_ingest · bot_classifier · oil_botpattern · profit_lock  │
│  catalyst_deleverage · rebalancer · journal · ...             │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   HyperLiquid DEX   │
                    │  (Native + xyz)     │
                    └─────────────────────┘
```

- **Claude Code** — writes thesis files, reviews trade journals, runs manual analysis, promotes tiers
- **Telegram Bot** — slash commands for instant data (`/status`, `/price`, `/chart`), plus free-text AI chat
- **Web Dashboard** — Next.js frontend (port 3000) + FastAPI backend (port 8420), local-only, real-time charts and log streaming
- **Daemon** — tick-based engine running 42 iterators on a configurable clock, enforcing all risk rules

All components share the same filesystem state: thesis files, `data/memory/memory.db`, and working state JSONs.

---

## Production Status

Default tier: **WATCH** (monitoring, no autonomous trade placement).

Autonomous trading requires per-asset delegation (`/delegate`) AND tier promotion to REBALANCE or OPPORTUNISTIC.
