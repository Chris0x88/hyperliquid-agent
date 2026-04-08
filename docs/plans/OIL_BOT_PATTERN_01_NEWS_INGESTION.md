# Sub-System 1 — News & Catalyst Ingestion

> **Parent:** `OIL_BOT_PATTERN_SYSTEM.md`
> **Status:** Approved 2026-04-09. Ready for implementation plan.
> **Constraint:** Additive only. Zero destructive changes to existing files.
> **Kill switch:** `data/config/news_ingest.json` → `enabled: false` no-ops the iterator.

---

## 1. Purpose and boundary

**One job:** turn public RSS feeds and iCal calendars into structured
catalyst records that downstream sub-systems consume. Nothing else.

**This sub-system DOES:**
- Poll RSS feeds and iCal calendars on a schedule
- Dedupe incoming headlines
- Tag headlines against a YAML rule library (categories + severity)
- Extract structured `Catalyst` records from tagged headlines
- Append catalysts above the severity threshold to the existing
  `data/daemon/catalyst_events.json` so the existing
  `CatalystDeleverageIterator` consumes them with zero behaviour change
- Emit Telegram alerts on severity ≥ 4 catalysts
- Expose two deterministic Telegram commands (`/news`, `/catalysts`)

**This sub-system does NOT:**
- Score sentiment (no NLP model in V1)
- Predict price direction beyond simple rule-based tagging
- Consume Twitter / X / Truth Social
- Modify thesis files
- Place trades
- Track physical disruptions (that is sub-system 2)
- Editorialise or summarise headlines with an LLM

## 2. Data flow

```
 RSS feeds                    iCal calendars
 (per data/config/             (EIA, OPEC, FOMC,
  news_feeds.yaml)              ECB schedules)
      │                              │
      ▼                              ▼
  ┌───────────────────────────────────────┐
  │ news_ingest iterator (WATCH tier)     │
  │  • polls per-feed, throttled          │
  │  • dedupes by sha256(source+url+title)│
  │  • appends raw → headlines.jsonl      │
  └───────────────┬───────────────────────┘
                  │
                  ▼
  ┌───────────────────────────────────────┐
  │ news_engine (pure logic, modules/)    │
  │  • keyword/regex tagger (rules.yaml)  │
  │  • severity 1-5 (rule-based)          │
  │  • date parser (event_date or pub)    │
  │  • emits Catalyst → catalysts.jsonl   │
  └───────────────┬───────────────────────┘
                  │
                  ▼
  ┌───────────────────────────────────────┐
  │ catalyst_feeder                       │
  │  • severity ≥ severity_floor →        │
  │    converts each Catalyst → one       │
  │    CatalystEvent per instrument       │
  │    (one-to-many fan-out)              │
  │  • appends converted events to        │
  │    data/daemon/external_catalyst_     │
  │    events.json (NEW file, separate    │
  │    from existing state file)          │
  │  • CatalystDeleverageIterator's tick  │
  │    prologue mtime-watches that file   │
  │    and merges via add_external_       │
  │    catalysts() (deduped by name)      │
  │  • severity ≥ alert_floor → Telegram  │
  │    alert via existing alert path      │
  └───────────────────────────────────────┘
```

## 3. Files

All additive. Zero destructive changes. Edits to existing files are
strictly extensions, not rewrites.

### New files

| File | Purpose |
|---|---|
| `modules/news_engine.py` | Pure logic: feed parser, dedupe, tagger, severity score, catalyst extractor. Fully unit-testable. No I/O except via injected sources. |
| `cli/daemon/iterators/news_ingest.py` | Daemon iterator. Polls feeds, throttles per source, writes JSONL, calls `catalyst_feeder`. |
| `data/config/news_feeds.yaml` | Feed registry: URL, source name, poll interval, weight, categories. |
| `data/config/news_rules.yaml` | Keyword/regex rules → category + severity. Editable without code changes. |
| `data/config/news_ingest.json` | Runtime config: `enabled`, `severity_floor`, `alert_floor`, `default_poll_interval_s`. |
| `data/news/headlines.jsonl` | Raw headline log, append-only (created at first run). |
| `data/news/catalysts.jsonl` | Structured catalysts, append-only (created at first run). |
| `tests/test_news_engine.py` | Unit tests: parser, dedupe, tagger, severity, extraction. |
| `tests/test_news_ingest_iterator.py` | Integration test: fixture feed XML → iterator tick → catalyst lands. |
| `tests/fixtures/news/*.xml` | Fixture feeds for tests (well-formed, malformed, edge cases). |

