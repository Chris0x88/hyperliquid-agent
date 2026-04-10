---
title: Overview
description: What is HyperLiquid Bot, who it's for, and how it differs from other trading tools.
---

## What Is HyperLiquid Bot?

HyperLiquid Bot is a personal trading instrument that trades **with the dumb-bot reality** — anticipating obvious moves and fading bot overshoot — instead of betting on the market being a fair discounting mechanism.

Markets are ~80% bots reacting to current news. This system turns your domain expertise into structured signals those bots cannot read.

**You bring the thesis. The system brings the discipline.**

---

## Who It's For

This tool was built for a petroleum engineer who trades HyperLiquid perps with an edge in oil markets. The design assumptions are:

- You have real domain knowledge in at least one market
- You want autonomous risk management that respects your thesis
- You do NOT want AI making up trades — the agent supports your thinking, it doesn't replace it
- You want zero external fees, zero telemetry, and full control of your keys

---

## Core Thesis Markets

The system operates on four thesis-driven markets:

| Market | Notes |
|--------|-------|
| **BRENTOIL** | Primary edge market. Long-only rule enforced. |
| **BTC** | Power Law strategy via vault account. |
| **GOLD** | Thesis-driven, currently stale — auto-clamped. |
| **SILVER** | Thesis-driven, currently stale — auto-clamped. |

Manual one-off positions in other markets (CL/NATGAS/equities) are tracked but unsupported for autonomous management.

---

## Key Design Principles

### Interface-First

The Telegram bot is the dashboard. Every metric you need is one slash command away, hitting the HyperLiquid API directly. Zero AI credits per command.

### Thesis-Driven

You write thesis JSON files in `data/thesis/`. The conviction engine reads them to size positions. Stale theses auto-clamp leverage — the system enforces its own humility.

### Mandatory Stop & Take-Profit

Every position MUST have both a stop loss and a take profit on the exchange. The daemon checks this every tick and places them if missing. No exceptions.

### Autonomous but Accountable

The AI agent can place trades, but only when you've delegated authority per-asset and promoted the tier beyond WATCH. The default is WATCH — monitoring only, no autonomous trading.

### No External Parties

No Nunchi. No builder fees. No telemetry. No third-party code in the critical path. Your API wallet cannot withdraw funds even if compromised.

---

## Architecture at a Glance

```
Claude Code (you)        Telegram Bot           Daemon (background)
─────────────────        ────────────           ──────────────────
Write thesis files  →    /portfolio             Heartbeat every 2min
Review trade journal     /price BTC             Enforce SL/TP
Run manual analysis      /funding               Check liquidation cushion
Promote tiers            Chat with AI agent     Run conviction sizing
                         /activate              REFLECT loop
```

The daemon, Telegram bot, and AI agent all share the same filesystem state — thesis files, memory.db, and working_state.json.

---

## Production Status

Current production tier: **WATCH** (monitoring, no autonomous trade placement).

Autonomous trading requires per-asset `agent` delegation AND tier promotion to REBALANCE or OPPORTUNISTIC. See [Tiers & Promotion](/operations/tiers/) for the full ladder.
