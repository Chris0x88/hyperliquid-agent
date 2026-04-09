---
kind: plan
last_regenerated: 2026-04-09 16:05
plan_file: docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER_PLAN.md
status: unknown
tags:
  - plan
---
# Plan: OIL_BOT_PATTERN_02_SUPPLY_LEDGER_PLAN

**Source**: [`docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER_PLAN.md`](../../docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER_PLAN.md)

**Status (detected)**: unknown

## Preview

```
# Sub-System 2 — Supply Disruption Ledger — Implementation Plan

> **Spec:** `docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER.md`
> **Parent:** `OIL_BOT_PATTERN_SYSTEM.md`
> **Builds on:** sub-system 1 (shipped 2026-04-09; `catalysts.jsonl` is the input stream)
> **Style:** Condensed. Each task has TDD cycle (test → fail → implement → pass → commit). This plan omits some of the verbose scaffolding from sub-system 1's plan because the patterns are now established. Read sub-system 1's plan (`OIL_BOT_PATTERN_01_NEWS_INGESTION_PLAN.md`) for any pattern not shown here.

**Goal:** Ship `modules/supply_ledger.py`, `cli/daemon/iterators/supply_ledger.py`, the config + data files, and 4 Telegram commands. Auto-extract `Disruption` records from sub-system 1 catalysts; accept manual entries via Telegram; aggregate into `SupplyState`.

**Architecture:** Three layers mirroring sub-system 1. (1) `modules/supply_ledger.py` pure logic. (2) `cli/daemon/iterators/supply_ledger.py` daemon integration. (3) `cli/telegram_bot.py` additive command handlers.

**Tech stack:** Python 3.13, pytest, PyYAML. No new external deps.

---

## Phase 0 — Data directory + config files

### Task 0.1 — Create config files and data dir

**Files:**
- Create: `data/config/supply_ledger.json`
- Create: `data/config/supply_auto_extract.yaml`
- Create: `data/supply/.gitkeep`

- [ ] **Step 1** — Write `data/config/supply_ledger.json`:
```json
{
  "enabled": true,
  "auto_extract": true,
  "recompute_interval_s": 300,
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