### Edited files (additive only)

| File | Edit |
|---|---|
| `cli/daemon/iterators/__init__.py` | Register `NewsIngestIterator` (one import + one entry). |
| `cli/daemon/tiers.py` | Add `NewsIngestIterator` to WATCH tier iterator list. |
| `cli/telegram_bot.py` | Add `cmd_news` and `cmd_catalysts` handlers. Apply five-surface checklist (handler, HANDLERS dict, `_set_telegram_commands` menu list, `cmd_help`, `cmd_guide`). Both commands deterministic — NO `ai` suffix. |
| `cli/daemon/iterators/catalyst_deleverage.py` | Two additive changes only: (1) new public method `add_external_catalysts(events: list[CatalystEvent])` merges new events into `self._catalysts`, deduping by `name`. (2) `tick()` gains a one-line prologue that calls `_load_external_catalysts_from_file()`, which mtime-watches `data/news/external_catalyst_events.json` and converts new entries via `add_external_catalysts()`. The existing constructor, state-loading, and processing logic are all unchanged. If the external file is missing or empty, behaviour is identical to today. |

## 4. Data model

```python
# modules/news_engine.py

@dataclass(frozen=True)
class Headline:
    id: str                  # sha256(source + url + title)
    source: str              # "reuters_energy"
    url: str
    title: str
    body_excerpt: str        # first 500 chars
    published_at: datetime
    fetched_at: datetime

@dataclass(frozen=True)
class Catalyst:
    id: str                  # sha256(headline_id + category)
    headline_id: str         # FK to Headline
    instruments: list[str]   # ["xyz:BRENTOIL", "CL", "BTC"]
    event_date: datetime     # parsed from headline OR = published_at
    category: str            # one of the 11 categories below
    severity: int            # 1-5
    expected_direction: str | None  # "bull" | "bear" | None
    rationale: str           # which rule fired, which keywords matched
    created_at: datetime
```

JSONL serialisation: one record per line, ISO-8601 datetimes, UTF-8.

## 5. Initial rule set

Lives in `data/config/news_rules.yaml`. Editable without code changes.
Each rule fires when ALL of its `keywords_all` and ANY of its
`keywords_any` lists match the lowercased headline+excerpt.

| # | Category | Match logic (any) | Severity | Direction | Affects |
|---|---|---|---|---|---|
| 1 | `trump_oil_announcement` | trump + (iran OR saudi OR opec OR sanctions OR deadline) | 4 | None | CL, BRENTOIL |
| 2 | `opec_action` | opec + (cut OR quota OR production OR meeting) | 4 | rule-conditional: cut→bull, increase→bear | CL, BRENTOIL |
| 3 | `eia_weekly` | eia + (crude OR inventories OR stockpile) | 3 | None (data-dependent) | CL, BRENTOIL |
| 4 | `geopolitical_strike` | (strike OR drone OR missile) + (refinery OR pipeline OR field OR oil OR terminal) | 5 | bull | CL, BRENTOIL |
| 5 | `cushing_storage` | cushing + (storage OR inventory OR build OR draw) | 3 | None (data-dependent) | CL primarily |
| 6 | `iran_deal` | iran + (deal OR deadline OR nuclear OR talks) | 4 | rule-conditional: deal→bear, collapse→bull | CL, BRENTOIL |
| 7 | `russia_oil` | russia + (oil OR sanctions OR pipeline OR refinery) | 4 | None (substance-dependent) | BRENTOIL primarily |
| 8 | `fomc_macro` | fomc OR fed + (rate OR hike OR cut OR pause) | 3 | rule-conditional: cut→bull, hike→bear | BTC, CL, BRENTOIL |
| 9 | `physical_damage_facility` | (refinery OR pipeline OR terminal OR oilfield OR "gas plant") + (strike OR drone OR missile OR fire OR explosion OR damage OR offline) | 5 | bull | CL, BRENTOIL |
| 10 | `shipping_attack` | (tanker OR vlcc OR ship OR vessel OR shipping) + (strike OR attack OR drone OR missile OR fire OR detained OR seized) | 5 | bull | CL, BRENTOIL |
| 11 | `chokepoint_blockade` | (hormuz OR "bab-el-mandeb" OR suez OR malacca OR "red sea" OR strait) + (block OR closed OR halt OR detain OR attack) | 5 | bull | CL, BRENTOIL |

