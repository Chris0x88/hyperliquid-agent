---
title: Quick Start
description: Your first 5 minutes — verify the system, send Telegram commands, understand slash commands vs AI, and create your first thesis.
---

import { Aside } from '@astrojs/starlight/components';

This guide assumes you've completed [Installation](/getting-started/installation/) and have the Telegram bot running.

---

## Your First Commands

Open Telegram and send these to your bot:

### Check System Status

```
/status
```

Shows all open positions with size, entry price, unrealized P&L, liquidation distance, and account equity.

### Check System Health

```
/health
```

Returns daemon status, margin utilization, equity, and iterator state.

### Read the Guide

```
/guide
```

Built-in reference for all commands, organized by section. Start here if you forget a command name.

### Check a Price

```
/price BRENTOIL
/price BTC
```

Returns the current mark price, index price, and 24h change.

### View All Commands

```
/help
```

One-line descriptions of every slash command. There are 60+ commands — `/guide` is the better starting point.

---

## Slash Commands vs AI Chat

This is the most important distinction in the system:

| Input | What Happens |
|-------|-------------|
| `/status` | Pure Python code, direct API call, instant, free |
| `/price BTC` | Pure Python code, direct API call, instant, free |
| `/briefai` | AI-powered (note the `ai` suffix), uses session token credits |
| "What's your view on oil today?" | Routes to AI agent, uses session token credits |
| "Analyze BRENTOIL for a long entry" | Routes to AI agent, uses session token credits |

**The rule:** Slash commands are deterministic code — no AI, no credits. Commands ending in `ai` (like `/briefai`, `/oilbotreviewai`, `/brutalreviewai`, `/lessonauthorai`) use AI. Free-text messages (not starting with `/`) route to the embedded Claude agent.

<Aside type="tip" title="Aliases save keystrokes">
Many commands have short aliases: `/b` for `/brief`, `/h` for `/health`, `/m` for `/market`, `/w` for `/watchlist`, `/pos` for `/position`, `/sig` for `/signals`, `/ch` for `/chathistory`.
</Aside>

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
Show me the current thesis for BRENTOIL and challenge it.
```

The agent has access to your thesis files, market data, position state, trade history, and calendar context (EIA reports, OPEC meetings, Fed decisions). It can execute trades if you've delegated authority — but by default, it's in advisory mode only.

---

## The Daemon

The daemon ticks on a configurable clock (default ~120 seconds). Each tick, its 42 iterators run:

- **account_collector** — fetches account state and prices
- **protection_audit** — checks for missing SL/TP on all positions, places them if absent
- **liquidation_monitor** — alerts if cushion drops below threshold
- **thesis_engine** — evaluates conviction sizing against thesis files
- **funding_tracker** — monitors funding rates across watchlist
- **market_structure** — tracks key levels and structure shifts
- **risk / guard** — enforces risk limits and position guards
- And 35 more (news ingestion, bot-pattern detection, profit lock, etc.)

You'll see Telegram alerts automatically when something needs attention.

---

## Starting in WATCH Tier

WATCH is the default and correct starting tier. It runs all monitoring iterators and sends all alerts, but gates any autonomous trade placement.

```bash
python -m cli.main daemon start --tier watch
```

Verify with:

```
/readiness
```

This shows whether the daemon is running, which iterators are active, and the current tier state.

---

## Your First Thesis File

Thesis files drive the conviction engine. They live in `data/thesis/` and follow the naming convention `{clearinghouse}_{market}_state.json`.

Create `data/thesis/xyz_brentoil_state.json`:

```json
{
  "market": "BRENTOIL",
  "direction": "long",
  "conviction": 0.7,
  "thesis_summary": "Supply disruption from X + seasonal demand pickup",
  "invalidation_conditions": [
    "Price breaks below $70 on volume",
    "Supply disruption resolves"
  ],
  "evidence_for": "Inventory draws, refinery maintenance season",
  "evidence_against": "Global demand slowdown risk",
  "recommended_leverage": 5,
  "recommended_size_pct": 0.15,
  "weekend_leverage_cap": 3,
  "take_profit_price": 78.00,
  "allow_tactical_trades": false,
  "tactical_notes": "",
  "last_evaluation_ts": "2026-04-11T00:00:00Z",
  "snapshot_ref": "",
  "notes": "First thesis — conservative sizing"
}
```

**Key fields:**

| Field | Purpose |
|-------|---------|
| `conviction` | 0.0–1.0, drives position sizing. Higher = larger position within risk limits |
| `direction` | `long`, `short`, or `flat`. BRENTOIL enforces long-only |
| `invalidation_conditions` | List of strings — if any become true, thesis is invalid |
| `take_profit_price` | Used for TP placement. Falls back to 5x ATR if absent |
| `recommended_leverage` | Suggested leverage for this thesis |
| `weekend_leverage_cap` | Reduced leverage for weekend gaps |
| `last_evaluation_ts` | Timestamp of last review. >7d = `needs_review`, >14d = `is_very_stale` |

Check your thesis is loaded:

```
/thesis
```

---

## Checking Readiness

Before promoting beyond WATCH, verify everything is wired:

```
/readiness
```

```
/health
```

```
/diag
```

`/readiness` confirms daemon state and iterator health. `/health` shows account metrics. `/diag` runs deeper diagnostics.

---

## What's Live vs What's Gated

| Feature | Status |
|---------|--------|
| All slash commands (status, price, chart, etc.) | Live |
| Mandatory SL/TP enforcement | Live (daemon running) |
| Liquidation cushion monitoring | Live (daemon running) |
| AI agent advisory mode | Live (with session token) |
| Web dashboard | Live (local only, optional) |
| Autonomous trade placement | Gated — requires `/delegate` + tier promotion |
| Oil Bot-Pattern strategy | Kill switch off by default |
| News ingestion pipeline | Kill switch in `data/config/news_ingest.json` |

See [Tiers & Promotion](/operations/tiers/) to understand how to unlock autonomous features.
