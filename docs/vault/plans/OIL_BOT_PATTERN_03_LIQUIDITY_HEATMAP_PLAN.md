---
kind: plan
last_regenerated: 2026-04-09 16:05
plan_file: docs/plans/OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP_PLAN.md
status: unknown
tags:
  - plan
---
# Plan: OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP_PLAN

**Source**: [`docs/plans/OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP_PLAN.md`](../../docs/plans/OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP_PLAN.md)

**Status (detected)**: unknown

## Preview

```
# Sub-system 3 Build Plan — Stop / Liquidity Heatmap

Wedge structure mirrors sub-system 2 (supply ledger). Each wedge ships
independently and leaves the suite green.

## Wedge 1 — Plan docs (THIS FILE + sibling)
- `OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP.md`
- `OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP_PLAN.md`

## Wedge 2 — Config + dataclasses + skeleton
- `data/config/heatmap.json` (kill switch off-by-default in test, on in prod)
- `data/heatmap/.gitkeep`
- `modules/heatmap.py` — `Zone`, `Cascade` dataclasses, JSONL I/O
  (`append_zone`, `append_cascade`, `read_zones`, `read_cascades`),
  `write_zones_atomic` for snapshot batches.
- Tests: dataclass round-trip, JSONL append + read.

## Wedge 3 — Zone clustering (PARALLEL with W4)
- `modules/heatmap.py::cluster_l2_book(book, mid, cluster_bps,
  max_distance_bps, max_zones_per_side, min_notional)` → `list[Zone]`
- Pure function. Input is the dict returned by the HL `l2Book` info call
  (`{'levels': [bids[], asks[]], ...}`). Output is one snapshot's worth of
  ranked zones per side.
- Tests: synthetic books, edge cases (empty, one-sided, all under min).

## Wedge 4 — Cascade detector (PARALLEL with W3)
- `modules/heatmap.py::detect_cascade(prev_oi, curr_oi, prev_funding,
  curr_funding, window_s, oi_threshold_pct, funding_threshold_bps)`
  → `Cascade | None`
- Pure function. Severity scaled 1..4.
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