**Why most rules tag `direction=None`:** sub-system 4 (bot-pattern
classifier) is what figures out which way to fade. Sub-system 1's job is
to PUBLISH the catalyst, not predict it. Only the rules where the
direction is unambiguous from the keywords alone (physical damage,
shipping attacks, chokepoint blockades — all bullish) carry a default
direction.

**Rule-conditional direction:** rules 2, 6, 8 use a small post-tag
substring check to set direction. The check lives in `news_engine.py`
as a per-rule callable, not in YAML. New rule-conditional rules require
a code edit; pure keyword rules do not.

Example for rule 2 (`opec_action`):

```python
def direction_for_opec_action(headline_text: str) -> str | None:
    text = headline_text.lower()
    if any(w in text for w in ("cut", "reduce", "lower")):
        return "bull"
    if any(w in text for w in ("increase", "raise", "boost", "ramp")):
        return "bear"
    return None
```

Same shape for `iran_deal` (deal/agreement→bear, collapse/walk-out/breakdown→bull)
and `fomc_macro` (cut/dovish→bull, hike/hawkish→bear). All three callables
are pure functions, fully unit-testable, and live in
`modules/news_engine.py` next to the rule library.

**Adding rules:** drop a new YAML block. The engine reloads the YAML on
next iterator start. No daemon restart for YAML changes is required at
ship time, but is OK if needed.

## 6. Initial feed list

Lives in `data/config/news_feeds.yaml`. All free public RSS, no auth.

```yaml
feeds:
  - name: reuters_energy
    url: https://www.reuters.com/business/energy/feed/
    poll_interval_s: 60
    weight: 0.9
    categories: [oil, energy]
  - name: oilprice_main
    url: https://oilprice.com/rss/main
    poll_interval_s: 120
    weight: 0.8
    categories: [oil, energy]
  - name: eia_today_in_energy
    url: https://www.eia.gov/rss/todayinenergy.xml
    poll_interval_s: 300
    weight: 0.95
    categories: [oil, energy, fundamentals]
  - name: ap_top
    url: https://feeds.apnews.com/rss/apf-topnews
    poll_interval_s: 60
    weight: 0.7
    categories: [macro, geopolitical]
  - name: argus_oil
    url: TBD_AT_BUILD_TIME
    poll_interval_s: 120
    weight: 0.9
    categories: [oil, energy]
  - name: bloomberg_energy
    url: TBD_AT_BUILD_TIME
    poll_interval_s: 120
    weight: 0.85
    categories: [oil, energy]

icals:
  - name: eia_weekly_petroleum
    url: TBD_AT_BUILD_TIME
    categories: [oil, scheduled]
  - name: opec_meetings
    url: TBD_AT_BUILD_TIME
    categories: [oil, scheduled]
  - name: fomc_schedule
    url: TBD_AT_BUILD_TIME
    categories: [macro, scheduled]
```

URLs marked `TBD_AT_BUILD_TIME` are verified during implementation, not
in this spec. Failure to verify a URL drops that feed from V1; the
system runs with the verified subset and logs a warning.

## 7. Telegram surface

Two new commands. Both deterministic. Both pure code reading JSONL
files. Neither is AI-driven, so neither carries the `ai` suffix.

### `/news`

Output: last 10 catalysts ranked by `severity DESC, created_at DESC`.

```
🛢️ Latest catalysts (last 10)

5  ⚡ shipping_attack          2026-04-09 14:22 UTC
   "Houthi missiles strike VLCC in Red Sea, vessel ablaze"
   → CL, BRENTOIL  (bull)

5  ⚡ physical_damage_facility 2026-04-08 22:14 UTC
   "Drone strike hits Volgograd refinery, 200kbpd offline"
   → CL, BRENTOIL  (bull)

4  ⚠ trump_oil_announcement   2026-04-08 19:30 UTC
   "Trump sets 8 PM deadline for Iran nuclear deal"
   → CL, BRENTOIL

...
```

### `/catalysts`

Output: scheduled catalysts in next 7 days from iCal sources, plus any
non-scheduled catalysts with `event_date > now`.

### Five-surface checklist (per CLAUDE.md, mandatory)

