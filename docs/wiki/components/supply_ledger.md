# supply_ledger iterator

**Runs in:** WATCH, REBALANCE, OPPORTUNISTIC (all tiers — read-only, safe)
**Source:** `cli/daemon/iterators/supply_ledger.py`
**Pure logic:** `modules/supply_ledger.py`
**Spec:** `docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER.md`
**Plan:** `docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER_PLAN.md`

## Purpose

Encodes petroleum-engineering knowledge about physical supply disruptions as
structured data. Auto-creates Disruption records from sub-system 1 catalysts
tagged `physical_damage_facility` / `shipping_attack` / `chokepoint_blockade`,
accepts manual entries via `/disrupt`, and publishes aggregated `SupplyState`
to `data/supply/state.json` for later sub-systems to consume.

Sub-system 2 of the Oil Bot-Pattern Strategy.

## Inputs

- `data/news/catalysts.jsonl` — produced by news_ingest (sub-system 1)
- `data/config/supply_ledger.json` — runtime config
- `data/config/supply_auto_extract.yaml` — auto-extract mapping rules
- Manual entries via Telegram `/disrupt` and `/disrupt-update`

## Outputs

- `data/supply/disruptions.jsonl` — append-only disruption log
- `data/supply/state.json` — latest aggregated SupplyState
- Telegram info alerts for new refinery/chokepoint disruptions

## Telegram commands

- `/supply` — show current aggregated supply state
- `/disruptions` — list top 10 active disruptions by confidence*volume
- `/disrupt <type> <location> [volume] [unit] [status] [date] "notes"` — manual entry
- `/disrupt-update <id_prefix> key=value [...]` — update existing entry (history preserved)

## Kill switch

`data/config/supply_ledger.json` → `"enabled": false`.

## Out of scope

- Ship tracking integration (future)
- Satellite imagery
- EIA outage report scraper
- LLM facility-name extraction
- Auto-recovery date estimation
