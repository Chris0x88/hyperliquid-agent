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

```python
@dataclass(frozen=True)
class Disruption:
    id: str                       # sha256(facility_name + incident_date iso)
    source: str                   # "news_auto" | "manual" | "ical" | "tracker"
    source_ref: str               # catalyst_id | telegram_user_id | ical_uid
    facility_name: str            # "Volgograd refinery", "Suezmax tanker Red Sea"
    facility_type: str            # refinery | oilfield | gas_plant | terminal | pipeline | ship | chokepoint
    location: str                 # "Volgograd, Russia" or "Hormuz Strait"
    region: str                   # "russia" | "iran" | "saudi" | "us_gulf" | "red_sea" | ... (canonical)
    volume_offline: float | None  # numeric value, None if unknown
    volume_unit: str | None       # "bpd" | "mcfd" | None
    incident_date: datetime
    expected_recovery: datetime | None
    confidence: int               # 1-5 (1 = rumour, 5 = confirmed by operator/satellite)
    status: str                   # "active" | "partial" | "restored" | "unknown"
    instruments: list[str]        # ["xyz:BRENTOIL", "CL"]
    notes: str
    created_at: datetime
    updated_at: datetime

@dataclass(frozen=True)
class SupplyState:
    computed_at: datetime
    total_offline_bpd: float
    total_offline_mcfd: float
    by_region: dict[str, float]          # region → bpd
    by_facility_type: dict[str, float]   # type → bpd
    active_chokepoints: list[str]        # canonical chokepoint names currently disrupted
    active_disruption_count: int
    high_confidence_count: int           # confidence >= 4
```

## 3. Files (all additive)

### New files

| Path | Responsibility |
|---|---|
| `modules/supply_ledger.py` | Pure logic. `Disruption` + `SupplyState` dataclasses, JSONL I/O, auto-extract from `Catalyst`, manual-entry builder, aggregation math. Zero daemon imports. |
| `cli/daemon/iterators/supply_ledger.py` | Daemon iterator. Watches `data/news/catalysts.jsonl` via mtime, calls `modules.supply_ledger.auto_extract()`, appends to `data/supply/disruptions.jsonl`, recomputes `state.json` every 5 min. |
| `data/config/supply_ledger.json` | Runtime config: `enabled`, `auto_extract`, `recompute_interval_s`, file paths. |
| `data/config/supply_auto_extract.yaml` | Mapping: catalyst category → default facility_type, default confidence, default status. Editable without code. |
| `data/supply/disruptions.jsonl` | Append-only Disruption log. |
| `data/supply/state.json` | Latest computed SupplyState. |
| `data/supply/.gitkeep` | Directory placeholder. |
| `tests/test_supply_ledger.py` | Unit tests for pure logic. |
| `tests/test_supply_ledger_iterator.py` | Integration tests for the iterator. |
| `tests/test_telegram_supply_command.py` | Tests for Telegram commands. |
| `docs/wiki/components/supply_ledger.md` | Wiki page. |

### Edited files (additive only)

| Path | Edit |
|---|---|
| `cli/commands/daemon.py` | Add import + `clock.register(SupplyLedgerIterator())` between news_ingest and pulse. |
| `cli/daemon/tiers.py` | Add `"supply_ledger"` to all three tier lists. |
| `cli/telegram_bot.py` | Add `cmd_supply`, `cmd_disruptions`, `cmd_disrupt`, `cmd_disrupt_update` handlers. Apply 5-surface checklist to each. All deterministic, NO `ai` suffix. |
| `docs/wiki/build-log.md` | Ship entry. |

## 4. Auto-extraction rules

`data/config/supply_auto_extract.yaml`:

```yaml
# When news_ingest emits a Catalyst with these categories, the supply ledger
# iterator auto-creates a Disruption row. These are LOW-confidence starting
# points — Chris updates them via /disrupt-update with real numbers.

mappings:
  - catalyst_category: physical_damage_facility
    facility_type: refinery            # default; regex heuristic may refine
    confidence: 2
    status: active

  - catalyst_category: shipping_attack
    facility_type: ship
    confidence: 2
    status: active

  - catalyst_category: chokepoint_blockade
    facility_type: chokepoint
    confidence: 3
    status: active
```