For each new command (`/news` and `/catalysts`):
1. `cli/telegram_bot.py` — `def cmd_<name>(token, chat_id, args)` handler
2. HANDLERS dict — register both `/cmd` and bare `cmd` forms
3. `_set_telegram_commands()` list — `{"command": ..., "description": ...}` for menu UI
4. `cmd_help()` — one-line entry under the right section
5. `cmd_guide()` — entry under the relevant user-facing section

### High-severity alerts

Catalysts with `severity >= alert_floor` (default 4) emit a one-line
Telegram alert via the existing alert path on first observation. Format:

```
🛢️ NEW CATALYST  sev=5  shipping_attack
"Houthi missiles strike VLCC in Red Sea, vessel ablaze"
→ CL, BRENTOIL  (bull)
source: reuters_energy
```

The alerter dedupes by `Catalyst.id` so re-polling the same headline
does not re-fire the alert.

## 8. Configuration

`data/config/news_ingest.json`:

```json
{
  "enabled": true,
  "severity_floor": 3,
  "alert_floor": 4,
  "default_poll_interval_s": 60,
  "max_headlines_per_tick": 50,
  "headlines_jsonl": "data/news/headlines.jsonl",
  "catalysts_jsonl": "data/news/catalysts.jsonl"
}
```

- `enabled: false` → iterator no-ops on tick. Existing
  CatalystDeleverageIterator continues to read its hand-curated JSON
  file as it does today. Zero regression. This is the kill switch.
- `severity_floor` → catalysts below this severity are written to
  `catalysts.jsonl` but NOT fed into `catalyst_events.json`.
- `alert_floor` → catalysts below this severity do not emit Telegram
  alerts.

## 9. Tests (TDD; required before any iterator code lands)

The test suite is the contract. All tests live under
`agent-cli/tests/`. Run with:

```
cd agent-cli && .venv/bin/python -m pytest tests/test_news_engine.py tests/test_news_ingest_iterator.py -x -q
```

| # | Test | What it proves |
|---|---|---|
| 1 | `test_parse_atom_feed_well_formed` | Atom 1.0 parser handles real Reuters feed |
| 2 | `test_parse_rss20_well_formed` | RSS 2.0 parser handles real OilPrice feed |
| 3 | `test_parse_malformed_feed_returns_empty` | Malformed XML does not crash |
| 4 | `test_dedupe_same_headline_twice` | Same headline polled twice → one Headline record |
| 5 | `test_dedupe_url_changes_but_title_stable` | URL changes (tracking params) but title stable → still deduped |
| 6 | `test_rule_trump_oil_announcement_fires` | "Trump deadline Iran" headline → category fires |
| 7 | `test_rule_physical_damage_fires` | "Drone strike refinery" → severity 5, direction bull |
| 8 | `test_rule_shipping_attack_fires` | "Houthi missile tanker Red Sea" → severity 5, direction bull |
| 9 | `test_rule_chokepoint_fires` | "Hormuz strait closed" → severity 5, direction bull |
| 10 | `test_rule_negative_no_false_positive` | "Trump tweets about golf" → no oil rule fires |
| 11 | `test_severity_threshold_filters_catalyst_events` | Severity 2 → not fed to catalyst_events.json |
| 12 | `test_severity_above_alert_floor_emits_alert` | Severity 5 → Telegram alert on first observation only |
| 13 | `test_alert_dedupe_on_second_observation` | Same Catalyst.id second time → no re-alert |
| 14 | `test_event_date_parser_relative_phrases` | "Trump's 8 PM ET deadline tomorrow" → correct UTC datetime |
| 15 | `test_catalyst_feeder_appends_without_corrupting_existing_json` | Existing catalyst_events.json entries are preserved |
| 16 | `test_iterator_handles_failing_feed_without_crashing_daemon` | One bad feed → others continue |
| 17 | `test_iterator_throttles_per_feed` | poll_interval_s respected; not all feeds polled every tick |
| 18 | `test_kill_switch_enabled_false_noop` | enabled=false → zero writes, zero alerts |
| 19 | `test_e2e_fixture_feed_to_catalyst_deleverage` | Mock-mode end-to-end: fixture feed → CatalystDeleverageIterator picks it up next tick |

Tests 1-15 are pure unit tests against `modules/news_engine.py`. Tests
16-19 are integration tests against the iterator and run in mock mode.

