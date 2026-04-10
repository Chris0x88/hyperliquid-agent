---
title: Quick Start
description: Your first 5 minutes — verify the daemon is running, send your first Telegram commands, and understand what you're looking at.
---

import { Aside } from '@astrojs/starlight/components';

This guide assumes you've completed [Installation](/getting-started/installation/) and have both the daemon and Telegram bot running.

---

## Your First Commands

Open Telegram and send these commands to your bot:

### Check Portfolio

```
/portfolio
```

Shows all open positions with size, entry price, unrealized P&L, and liquidation distance.

### Check a Price

```
/price BRENTOIL
/price BTC
```

Returns the current mark price, index price, and 24h change.

### Check Funding Rates

```
/funding
```

Shows funding rates for all your watchlist markets. Negative funding on a long position = you're being paid.

### Check Account Health

```
/health
```

Returns margin utilization, equity, and a quick summary of the daemon status.

### View the Help Menu

```
/help
```

Lists all available slash commands with one-line descriptions. Slash commands are deterministic — they hit the HyperLiquid API directly, no AI involved, no credits consumed.

---

## Understanding Slash Commands vs. AI Chat

This is the most important distinction in the system:

| Input | What happens |
|-------|-------------|
| `/price BTC` | Pure Python code, direct API call, instant, free |
| `/portfolio` | Pure Python code, direct API call, instant, free |
| "What's your view on oil today?" | Routes to AI agent, uses OpenRouter credits |
| "Analyze BRENTOIL for a long entry" | Routes to AI agent, uses OpenRouter credits |

Slash commands with `ai` suffix (e.g., `/briefai`) are AI-powered. Everything else without `ai` is deterministic code.

---

## Talking to the AI Agent

Send any free-text message (not starting with `/`) to route it to the embedded Claude agent:

```
What are the key risks to an oil long right now?
```

```
Check my positions and tell me if any stops need adjusting.
```

```
Show me the current thesis for BRENTOIL.
```

The agent has access to your thesis files, market data, position state, and trade history. It can execute trades if you've delegated authority — but by default, it's in advisory mode.

<Aside type="tip" title="CalendarContext">
The agent automatically checks a calendar context for upcoming scheduled events (EIA inventory reports, OPEC meetings, Fed decisions) before any analysis. This is built in — you don't need to remind it.
</Aside>

---

## The Daemon Running in Background

The daemon ticks every ~120 seconds (configurable). Each tick it:

1. Fetches account state and prices
2. Checks for missing SL/TP on all positions — places them if absent
3. Checks liquidation cushion — alerts if below threshold
4. Evaluates conviction sizing against thesis files
5. Runs the REFLECT loop (periodic self-review of recent trades)

You'll see Telegram alerts automatically when:
- A position is missing a stop or take-profit
- Liquidation cushion drops below your configured threshold
- A new signal fires (if tier is above WATCH)

---

## Your First Thesis File

When you're ready to enter a position, write a thesis file at `data/thesis/BRENTOIL.json`:

```json
{
  "market": "BRENTOIL",
  "direction": "long",
  "conviction": 0.7,
  "entry_price": 72.50,
  "stop_loss_price": 70.00,
  "take_profit_price": 78.00,
  "thesis": "Supply disruption from X + seasonal demand pickup",
  "invalidation": "Price breaks below $70 on volume, or supply disruption resolves",
  "updated_at": "2026-04-10T00:00:00Z"
}
```

The conviction value (0.0–1.0) drives sizing. 1.0 = maximum allowed position for your risk settings.

---

## Checking Daemon Status

```
/readiness
```

Shows whether the daemon is running, which iterators are active, and the current tier state.

```
/health
```

Quick account health snapshot — equity, margin usage, positions.

---

## What's Running vs. What's Gated

| Feature | Status |
|---------|--------|
| Price/funding/portfolio commands | Live |
| Mandatory SL/TP enforcement | Live |
| Liquidation cushion monitoring | Live |
| AI agent advisory mode | Live (with OpenRouter key) |
| Autonomous trade placement | Gated behind tier promotion |
| Oil Bot-Pattern strategy | Kill switch off by default |
| News ingestion pipeline | Kill switch off by default |

See [Tiers & Promotion](/operations/tiers/) to understand how to unlock autonomous features.
