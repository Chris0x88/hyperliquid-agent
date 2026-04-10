---
title: System Architecture
description: Four architecture generations and what's running now — from tick daemon to embedded Claude Code port.
---

import { Aside } from '@astrojs/starlight/components';

## Architecture Generations

The system evolved through four generations, each adding a new layer without replacing the last:

| Version | Era | Key Innovation |
|---------|-----|----------------|
| **v1** | Daemon-centric | Hummingbot-style tick engine, tiered iterators, 4-phase plan, no UI |
| **v2** | Interface-first | Telegram bot, OpenRouter bypass, rich AI context |
| **v3** | Agentic tool-calling | Function-tool invocation with dual-mode parsing + approval gates |
| **v4** | Embedded agent runtime | Claude Code port, parallel tools, streaming, self-modification |
| **v4+** | Oil Bot-Pattern + Lesson Layer (2026-04-09) | News/supply-disruption ingestion, trade-lesson FTS5 corpus, guardian cartographer |

---

## System Roles

The system serves three roles simultaneously:

1. **Copilot** — AI chat via Telegram for market analysis, thesis review, and trade discussion
2. **Research Agent** — Autonomous market analysis, news ingestion, supply disruption detection
3. **Risk Manager** — Stop enforcement, drawdown protection, conviction-based sizing every tick

---

## Running Processes (macOS)

```
launchd
├── com.hyperliquid.daemon      (every 2 min) → common/heartbeat.py
├── com.hyperliquid.telegram    (always on)   → cli/telegram_bot.py
└── com.hyperliquid.vault       (hourly)      → scripts/run_vault_rebalancer.py

On demand (started by user or daemon):
└── cli/agent_runtime.py        → Embedded Claude agent (triggered by Telegram chat)
```

---

## Mermaid: Top-Level Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│  CHRIS (Human-in-the-Loop)                                  │
│  Claude Code sessions → write thesis files, review journal  │
│  Telegram → /commands, AI chat                              │
└─────────────┬───────────────────┬───────────────────────────┘
              │                   │
              ▼                   ▼
┌─────────────────┐   ┌────────────────────────────────────────┐
│  Telegram Bot   │   │  Daemon (heartbeat, ~120s ticks)       │
│  cli/telegram   │   │  ├── Account state                     │
│  _bot.py        │   │  ├── Mandatory SL/TP enforcement       │
│                 │   │  ├── Liquidation cushion               │
│  /commands →    │   │  ├── Conviction sizing                 │
│  HL API direct  │   │  ├── REFLECT loop                      │
│                 │   │  └── Oil Bot-Pattern signals           │
│  Chat text →    │   └────────────┬───────────────────────────┘
│  AI Agent       │                │
└────────┬────────┘                │
         │                         ▼
         ▼            ┌────────────────────────────────────────┐
┌─────────────────┐   │  Shared Filesystem State               │
│  AI Agent       │   │  data/thesis/*.json (conviction)       │
│  (v4 runtime)   │◄──►  data/memory/memory.db (SQLite)        │
│  Parallel tools │   │  data/agent_memory/MEMORY.md           │
│  SSE streaming  │   │  data/config/markets.yaml              │
│  Compaction     │   │  data/daemon/chat_history.jsonl        │
└────────┬────────┘   └────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│  HyperLiquid Exchange                                       │
│  Main Account (oil, gold, silver) — xyz clearinghouse      │
│  Vault Account (BTC Power Law) — default clearinghouse     │
└─────────────────────────────────────────────────────────────┘
```

<Aside type="note" title="Mermaid support">
This diagram is rendered as ASCII art. Full Mermaid rendering requires the `astro-mermaid` integration — see `astro.config.mjs` for where to add it when needed.
</Aside>

---

## The Shared Contract: Thesis Files

The `data/thesis/` directory is the single most important shared state. It is written by:
- You (via Claude Code sessions)
- The AI agent (with your authorization)
- The thesis_updater daemon (Haiku-powered, kill switch off by default)

And read by:
- The daemon's conviction sizing iterator
- The AI agent's context harness
- The Telegram bot's `/briefai` command

A thesis file controls:
- Direction (long / neutral — short only allowed on BTC, GOLD, SILVER, never on oil)
- Conviction (0.0–1.0 → position size multiplier)
- Stop loss and take profit prices
- Invalidation conditions

If a thesis file goes stale (not updated within the configured TTL), the conviction engine auto-clamps leverage to a safe floor. The system enforces its own humility.

---

## Authority Model

Per-asset authority controls whether the AI agent can place trades autonomously:

| Authority | What it allows |
|-----------|---------------|
| `off` | No autonomous action on this asset |
| `manual` | AI can suggest but not execute |
| `agent` | AI can execute — requires tier >= REBALANCE |

Authority is stored in `data/authority.json` and managed via `/authority` Telegram command or Claude Code sessions.

**Default: all assets start at `manual`.**

---

## Two Clearinghouses

HyperLiquid has two separate clearinghouses:

| Clearinghouse | Assets | API param |
|--------------|--------|-----------|
| Default (native) | BTC, ETH, most perps | `dex=None` |
| xyz | BRENTOIL, GOLD, SILVER | `dex='xyz'` |

The `dex='xyz'` parameter must be passed on **every API call** for xyz assets — positions, orders, prices, universe lookups. Missing it causes silent failures.

---

## Key Packages

| Package | What it does |
|---------|-------------|
| `cli/` | Telegram bot, AI agent, menu system, tool handlers, signal engine |
| `common/` | Models, snapshots, context harness, renderer ABC, health |
| `parent/` | Exchange proxy, risk manager, protection chain |
| `cli/daemon/` | Clock loop, iterator runner, tier state machine |
| `modules/` | REFLECT, GUARD, RADAR, PULSE, JOURNAL, MEMORY, APEX |
| `agent/` | AGENT.md (system prompt), SOUL.md (trading rules) |