**Heuristic refinement** (in `modules/supply_ledger.py`, not YAML):
- If headline mentions "pipeline" → `facility_type: pipeline`
- If headline mentions "terminal" → `facility_type: terminal`
- If headline mentions "oilfield" or "oil field" → `facility_type: oilfield`
- Otherwise fall back to YAML default

**Region classifier** (pure-Python keyword → canonical region):
- `{"russia", "volgograd", "moscow", "ryazan", "samara"}` → `russia`
- `{"iran", "iranian", "tehran", "abadan"}` → `iran`
- `{"saudi", "arabia", "ras tanura", "abqaiq"}` → `saudi`
- `{"hormuz"}` → `hormuz_strait`
- `{"red sea", "bab-el-mandeb", "houthi"}` → `red_sea`
- `{"suez"}` → `suez`
- `{"malacca"}` → `malacca_strait`
- `{"cushing", "permian", "eagle ford", "gulf of mexico", "us gulf"}` → `us_gulf`
- Otherwise `unknown`

## 5. Aggregation math

Called every `recompute_interval_s` (default 300):

1. Read `data/supply/disruptions.jsonl`.
2. Group by `id`, keep only the latest row per id (by `updated_at`) — this is how `/disrupt-update` works.
3. Filter to `status in ("active", "partial")`.
4. For `active`, use full `volume_offline`. For `partial`, use `volume_offline * 0.5`.
5. Sum by region, by facility_type, by unit (bpd vs mcfd — separate totals).
6. `active_chokepoints` = list of disruptions with `facility_type == "chokepoint" and status != "restored"`.
7. `high_confidence_count` = count where `confidence >= 4`.
8. Write `SupplyState` to `data/supply/state.json` (full overwrite, atomic via tmp+rename).

## 6. Telegram surface (deterministic, NOT AI)

### `/supply`
Shows latest `SupplyState` from `data/supply/state.json`. Format:
```
🛢️ Supply state (computed 2026-04-09 06:15 UTC)

Total offline: 2,400,000 bpd + 180 mcfd
Active disruptions: 14 (high-confidence: 6)

By region:
  russia       1,200,000 bpd
  red_sea        800,000 bpd
  iran           400,000 bpd

By type:
  refinery     1,450,000 bpd
  pipeline       600,000 bpd
  ship           200,000 bpd

Active chokepoints: hormuz_strait, red_sea
```

### `/disruptions`
Lists top N active disruptions by `confidence * volume_offline`, newest first. Default N=10.

### `/disrupt`
Structured entry. Minimum args: `facility_type` + `location`. Optional: volumes, dates, status.
```
/disrupt refinery Volgograd 200000 bpd active 2026-04-08 "drone strike, 2-3 week repair"
```
Positional parser:
1. `facility_type` (required)
2. `location` (required)
3. `volume` (optional, numeric)
4. `volume_unit` (optional, `bpd` or `mcfd`)
5. `status` (optional, default `active`)
6. `incident_date` (optional ISO date, default today)
7. Remaining quoted string → `notes`

If parsing fails, bot replies with the expected format.

### `/disrupt-update`
```
/disrupt-update <id_prefix> status=restored expected_recovery=2026-04-15
```
Appends a new Disruption row with the same `id` as the matched record, `updated_at` now, and the updated fields merged in. Append-only preserves history.

### Five-surface checklist (CLAUDE.md §Slash Commands point 3)
For each of `/supply`, `/disruptions`, `/disrupt`, `/disrupt-update`:
1. Handler
2. HANDLERS dict (`/cmd` + bare `cmd` forms)
3. `_set_telegram_commands()` menu list
4. `cmd_help()` entry
5. `cmd_guide()` entry

## 7. Iterator behaviour

`cli/daemon/iterators/supply_ledger.py`:

