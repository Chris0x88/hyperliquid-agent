---
kind: adr
last_regenerated: 2026-04-09 16:36
adr_file: docs/wiki/decisions/002-conviction-engine.md
tags:
  - adr
  - decision
---
# ADR-002: Conviction Engine (Two-Layer Thesis System)

**Source**: [`docs/wiki/decisions/002-conviction-engine.md`](../../docs/wiki/decisions/002-conviction-engine.md)

## Preview

```
# ADR-002: Conviction Engine (Two-Layer Thesis System)

**Date:** 2026-03-30
**Status:** Accepted

## Context
Position sizing was manual and inconsistent. The operator (Chris) has deep domain expertise in oil markets but poor execution discipline. The system needed a way to translate qualitative conviction into mechanical sizing, with automatic staleness detection so stale theses don't drive oversized positions.

## Decision
Build a two-layer conviction system. Layer 1: ThesisState --- AI writes conviction (0.0--1.0) to per-market JSON files in `data/thesis/`. Layer 2: ExecutionEngine reads thesis each tick and sizes positions via Druckenmiller-style conviction bands (<0.3 defensive, 0.3--0.5 small, 0.5--0.7 medium, 0.7--0.9 large, 0.9+ maximum). Stale theses (>7d) taper conviction; >14d clamps to 0.3. Kill switch: `conviction_bands.enabled = false`.

## Consequences
- Thesis files become the shared contract between human (writes conviction via Claude Code) and machine (reads and executes).
- Staleness clamping prevents the frozen-thesis failure that caused the 2026-04-02 oil loss.
- Six safeguards gate execution: no thesis = no trade, conviction > 0.5 required, oil long-only, vault protected, notional cap 50%.
```

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
