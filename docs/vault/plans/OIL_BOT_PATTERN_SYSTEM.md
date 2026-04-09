---
kind: plan
last_regenerated: 2026-04-09 16:05
plan_file: docs/plans/OIL_BOT_PATTERN_SYSTEM.md
status: Approved 2026-04-09. Sub-system 1 enters detailed spec.
tags:
  - plan
---
# Plan: OIL_BOT_PATTERN_SYSTEM

**Source**: [`docs/plans/OIL_BOT_PATTERN_SYSTEM.md`](../../docs/plans/OIL_BOT_PATTERN_SYSTEM.md)

**Status (detected)**: Approved 2026-04-09. Sub-system 1 enters detailed spec.

## Preview

```
# Oil Bot-Pattern Strategy — System Overview

> **Status:** Approved 2026-04-09. Sub-system 1 enters detailed spec.
> **Scope:** A new oil-trading subsystem that exploits bot-driven mispricing
> on CL (WTI) and BRENTOIL on Hyperliquid, by combining scraped news,
> tracked physical supply disruptions, orderbook stop-cluster detection,
> and bot-pattern classification into a fixed strategy with a bounded
> self-improvement harness.
> **Author:** Brainstormed with Chris (petroleum-engineer edge holder).
> **Build order is enforced:** sub-systems ship one at a time with kill switches.
> No sub-system that has not yet shipped is allowed to be referenced as a
> live dependency.

---

## 1. Origin and rationale

The triggering observation (Chris, 2026-04-09):

> Markets are dumb. ~80% of trades are bots reacting to known information,
> not forecasting. Ahead of major scheduled catalysts (e.g. Trump's 8 PM
> Iran deadline), oil drifted up to the minute, then violently
> over-corrected ~20% on the no-deal-yet-then-deal pattern, despite
> Russian/Iranian refinery damage and Middle East supply disruptions
> remaining offline. A petroleum engineer trying to forecast the
> fundamental gets killed by bots that don't read the supply ledger.
> The arbitrage: be early on the obvious thing, then fade the bot
> overcorrection when it lands.

The strategy's job is to encode that arbitrage as a fixed, testable,
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
