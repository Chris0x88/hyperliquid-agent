---
kind: plan
last_regenerated: 2026-04-09 16:05
plan_file: docs/plans/OIL_BOT_PATTERN_04_BOT_CLASSIFIER.md
status: parked. Comeback target: after ≥100 closed trades exist in
tags:
  - plan
---
# Plan: OIL_BOT_PATTERN_04_BOT_CLASSIFIER

**Source**: [`docs/plans/OIL_BOT_PATTERN_04_BOT_CLASSIFIER.md`](../../docs/plans/OIL_BOT_PATTERN_04_BOT_CLASSIFIER.md)

**Status (detected)**: parked. Comeback target: after ≥100 closed trades exist in

## Preview

```
# Sub-system 4 — Bot-Pattern Classifier

**Slot in `OIL_BOT_PATTERN_SYSTEM.md`:** row 4. First sub-system that
consumes multiple input streams. Read-only.

## What it is

A read-only iterator that periodically (default every 300s) scores each
configured oil instrument's recent move and emits a classification record:

- `bot_driven_overextension` — likely shake-out / cascade-driven move
  with no fundamental support
- `informed_move` — move backed by a high-severity catalyst or supply
  disruption
- `mixed` — both bot-driven and informed signals present
- `unclear` — neither signal dominates; insufficient evidence

Each record includes a `confidence` score (0..1), the contributing
signals as plain-text evidence strings, and the price + window context
needed for downstream sub-systems #5 (strategy engine) and #6
(self-tune harness) to consume.

The iterator NEVER places trades. Heuristic-only — **no ML, no LLM**.
Layer L5 (ML overlay) is explicitly deferred per `OIL_BOT_PATTERN_SYSTEM.md`
§6. Kill switch: `data/config/bot_classifier.json → enabled: false`.

## Why this slot

- It's the first sub-system that **needs** multiple streams. #1 catalysts,
  #2 supply state, and #3 cascades are all live, so #4 has real data to
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
