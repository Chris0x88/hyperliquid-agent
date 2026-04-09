---
kind: plan
last_regenerated: 2026-04-09 16:05
plan_file: docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER.md
status: Approved 2026-04-09. Same session. No brainstorm round.
tags:
  - plan
---
# Plan: OIL_BOT_PATTERN_02_SUPPLY_LEDGER

**Source**: [`docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER.md`](../../docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER.md)

**Status (detected)**: Approved 2026-04-09. Same session. No brainstorm round.

## Preview

```
# Sub-System 2 — Supply Disruption Ledger

> **Parent:** `OIL_BOT_PATTERN_SYSTEM.md`
> **Prerequisite:** `OIL_BOT_PATTERN_01_NEWS_INGESTION.md` (shipped 2026-04-09)
> **Status:** Approved 2026-04-09. Same session. No brainstorm round.
> **Constraint:** Additive only. Zero destructive changes.
> **Kill switch:** `data/config/supply_ledger.json` → `enabled: false`

---

## 1. Purpose and boundary

Encode Chris's petroleum-engineering edge as structured data. Turn headlines and manual observations about physical supply disruptions (refinery strikes, pipeline damage, tanker attacks, chokepoint blockades) into rows with **volumes**, **locations**, **recovery dates**, and **confidence scores** — the things headlines alone don't carry but a petroleum engineer needs.

**DOES:**
- Auto-create `Disruption` records from sub-system 1 catalysts tagged `physical_damage_facility`, `shipping_attack`, or `chokepoint_blockade`
- Accept manual entries via Telegram `/disrupt` command (this is the edge)
- Aggregate active disruptions into a `SupplyState` (total bpd offline, by region, by facility type, chokepoint status)
- Publish the aggregated state to `data/supply/state.json` for later sub-systems to consume
- Expose `/supply`, `/disruptions`, `/disrupt`, `/disrupt-update` Telegram commands (all deterministic, NOT AI)

**DOES NOT:**
- Place trades (sub-system 5)
- Predict prices from the ledger (sub-system 4/5)
- Summarise headlines (sub-system 1's job — already done)
- Run external scrapers for ship trackers or EIA outage reports in V1 (future extension)
- Modify or delete existing disruption records (append-only; updates get a new `updated_at` row via a dedicated update path that preserves history)

## 2. Data model

```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