- `name = "supply_ledger"`
- Registers in all 3 tiers (read-only, safe everywhere)
- Per tick:
  1. mtime-watch `data/news/catalysts.jsonl`. If changed, read the new entries since last tick.
  2. For each new Catalyst with category in the auto-extract mapping, call `supply_ledger.auto_extract_from_catalyst()` → Disruption, dedupe by id against existing disruptions.jsonl (skip if already present), append.
  3. If `(now_mono - last_recompute) >= recompute_interval_s` (default 300), call `supply_ledger.compute_state()` and atomic-write `state.json`.
  4. Telegram alert (severity=info) when a new auto-extracted Disruption with `facility_type in ("chokepoint", "refinery")` lands — one line, deduped by Disruption.id.

## 8. Configuration

`data/config/supply_ledger.json`:
```json
{
  "enabled": true,
  "auto_extract": true,
  "recompute_interval_s": 300,
  "disruptions_jsonl": "data/supply/disruptions.jsonl",
  "state_json": "data/supply/state.json",
  "auto_extract_rules": "data/config/supply_auto_extract.yaml"
}
```

## 9. Tests (TDD, required)

Grouped by file:

### `tests/test_supply_ledger.py` (unit — ~15 tests)
1. `Disruption` and `SupplyState` dataclasses construct + roundtrip to dict
2. `auto_extract_from_catalyst` — physical_damage_facility → Disruption with refinery default
3. `auto_extract_from_catalyst` — shipping_attack → facility_type=ship
4. `auto_extract_from_catalyst` — chokepoint_blockade → facility_type=chokepoint
5. Heuristic refinement — "pipeline" keyword overrides default refinery
6. Heuristic refinement — "oilfield" keyword overrides default refinery
7. Region classifier — "Volgograd refinery strike" → russia
8. Region classifier — "Houthi missile Red Sea tanker" → red_sea
9. Region classifier — unknown location → "unknown"
10. `compute_state` — empty file → zero totals
11. `compute_state` — 3 disruptions (2 active + 1 restored) → only active counted
12. `compute_state` — latest-row-per-id (update semantics)
13. `compute_state` — partial status halves volume_offline
14. `compute_state` — active_chokepoints list populated from chokepoint-type active entries
15. JSONL append preserves existing rows

### `tests/test_supply_ledger_iterator.py` (integration — ~5 tests)
1. Iterator has name "supply_ledger"
2. Kill switch `enabled: false` → tick is no-op
3. mtime watch: no change to catalysts.jsonl → no new disruptions
4. New catalyst added to catalysts.jsonl → auto-extracted Disruption lands in disruptions.jsonl
5. End-to-end: fixture catalyst (physical_damage_facility, severity 5) → Disruption extracted → state.json updated → Telegram alert appended

### `tests/test_telegram_supply_command.py` (Telegram — ~6 tests)
1. `cmd_supply` renders state.json into human-readable format
2. `cmd_supply` handles missing state.json gracefully
3. `cmd_disruptions` lists top N by confidence*volume
4. `cmd_disrupt` parses positional args into Disruption and appends to JSONL
5. `cmd_disrupt` rejects malformed input with helpful message
6. `cmd_disrupt_update` matches id prefix and appends updated row

## 10. Ship gates

- [ ] All ~26 tests passing
- [ ] Full suite ≥ baseline + new tests, no regressions
- [ ] Mock-mode end-to-end: new catalyst in catalysts.jsonl → Disruption lands → state.json recomputes
- [ ] Live daemon smoke test (`--mock --max-ticks 2`) — SupplyLedgerIterator starts cleanly, logs catalysts seen
- [ ] Wiki page `docs/wiki/components/supply_ledger.md` created
- [ ] Build-log entry added
- [ ] All 4 Telegram commands pass 5-surface checklist
- [ ] `/disrupt` smoke-tested via Telegram with a real manual entry

## 11. Out of scope (deferred)

- Ship tracking integration (`reference_aus_fuel_watch.md` points to an external repo; integration is a V2 / sub-system 3 concern)
- Satellite imagery ingestion
- EIA outage reports scraper
- LLM-powered facility-name entity extraction (V1 uses pure keyword heuristics)
- Auto-recovery date estimation (V1 leaves `expected_recovery=None` unless user provides it)
- Cross-source disruption clustering (sub-system 4's job)
- Integration with strategy engine (sub-system 5's job)

## 12. Deviations from plan will be tracked in the build-log

Per the sub-system 1 precedent, any plan-code deviations found during implementation are fixed inline and recorded in the final build-log entry.
