---
kind: plan
last_regenerated: 2026-04-09 16:36
plan_file: docs/plans/PHASE_3_REFLECT_LOOP.md
status: unknown
tags:
  - plan
---
# Plan: PHASE_3_REFLECT_LOOP

**Source**: [`docs/plans/PHASE_3_REFLECT_LOOP.md`](../../docs/plans/PHASE_3_REFLECT_LOOP.md)

**Status (detected)**: unknown

## Preview

```
# Phase 3: Wire REFLECT Meta-Evaluation

> **Status: Shipped (2026-04-07 alignment)**
> **Shipping commit:** `9ce5c20 feat: wire signals, trade journal, REFLECT loop, and /restart into daemon`
>
> The autoresearch daemon iterator now runs `ReflectEngine` and emits
> round-trip metrics into the daemon log and memory at every cycle.
> See `cli/daemon/iterators/autoresearch.py`. This document remains
> as the historical specification.

## Goal

The system evaluates itself. Every trade is journaled, every week is reviewed, performance is tracked over time, and Chris gets a clear "is this working?" signal.

## What's Already Built (just needs wiring)

| Module | Location | What it does |
|--------|----------|-------------|
| ReflectEngine | `modules/reflect_engine.py` | FIFO round-trip analysis, win rate, PnL, FDR, streaks |
| ReflectReporter | `modules/reflect_reporter.py` | Markdown reports + distilled summaries |
| ConvergenceTracker | `modules/reflect_convergence.py` | Detects if adjustments are helping or oscillating |
| ReflectAdapter | `modules/reflect_adapter.py` | Suggests config parameter fixes with guardrails |
| JournalEngine | `modules/journal_engine.py` | Trade quality assessment, nightly review |
| JournalGuard | `modules/journal_guard.py` | Journal persistence (JSONL I/O) |
| MemoryEngine | `modules/memory_engine.py` | Playbook (what works per instrument/signal) |
| MemoryGuard | `modules/memory_guard.py` | Memory persistence (JSONL + JSON) |
| AutoResearch iterator | `cli/daemon/iterators/autoresearch.py` | 30-min evaluation loop (daemon) |

## Wiring Plan

```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
