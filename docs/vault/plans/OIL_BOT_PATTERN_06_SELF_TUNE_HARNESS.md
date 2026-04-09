---
kind: plan
last_regenerated: 2026-04-09 14:08
plan_file: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md
status: APPROVED 2026-04-09 (picked up from prior session handoff).
tags:
  - plan
---
# Plan: OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS

**Source**: [`docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md`](../../docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md)

**Status (detected)**: APPROVED 2026-04-09 (picked up from prior session handoff).

## Preview

```
# Sub-system 6 — Oil Bot-Pattern Self-Tune Harness

**Slot in `OIL_BOT_PATTERN_SYSTEM.md`:** row 6. Wraps sub-system 5 with a
bounded self-improvement loop. First sub-system in the stack that does NOT
place trades directly — it mutates the parameters #5 reads on its next tick.

**Status:** APPROVED 2026-04-09 (picked up from prior session handoff).
Building now. First ship = **L1 + L2 only**. L3 and L4 get their own plan
docs; L5 remains deferred per SYSTEM doc §6.

## Background

Sub-system 5 shipped 2026-04-09 (`42efb54`) with both kill switches OFF.
It emits decision records to `data/strategy/oil_botpattern_journal.jsonl`
on every tick and appends closed positions to `data/research/journal.jsonl`
with `strategy_id="oil_botpattern"`. The self-tune harness reads those two
streams and nothing else — it does not touch exchanges, orderbooks, or any
external API.

The SYSTEM doc §6 defines six layers (L0-L5). Their status at the start of
this wedge series:

| Layer | Description | Status |
|---|---|---|
| L0 | Hard contracts (tests, SL+TP, schemas) | **Already shipped.** exchange_protection enforces SL+TP; tests live in `tests/`; every config file has a schema via the kill-switch reloader. No work needed here. |
| L1 | Bounded auto-tune — journal-replay nudges params within hard min/max after each closed trade | **This wedge.** |
| L2 | Reflect proposals — weekly structural change proposals to Telegram with 1-tap promote/reject | **This wedge.** |
| L3 | Pattern library growth — detects novel `(classification, direction, confidence_band, signals)` signatures in bot_patterns.jsonl, emits candidates for 1-tap promotion | **Shipped 2026-04-09.** Purely observational — classifier integration deferred. |
| L4 | Shadow counterfactual eval — replays approved L2 proposals against the last N days of decisions, reports divergences + est. PnL delta | **Shipped 2026-04-09.** Look-back counterfactual only; forward paper executor deferred. |
| L5 | ML overlay | **Deferred per SYSTEM doc §6.** Requires ≥100 closed trades first. Parked indefinitely. |
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
