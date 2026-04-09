---
kind: plan
last_regenerated: 2026-04-09 16:05
plan_file: docs/plans/OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP.md
status: unknown
tags:
  - plan
---
# Plan: OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP

**Source**: [`docs/plans/OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP.md`](../../docs/plans/OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP.md)

**Status (detected)**: unknown

## Preview

```
# Sub-system 3 — Stop / Liquidity Heatmap

**Slot in `OIL_BOT_PATTERN_SYSTEM.md`:** row 3. Pure HL API. Independent of #1/#2.

## What it is

A read-only iterator that polls Hyperliquid market data for oil instruments
(BRENTOIL on xyz dex, CL native if/when promoted) and writes two structured
streams that downstream sub-systems #4 (bot-pattern classifier) and #5
(strategy engine) consume:

1. **`data/heatmap/zones.jsonl`** — append-only snapshots of liquidity zones.
   Each line = one cluster of resting orders within `cluster_bps` of mid,
   ranked by aggregate notional. Used to identify magnet levels and likely
   stop-hunt targets.

2. **`data/heatmap/cascades.jsonl`** — append-only liquidation cascade events.
   Each line = a window in which liquidations + OI delta exceed thresholds,
   tagged with side and severity. Used to detect bot-driven overextensions.

The iterator NEVER places trades. The kill switch is
`data/config/heatmap.json → enabled: false`.

## Why this slot

- **Smallest external surface** — Hyperliquid info API only. No new RSS, no
  scraping, no LLM. Lowest risk to ship after #1/#2.
- **Independent** — does not consume #1 or #2. Can run in parallel without
  blocking the strategy chain.
- **Mechanical and testable** — pure transforms over orderbook + recent fills.
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
