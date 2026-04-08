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
- Tests: positive (long cascade, short cascade), negative (below threshold,
  no funding move), severity boundaries.

## Wedge 5 — Iterator + tier registration
- `cli/daemon/iterators/heatmap.py` — `HeatmapIterator` mirrors
  `SupplyLedgerIterator` shape:
  - `on_start` reloads config + opens HL info client
  - `tick`: respects `poll_interval_s`, polls `l2Book` per instrument,
    calls `cluster_l2_book`, appends to `zones.jsonl`. Tracks OI/funding
    history per instrument; calls `detect_cascade`; appends to
    `cascades.jsonl`. Emits `Alert(severity="info")` on cascades severity ≥3.
- Register in all 3 tiers in `cli/daemon/tiers.py` (read-only is safe).
- Update `cli/daemon/CLAUDE.md` known-iterators list.
- Tests: iterator dry-tick with mocked HL info client.

## Wedge 6 — `/heatmap` Telegram command (5 surfaces)
- `cli/telegram_bot.py::cmd_heatmap` — reads latest snapshot from
  `zones.jsonl` per instrument, formats top zones per side + recent
  cascades. Read-only, no AI, no `ai` suffix needed.
- `HANDLERS` dict — register `/heatmap` and bare `heatmap`
- `_set_telegram_commands()` — menu entry
- `cmd_help()` — one-line entry under oil section
- `cmd_guide()` — section entry if user-facing
- Tests: `tests/test_telegram_bot.py::test_cmd_heatmap_*`

## Wedge 7 — Wiki + build-log + alignment commit
- `docs/wiki/components/heatmap.md` — narrative page
- `docs/wiki/build-log.md` — top entry for 2026-04-09 (sub-system 3 ship)
- `cli/daemon/CLAUDE.md` — add `heatmap` to known iterators
- Run `pytest tests/ -x -q` and verify 100% pass
- `alignment:` commit with all files added by name

## Out of scope (do NOT pull in)
- Direction-rule relaxation (sub-system 5 only)
- CL native trading (still gated)
- Anything that places orders
- Touching parallel session's `guardian/` work