## 10. Ship gates (must pass before sub-system 2 starts)

Per `OIL_BOT_PATTERN_SYSTEM.md` §7:

- [ ] All 19 tests passing
- [ ] Mock-mode end-to-end run produces expected outputs against fixture feeds
- [ ] **Dry-run phase:** ≥ 24h with `enabled: true` AND `severity_floor: 5`. During this phase the iterator polls real RSS feeds, writes to `headlines.jsonl` and `catalysts.jsonl` normally, and emits Telegram alerts — but only severity-5 catalysts get converted into the external catalyst-events file, so the existing `CatalystDeleverageIterator` only sees the highest-confidence inputs while we're trialling. Verify alerts fire on real catalysts and do not duplicate. Verify no severity-3/4 entries reach `external_catalyst_events.json`.
- [ ] **Promotion:** after dry-run passes, lower `severity_floor` to `3` for normal operation. This is a config edit, no code change.
- [ ] Wiki page `agent-cli/docs/wiki/components/news_ingest.md` created
- [ ] `CLAUDE.md` updated with one line under the daemon iterator list
- [ ] Build-log entry under `agent-cli/docs/wiki/build-log.md`
- [ ] `/news` and `/catalysts` commands smoke-tested via Telegram on mainnet

## 11. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| RSS feed URL changes upstream | High | Single feed silently stops working | Per-feed `last_successful_fetch_at` tracked; warn after 2× expected interval; daily Telegram summary lists stale feeds |
| Headline floods (e.g. major event) blow context | Medium | Daemon CPU spike, memory bloat | `max_headlines_per_tick` bound; per-feed throttle |
| False-positive rule fires | Medium | Noise alerts | severity_floor + alert_floor are dials, not removals; rule library is YAML-editable; bad rules are easy to disable |
| Existing CatalystDeleverageIterator behaviour changes | Low | Regression in already-shipped path | Edit to `catalyst_deleverage.py` is strictly additive (`_load_external_catalysts` is optional, falls back to current behaviour if catalysts.jsonl missing); existing tests must continue to pass unchanged |
| Source publishes paywalled URLs | Medium | Can't fetch body excerpt | Excerpt is best-effort, headline alone is sufficient for tagging; do not block on excerpt |
| Same news from multiple sources | High | Multiple Catalyst records for the same event | V1 dedup is per-source; cross-source dedup is V2 (sub-system 4 will do better signal-level dedup using clustering) |

## 12. Out of scope (deferred to other sub-systems or later versions)

- Sentiment scoring → sub-system 4
- Price-impact prediction → sub-system 5
- Twitter/X feeds → deferred indefinitely
- LLM-based headline summarisation → deferred indefinitely
- Auto-tuning the rule weights → sub-system 6
- Cross-source event clustering → sub-system 4 (with classifier output)
- Promoting CL to thesis_engine → sub-system 5

## 13. Open implementation questions

These get answered during the writing-plans phase, not now:

1. Which Python feed-parsing library: `feedparser` (mature, ~2k LoC dep) vs `defusedxml + manual parser` (zero dep, more code)? Recommend `feedparser` — already in many Python data-science envs and is the de-facto choice. Note: this is the first external dep added specifically for this sub-system; CLAUDE.md's "zero external deps by default" rule requires explicit user approval at the writing-plans stage.
2. Where do iCal parsers live: `icalendar` package, or hand-rolled? Recommend `icalendar` (small, well-maintained, MIT). Same approval requirement as #1.
3. Initial fixture feeds: real captured Reuters/OilPrice XML or synthetic? Recommend real captured (more realistic edge cases).
4. Should `news_ingest.py` run on a separate thread or be tick-driven? Tick-driven is safer (single-instance daemon model), polling throttle handled per-feed.
5. Does the catalyst_feeder conversion (Catalyst → CatalystEvent, one-per-instrument) live in `news_engine.py` or in a new `modules/catalyst_bridge.py`? Recommend the latter — keeps `news_engine.py` pure and testable without importing daemon types, and keeps the bridge in one place when sub-system 2 (supply ledger) also needs to write catalysts.
6. What happens if the same underlying event produces multiple headlines (e.g. Reuters and AP both cover the same Houthi strike)? V1: per-source dedup only; each source produces its own Catalyst; downstream sub-system 4 handles cross-source clustering. Documented in §11 risks table.
