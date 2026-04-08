# Build Log

Chronological record of architecture changes, incidents, and milestones. Most recent first.

---

## 2026-04-09 — Oil Bot-Pattern Sub-System 2 shipped

- **What:** Supply Disruption Ledger. Auto-extracts structured disruption records from sub-system 1 catalysts, accepts manual entries via Telegram, aggregates into SupplyState consumed by later sub-systems.
- **Shape:** `modules/supply_ledger.py` (pure logic), `cli/daemon/iterators/supply_ledger.py` (daemon iterator, all 3 tiers), 4 Telegram commands (`/supply`, `/disruptions`, `/disrupt`, `/disrupt-update`), YAML auto-extract rules.
- **Storage:** JSONL append-only at `data/supply/disruptions.jsonl` with latest-per-id semantics; aggregated `state.json` atomic-written every 5 min.
- **Tests:** ~26 (unit + iterator + Telegram), full suite green.
- **Plan:** `docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER_PLAN.md`
- **Next:** Sub-system 3 (stop/liquidity heatmap).

---

## 2026-04-09 — Oil Bot-Pattern Sub-System 1 shipped

- **What:** First sub-system of the Oil Bot-Pattern Strategy ships — news & catalyst ingestion.
- **Why:** Chris identified that bot-driven mispricing around scheduled catalysts (e.g. Trump's 8 PM Iran deadline) leaves systematic arbitrage on the table for a petroleum-engineer operator. Sub-system 1 is the foundation: scraped headlines → structured catalysts → existing deleverage pipeline.
- **Shape:** New `modules/news_engine.py` (pure logic), `modules/catalyst_bridge.py` (Catalyst → CatalystEvent conversion), `cli/daemon/iterators/news_ingest.py` (WATCH/REBALANCE/OPPORTUNISTIC tiers). Additive-only edits to `cli/daemon/iterators/catalyst_deleverage.py` (new `add_external_catalysts()` method + `tick()` file-watcher prologue). Two new Telegram commands: `/news`, `/catalysts` (both deterministic, not AI).
- **Deps added:** `feedparser>=6.0.10`, `icalendar>=7.0.3`. User-approved in spec §13. (Plan called for `icalendar>=5.0.0`; shipped with v7 — API verified compatible.)
- **Kill switch:** `data/config/news_ingest.json` → `enabled: false`.
- **Tests:** ~15 new tests across `tests/test_news_engine.py`, `tests/test_catalyst_bridge.py`, `tests/test_catalyst_deleverage_external.py`, `tests/test_news_ingest_iterator.py`, and `tests/test_telegram_news_command.py`. Full suite: **2084 passing** (excluding `tests/test_agent_tools_lessons.py` — parallel-session WIP).
- **Dry-run:** 24h live-mode dry-run at `severity_floor: 5` is still **pending** — operational gate, not a code task. Promotion to `severity_floor: 3` happens only after dry-run passes.
- **Plan deviations:**
  - Task 1.9 — regex fix applied to rule tagger during implementation.
  - Task 3.2 — test import paths adjusted to match `modules/` layout.
  - Task 5.1 — iterator entry point wiring tweaked vs. plan.
  - `_send_message` → `tg_send` (Telegram helper renamed in-flight to match existing surface).
  - `icalendar` v7 API verified directly — `vDDDTypes`/component walk unchanged from v5 for our use.
- **Next:** Run the 24h dry-run. Then sub-system 2 — Supply Disruption Ledger (separate brainstorm).
- **Plan:** `docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION_PLAN.md`

---

## 2026-04-09 — Trade Lesson Layer Ships (parallel session) + Test Coverage + NameError Fix

**Two Claude sessions converged on the same design.** In the morning, Chris asked
an Opus session about integrating `github.com/milla-jovovich/mempalace` (a
brand-new viral memory library). That session produced a tailored design
(`.claude/plans/bubbly-juggling-fountain.md`) that rejected mempalace on three
converging grounds (`feedback_no_mcp.md`, `CLAUDE.md` rule #3 "zero external
deps", `feedback_no_external_parties.md`) and proposed instead a
stdlib-only Trade Lesson Palace built on SQLite FTS5 over a new `lessons`
table in the existing `data/memory/memory.db`. Independently and in parallel,
a Sonnet 4.6 session worked through essentially the same approach and shipped
the data layer as commit `7ac7bea`:

- `common/memory.py` — new `lessons` table, FTS5 virtual table
  (`lessons_fts`), three triggers (`lessons_ai` for insert-FTS-sync,
  `lessons_append_only` blocking updates on 14 frozen content columns,
  `lessons_tags_au` keeping FTS in sync when tags are curated), four b-tree
  indexes, four module-level helpers (`log_lesson`, `get_lesson`,
  `search_lessons`, `set_lesson_review`), and `_fts5_escape_query` to
  neutralise FTS5 operators in user/agent input
- `modules/lesson_engine.py` — pure-computation `Lesson` dataclass,
  `LessonAuthorRequest` (verbatim context bundle), sentinel-wrapped
  `build_lesson_prompt()`, strict `parse_lesson_response()` that raises
  `ValueError` on missing/invalid sentinels (follows the 2026-04-08 Bug A
  "refuse to write garbage records" pattern from the journal iterator)
- `docs/plans/OIL_BOT_PATTERN_SYSTEM.md` and
  `docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md` — separate strategic
  workstream, unrelated to the lesson layer

**The Opus session's alignment check ran before the parallel commit landed.**
`git log --grep='alignment:'` at session start showed `d66ac9f` as the most
recent alignment commit. The Sonnet session committed `7ac7bea` a few hours
later (2026-04-09 04:32:43 local). The Opus session had moved on to writing
files and didn't re-run the alignment check. When it later called `Write` on
`modules/lesson_engine.py`, the on-disk file from the Sonnet commit was
already there. Because both sessions followed the same detailed plan, the
Opus version converged byte-for-byte (same MD5) with the Sonnet version —
not exact collaboration, but close enough that `Write` appeared to succeed
without apparent conflict. Same story for `common/memory.py`: the Opus Edits
found their target text already present in the committed version. This is
the second manifestation of the 2026-04-07 postmortem pattern — assuming
your plan is the active phase without re-checking when the wall-clock gap
between alignment-check and commit is non-trivial. **The rule to add to the
session protocol: re-run the alignment grep immediately before committing
any non-trivial new work, not only at session start.**

**The 77 tests authored by the Opus session caught a real latent bug.**
`_fts5_escape_query` in `common/memory.py` (committed in `7ac7bea`) calls
`re.split()` but the file never imports `re`. Any call to
`search_lessons(query="non-empty")` raised `NameError: name 're' is not
defined`. `tests/test_lesson_memory.py::TestSearchLessons::test_fts_query_ranks_relevant_first`
(and every other `_fts_*` test) surfaced the bug on first run. Verified by
stashing the one-line `+import re` fix and re-running the test — fails as
expected. Re-applied and it passes. The fix and the test files shipped
together as commit `3027b00`:

- `common/memory.py` — one-line `import re` addition
- `tests/test_lesson_engine.py` — 42 tests covering the pure-computation
  layer: `Lesson` roundtrip incl. JSON-string tag coercion, outcome
  classification boundaries (breakeven is |roe_pct|<0.5), `LessonAuthorRequest`
  stable section ordering and empty-section skipping, prompt sentinel
  presence, response-parsing happy paths, and all five failure modes
  (missing sentinels, invalid lesson_type, invalid direction, empty summary,
  malformed tags); tag dedup/cap/lowercasing; body_full sentinel stripping;
  verbatim-context safety net
- `tests/test_lesson_memory.py` — 35 tests covering schema migration (tables,
  indexes, triggers, idempotency), insert/get roundtrip with nullable fields,
  `CHECK` constraint enforcement, FTS5 BM25 ranking across a 4-lesson seed,
  every filter dimension (market, direction, signal_source, lesson_type,
  outcome), combined filters with query, limit, rejected-exclusion-by-default
  and opt-in, FTS5 injection resistance (operator chars, quotes, parens,
  wildcards, NOT/AND/OR), curation (approve/reject/unreview), append-only
  trigger on 14 frozen columns, `reviewed_by_chris` and tags mutability
  preserved, tags-update keeps FTS5 in sync

### What's shipped vs what's still open on the lesson layer

| Layer | Status |
|---|---|
| `lessons` table + FTS5 + triggers | Shipped (`7ac7bea`) |
| `log_lesson` / `get_lesson` / `search_lessons` / `set_lesson_review` helpers | Shipped (`7ac7bea`) |
| `modules/lesson_engine.py` (dataclass, prompt, parser) | Shipped (`7ac7bea`) |
| Test coverage for the above | Shipped (`3027b00`) |
| `import re` fix in `common/memory.py` | Shipped (`3027b00`) |
| `cli/daemon/iterators/lesson_author.py` (lesson-writer iterator) | **Not built** |
| `search_lessons` + `get_lesson` in `cli/agent_tools.py` | **Not built** |
| `RECENT RELEVANT LESSONS` section in `cli/agent_runtime.py:build_system_prompt()` | **Not built** |
| `/lessons` + `/lesson` + `/lessonsearch` in `cli/telegram_bot.py` | **Not built** |
| `agent/reference/tools.md` + `agent/AGENT.md` updates | **Not built** |
| `common/thesis.py:snapshot_to_disk()` helper (for `thesis_snapshot_path`) | **Not built** (verify H6 backup coverage first) |

Until the iterator ships, the table is an empty shell — no lessons will be
written without a catalyst. The agent tools and prompt injection are
read-only against that empty table. Chris deferred the wiring work to a
future session per `.claude/plans/bubbly-juggling-fountain.md`.

### Pattern: re-run the alignment check immediately before committing

The `d66ac9f`-based alignment check at the start of the Opus session was
valid at the moment it ran, but lost accuracy the moment another session
committed. This is the second time in three days the codebase has punished
stale alignment-check state (see 2026-04-07 postmortem for the first). The
cheap fix is a habit change: before any `git add` / `git commit` of
non-trivial new files, re-run `git log --grep='alignment:' -1` and then
`git log <hash>..HEAD` against the current HEAD. If the grep now returns a
newer alignment commit than the session started with, STOP and re-audit
before proceeding. The 20-second cost beats the N-hours cost of rediscovering
the convergence later.

### Verification

- `pytest tests/test_lesson_engine.py tests/test_lesson_memory.py -x -q` —
  passes
- `pytest tests/ -x -q` — full suite passes, zero regressions
- Bug reproduction: `git stash push common/memory.py && pytest
  tests/test_lesson_memory.py::TestSearchLessons::test_fts_query_ranks_relevant_first`
  → `NameError: name 're' is not defined`; `git stash pop` → passes
- Byte-identity of `modules/lesson_engine.py` confirmed via `md5` against
  `git show HEAD:modules/lesson_engine.py | md5` — identical

### Files touched

```
common/memory.py                       (+1 line:  import re)
tests/test_lesson_engine.py            (new)
tests/test_lesson_memory.py            (new)
docs/wiki/build-log.md                 (this entry)
docs/wiki/architecture/data-stores.md  (lessons table row + memory.db schema)
docs/wiki/architecture/current.md      (remove stale '6-table store' label)
docs/wiki/components/ai-agent.md       ('built, not yet wired' note on lessons)
modules/CLAUDE.md                      (lesson_engine row)
common/CLAUDE.md                       (memory.py row added — was missing)
docs/plans/MASTER_PLAN.md              (lesson layer in What Has Shipped)
```

### Retrospective

**What worked:** Writing tests against a design instead of against a
specific implementation meant the tests passed against the parallel
session's work without modification. The sentinel-wrapped prompt format
in `lesson_engine.py` is strict enough that the parser's failure modes are
enumerable and testable. The append-only trigger is simple (`BEFORE UPDATE
OF col1, col2, ...`) and lets the curation columns (`reviewed_by_chris`,
`tags`) stay mutable without extra bookkeeping.

**What went wrong:** The Opus session burned ~20 minutes writing code that
already existed because the alignment check went stale. Would have been
avoided by a 20-second re-grep immediately before committing.

**What to do differently next time:** (1) Every Claude session that writes
code must re-run the alignment grep right before staging changes, not just
at the start. (2) When two sessions work from the same detailed plan,
convergence is possible but not guaranteed — the test suite is the only
reliable way to detect behavioural divergence between parallel
implementations. Write tests against the *contract* (dataclass fields,
function signatures, invariants), not against internal implementation
details, so the tests transfer across convergent implementations.

---

## 2026-04-09 — Calibration + /restart + Oil Bot Pattern System Approved

### Liquidation monitor threshold recalibration

Default thresholds (`crit<10%`, `warn<20%`) were built for 2-5x retail traders.
Production journal data showed avg leverage of 19.8x (range 17-24x) with typical
entry-to-liquidation cushions of 2-3%. A 6.5% cushion was firing CRITICAL every
tick as a result.

New thresholds: `safe>=6%`, `warn 2-6%`, `crit<2%`. All 19 tests updated to
match new bands, 1969 still passing.

### /restart telegram registration

`cmd_restart` was implemented and in HANDLERS but missing from all three
visibility surfaces (`_set_telegram_commands`, `cmd_help`, `cmd_guide`). Added
to all three. No behaviour change — command already worked, just invisible to
the menu.

### Oil Bot Pattern System — Approved for implementation

Brainstormed and approved a new oil-trading subsystem that exploits
bot-driven mispricing on CL (WTI) and BRENTOIL by combining RSS news
ingestion, physical supply disruption tracking, orderbook stop-cluster
detection, and bot-pattern classification into a fixed, bounded strategy.

Key design decisions captured in `docs/plans/OIL_BOT_PATTERN_SYSTEM.md`:
- 6 sub-systems built in strict sequence with kill switches and ship gates
- Additive-only: does NOT replace the existing BRENTOIL thesis path
- **Scoped oil short relaxation** (sub-system 5 only): SHORT permitted on CL/BRENTOIL
  when bot-pattern classifier fires `bot_driven_overextension` at ≥0.7 confidence,
  no bullish catalyst pending, no recent supply disruption, size ≤50% long budget,
  24h hard cap, 1.5% daily loss cap. All other oil shorting remains forbidden.
- The long-standing "LONG or NEUTRAL only on oil — never short" rule in CLAUDE.md
  and memory is updated at sub-system 5 ship time, not now.
- `OIL_BOT_PATTERN_01_NEWS_INGESTION.md` drafted: 19-test TDD spec for RSS + iCal
  ingestion, rule-based catalyst tagging, existing CatalystDeleverageIterator
  integration. Sub-system 1 is next to build.

**Pattern:** separate alert/monitoring semantics from sizing semantics. See ADR-013.

---

## 2026-04-08 -- Alert Numbers + Format Postmortem (4 commits, 45 new tests)

**Production incident: trade closed alerts on the morning of 2026-04-08 reported
``exit=$0.00 PnL=+$2840.95 (+100.0%)`` for closed positions on a sub-$1000
account. The bogus PnL was simultaneously written to
``data/research/journal.jsonl`` which feeds the AI agent's reflection loop —
so the agent has been learning from hallucinated wins/losses since the
journal iterator went into production. Chris flagged it after a morning trading
session: "all the alerts are showing wrong numbers" and "alerts as they come
to me are not in a human friendly readable format". Four distinct bugs found
during root-cause investigation, all fixed in one session with zero
regressions across the suite (1924 → 1969 tests).**

### What shipped

| ID | Bug | Commit | Files | Tests |
|---|---|---|---|---|
| **A** | `journal` exit_price=$0 → garbage PnL — `ctx.prices` empty for closed positions, lookup returned 0, PnL = (entry - 0) × size produced fake numbers | `988aea0` | `iterators/journal.py` | 6 in `test_journal_iterator_exit_price.py` |
| **B** | `ctx.balances["USDC"]` was native-perps-only — alerts reported a different equity than `/status` | `5839b23` | `daemon/context.py`, `iterators/connector.py`, `iterators/journal.py` | 5 in `test_connector_native_positions.py::TestConnectorTotalEquity` |
| **C** | TelegramIterator sent with `parse_mode="HTML"` while alerts contained markdown — backticks and asterisks rendered as literal characters | `f014188` | `iterators/telegram.py` | 7 in `test_telegram_iterator_format.py` |
| **D** | Cryptic key=value alert strings (`mark=89500.0000 liq=82150.0000`) — no `$`, no thousands separator, 4-decimal precision regardless of scale | `1d3cec1` | `iterators/_format.py` (new), `liquidation_monitor.py`, `protection_audit.py`, `account_collector.py`, `risk.py` | 27 in `test_iterator_format_helpers.py` |

### Root cause: Bug A — exit price resolution

The journal iterator's close-detection path:

```python
exit_price = float(ctx.prices.get(prev.instrument, ZERO))
# ... PnL computed against this value
```

But `connector.py:167-177` only fetches mark prices for instruments in
`ctx.positions` on the current tick. When a position closes between tick N
and tick N+1, the connector skips it (no longer in the list), so
`ctx.prices` has no entry for that instrument and the lookup returns 0.

Real production logs from this morning:

```
05:47:18 journal: Trade closed: LONG xyz:CL  entry=$116.33  exit=$0.00  PnL=-$4489.21 (-100.0%)
10:21:41 journal: Trade closed: SHORT xyz:CL entry=$94.54   exit=$0.00  PnL=+$2840.95 (+100.0%)
10:40:12 journal: Trade closed: LONG xyz:CL  entry=$96.25   exit=$0.00  PnL=-$1829.58 (-100.0%)
```

None of those PnLs are real — equity moved $597 → $607 → $560 → $505 → $193
in that window. The bogus PnL was being written to `journal.jsonl` and
ingested by the AI agent for reflection.

**Fix:** four-step resolution cascade in `_detect_position_changes`:

1. `ctx.prices[prev.instrument]` (zero-latency happy path)
2. `ctx.prices` stripped-coin match (xyz: compat)
3. `prev.current_price` (cached from previous tick — closest approximation)
4. `_fetch_mark_price_fallback()` — direct HL `allMids` API call
5. If all four sources return 0 → log error and **skip the record** (better
   to lose the entry than corrupt the journal)

### Root cause: Bug B — equity reporting

`cli/daemon/CLAUDE.md` already documented `total_equity = perps (native + xyz)
+ spot USDC`, and `telegram_bot._get_account_values()` (the working `/status`
helper) summed all three. But `connector.py:52-59` only read native HL
`account_value` from `get_account_state()` and stored it in
`ctx.balances["USDC"]`. Every iterator that read that field thought it was
total equity but was actually getting native-only.

Two surfaces to fix this safely:
- **Alerts** (telegram periodic block, journal trade record) — must match
  `/status`, so they get the new total
- **Sizing** (`execution_engine`, `profit_lock`, `autoresearch`) — currently
  use native-only and were not flagged in the user complaint, so leaving them
  on the legacy field until a separate review confirms migration is safe

**Fix:** added `ctx.total_equity: float` (additive, defaults to 0). Connector
sums native + xyz + spot from the same `get_account_state()` and
`get_xyz_state()` calls it already makes — no extra API round-trip.
`ctx.balances["USDC"]` semantic is unchanged. See ADR-013 for the rationale
on the parallel-field approach.

### Root cause: Bug C — parse_mode mismatch

`iterators/telegram.py:186` was sending with `"parse_mode": "HTML"`. But
`account_collector.py` and `risk.py` had been emitting messages with
markdown backticks (`` `${equity:,.0f}` ``). Under HTML those rendered as
literal backtick characters in the user's chat. `telegram_bot.py:121` (the
working `/status` command path) has always used `"parse_mode": "Markdown"` —
the two surfaces had drifted.

**Fix:** flipped TelegramIterator to Markdown by default with a plain-text
fallback on parse error. Reformatted the periodic alert block + per-alert
output as labelled markdown sections.

### Root cause: Bug D — number formatting

`liquidation_monitor.py`, `protection_audit.py`, and journal trade-closed
alerts were all using `:.4f` format strings without `$` or thousands
separators. For BTC at $89,500 the operator received ``mark=89500.0000`` —
unreadable noise. For SP500 contract unit at 0.2746 the same `:.4f` was OK
but inconsistent across coins.

**Fix:** new `cli/daemon/iterators/_format.py` with:
- `fmt_price(x)` — adaptive `$X,XXX.XX` precision by magnitude
- `fmt_pnl(x)` — explicit `+$1,234.56` / `-$78.90` sign
- `fmt_pct(x)` — configurable percentage precision
- `dir_dot(x)` — 🟢 / 🔴 from net_qty or direction string

All four iterators now produce labelled markdown blocks the operator can
read at a glance.

### Pattern: separate alert from sizing semantics

Bug B's resolution illustrates a recurring tension: ``ctx.balances["USDC"]``
had two consumer classes — alerts (which need total equity) and sizing
(which had been operating fine on native-only). Changing the semantic in
place would have forced both consumer classes to migrate simultaneously,
risking a sizing change as a side effect of an alert fix. Adding a parallel
field decouples the two and lets each migrate on its own timeline. This is
the same pattern ADR-007 (Renderer ABC) used for separating presentation
from data.

### Pattern: refuse to write garbage records

Bug A's resolution introduces a small but important rule: **if you cannot
determine a value, do not write a record with a placeholder default**.
Better to log an error and skip the record (the operator can reconstruct it
from exchange fill history) than to write `exit=$0` and pollute the file
that feeds the AI agent's reflection. The same rule applies to any future
journaling code.

### Postmortem note: the daemon log was telling us all along

The full evidence of this bug was sitting in `data/daemon/daemon.log` —
six different ``exit=$0.00`` lines on 2026-04-08 between 05:47 and 10:40.
The morning chat shows the user noticing equity numbers that didn't match
what the daemon was reporting, but no one ran the daemon log against
`/status` until Chris explicitly demanded it. Lesson: when the user reports
"the numbers are wrong", grep the daemon log first — the answer is usually
already there in plain text.

### Verification

- ``cd agent-cli && .venv/bin/python -m pytest tests/ -x -q`` → 1969 passed,
  0 regressions, 12 pre-existing warnings (renderer return-vs-assert)
- 45 new tests across 4 new test files / 1 extended test file
- All 4 commits land on `public-release` branch in sequence: 988aea0,
  5839b23, f014188, 1d3cec1

### Files touched

```
cli/daemon/context.py                                 (+22 lines)
cli/daemon/iterators/connector.py                     (+24 lines)
cli/daemon/iterators/journal.py                       (+105 lines)
cli/daemon/iterators/telegram.py                      (+45 lines)
cli/daemon/iterators/liquidation_monitor.py           (+8 lines)
cli/daemon/iterators/protection_audit.py              (+45 lines)
cli/daemon/iterators/account_collector.py             (+18 lines)
cli/daemon/iterators/risk.py                          (+13 lines)
cli/daemon/iterators/_format.py                       (+92 lines, new)
tests/test_journal_iterator_exit_price.py             (+220 lines, new)
tests/test_telegram_iterator_format.py                (+170 lines, new)
tests/test_iterator_format_helpers.py                 (+115 lines, new)
tests/test_connector_native_positions.py              (+115 lines)
tests/test_protection_audit.py                        (+5 lines)
docs/wiki/decisions/013-parallel-equity-field.md      (+85 lines, new)
docs/wiki/build-log.md                                (this entry)
```

---

## 2026-04-07 -- H1-H8 Production Hardening (8 commits, 53 new tests)

**Eight production hardening items from ADR-012's roadmap shipped in one session.
All four P0 authority gaps closed, the active growth concern (ticks.jsonl)
rotated, all three SPOF stores backed up. Zero regressions across the suite
(1862 → 1885 tests).**

### What shipped

| ID | Description | Commit | Cell | Tests |
|---|---|---|---|---|
| **H1** | `exchange_protection` per-asset authority check (skip non-agent positions, cleanup on reclaim) | `37be8c7` | P4 DAEMON_GUARDS | 7 in `test_exchange_protection_authority.py` |
| **H2** | `execution_engine._process_market` explicit `is_agent_managed()` gate before any sizing math | `45df230` | P6 DAEMON_EXECUTION | 6 in `test_execution_engine_authority.py` |
| **H3** | `clock._execute_orders` defense-in-depth per-asset gate (CRITICAL alert if upstream leaked) | `5c20ada` | P3 DAEMON_HARNESS | 7 in `test_clock_authority_gate.py` |
| **H4** | `guard.tick` per-position authority + bridge teardown on reclaim | `0193191` | P4 DAEMON_GUARDS | 8 in `test_guard_authority.py` |
| **H5** | `ticks.jsonl` daily rotation (`ticks-YYYYMMDD.jsonl`) + 14-day retention pruning | `f8bbb57` | P6 DAEMON_EXECUTION | 9 in `test_journal_iterator_rotation.py` |
| **H6** | `data/thesis/*.json` dual-write to sibling `data/thesis_backup/` | `987edca` | P9 MEMORY_AND_KNOWLEDGE | 10 in `test_thesis_backup.py` |
| **H7** | `working_state.json.bak` dual-write (atomic .bak.tmp + rename) | `88b7fe5` | P7 HEARTBEAT_PROCESS | 6 in `test_heartbeat_state_backup.py` |
| **H8** | `funding.json.bak` dual-write (closes the irrecoverable history concern) | `d0a97d0` | P5 DAEMON_SIGNALS | 7 in `test_funding_tracker_backup.py` |

Plus housekeeping commit `4950b52` for `.gitignore` (brent_rollover.json +
data/strategies/) at the start of the session.

### Pattern: minimal-diff hardening per cell

Every fix followed the same template:

1. Read the file the verification ledger flagged
2. Apply the smallest possible patch to close the gap
3. Write a focused test file for the new behaviour
4. Run the per-cell smoke test to confirm zero regressions
5. Commit with a message that links the verification ledger gap, the cell
   from `work-cells.md`, the diff scope, the test results, and the production
   impact

This is the dispatch model from `work-cells.md` § "Cross-cell coordination
patterns" pattern 2 (one agent loads multiple cells when the work is small),
applied sequentially.

### Pattern: best-effort dual-write for SPOF stores (H6-H8)

Three stores were single-points-of-failure: `data/thesis/*.json`,
`data/memory/working_state.json`, `state/funding.json`. Each got the same
treatment:

1. Extract the existing JSON serialisation into a local variable
2. Keep the existing atomic primary write (.tmp + rename) unchanged
3. Add a best-effort backup write to a sibling location (sibling directory
   for thesis files since they live in a per-market dir, `.bak` suffix for
   single-file stores)
4. Wrap the backup write in try/except → log WARNING on failure, never
   propagate
5. Use the same atomic .bak.tmp + rename pattern for the backup itself

The result: each save() call now produces two byte-identical files. Recovery
procedure: `cp foo.json.bak foo.json` (or `cp -r data/thesis_backup/.
data/thesis/`). Verified by tests that delete the primary, rename the
backup, and reload successfully.

### Tier promotion gate status

Before this session: WATCH→REBALANCE was blocked by 4 latent authority gaps
in `exchange_protection`, `execution_engine`, `clock._execute_orders`, and
`guard`.

After this session: all 4 gaps closed in code AND covered by tests. The
operator-side checklist in `tier-state-machine.md` is the only remaining
gate (heartbeat launchd disable, 2-week WATCH validation period, etc.).

### What's NOT in this session

- H9 (OrderState lifecycle in `tickcontext-provenance.md`) — partial; covered
  in `master-diagrams.md` View 4 from the prior phase, but the provenance doc
  itself wasn't updated. Defer to a doc-only session.
- H11 (decompose `common/heartbeat.py` god-file) — deferred per ADR-012 P3.
- H12 (ADR-011 research-app split) — deferred per ADR-011.
- Tier promotion to REBALANCE — code is now ready, but the operator-side
  checklist still needs to run before flipping `--tier rebalance`.

### Test impact

| | Before | After | Delta |
|---|---|---|---|
| Total tests | 1862 | 1885 | +23 |
| Passing | 1862 | 1885 | +23 |
| Failing | 0 | 0 | 0 |
| New test files | — | 8 | — |
| New test functions | — | ~53 | — |

The "+23" net delta is because some new tests assert behaviour previously
spread across multiple test methods, so the net delta is smaller than the
raw new test count.

---

## 2026-04-07 -- Architecture Verification + Work-Cell Taxonomy (5-phase session)

**Five-phase doc session that verified the prior assessment, reconciled
contradictions, and established the work-cell architecture for parallel agent
dispatch.** No production code touched — all wiki + ADR.

### What shipped
- **Phase 1 — Verification ledger + 6 doc fixes** (commit `86929ba`). New
  `architecture/verification-ledger.md` (~450 lines) records every claim from the
  six prior architecture docs with verdict, code reference, and recommended fix.
  Then patched `tier-state-machine.md`, `writers-and-authority.md`,
  `tickcontext-provenance.md`, `data-stores.md`, `system-grouping.md`, and
  `workflows/input-routing-detailed.md` in place — minimal diffs, prior author
  voice preserved (+138 / -53 across 6 files plus the new ledger).
- **Phase 2 — Telegram input trace** (commit `31c16e7`). New
  `workflows/telegram-input-trace.md` (~570 lines). Three line-by-line traces with
  mermaid sequence diagrams: slash command (`/status`), natural-language
  (`"What's my BTC PnL?"`), inline button callback (Approve/Reject for write tools).
  Each trace verified against `cli/telegram_bot.run()`,
  `cli/telegram_agent.handle_ai_message()`, `cli/agent_tools.execute_tool()`,
  and the four callback handlers.
- **Phase 3 — Master diagrams** (commit `5910ec8`). New
  `architecture/master-diagrams.md` (~680 lines) with seven canonical mermaid
  views: process topology, three-writer authority model, TickContext fan-out per
  tier, conviction→execution chain, daemon clock harness (the 5 safety
  subsystems prior docs missed), data store ownership map, telegram routing tree.
- **Phase 4 — Work-cells** (commit `0596c13`). New
  `architecture/work-cells.md` (~915 lines) defining 9 production cells for
  parallel agent dispatch (P1-P9), complementing the 7 research cells in
  `system-grouping.md`. Each cell carries purpose, files, LOC budget, freeze
  list, test surface, safe ops, risky ops, common tasks, and dependencies.
- **Phase 5 — ADR-012** (this commit). New
  `decisions/012-work-cells-and-production-hardening.md` formalizes the
  work-cell taxonomy, the status-badge convention (ACTIVE / LATENT-REBALANCE /
  LATENT-OPPORTUNISTIC / MITIGATED), the verification-ledger pattern as the
  standard for architecture assessment, and the H1-H10 production hardening
  roadmap.

### Headline findings (recorded in the verification ledger)
- `tier-state-machine.md` self-contradicted on iterator counts **three times
  within the same file** (14, 16, 17 — actual is 17 per `cli/daemon/tiers.py`).
  This was the worst single-doc offender.
- `exchange_protection` has **NO authority check** in code (verified via reading
  `exchange_protection.py:86-180` directly). The doc was right that there was a
  bug, wrong about which doc was authoritative — `tier-state-machine.md` claimed
  the iterator was authority-aware, contradicting `writers-and-authority.md`.
- `chat_history.jsonl` is **~78 KB** (verified by `ls -lh`), not "6 MB observed
  Apr 7" as `data-stores.md` claimed.
- The `risk_gate` "dual-writer" was misframed — `risk.py` uses a structured
  worst-gate-wins merge and `execution_engine.py:114` only writes at drawdown
  ≥ 40%. Real bug exists but it's tier-ordering, not "no coordination".
- The five clock harness subsystems (`run_with_middleware`,
  `_consecutive_failures` circuit breaker, `HealthWindow` error budget,
  `TelemetryRecorder`, `TrajectoryLogger`, auto-tier-downgrade) were not
  mentioned in any of the six docs. They are documented in `master-diagrams.md`
  View 5 and ADR-012.
- Production runs in **WATCH tier**, where most "CRITICAL" bugs in the prior
  docs are LATENT (only fire on tier promotion). Status badges throughout the
  reconciled docs make this distinction explicit.

### Process retro
- The session was prompted by the user noting the previous architecture
  assessment work felt low-quality and untrustworthy. Verification confirmed the
  instinct — the six docs from commit `977bcc2` had real but mixed quality, and
  needed a sequential code-backed audit.
- The audit was performed sequentially in this conversation (no parallel agents),
  per user preference for full reasoning visibility. Every claim was checked
  against the actual source file before any wiki edit.
- The verification-ledger pattern (claim → code → verdict → minimal-diff fix)
  is now canonical for future architecture review work and is documented in
  ADR-012.
- All edits to existing docs followed the minimal-diff principle — prior author
  wording preserved where possible, only wrong sentences replaced or added to.

### Out of scope (next session — H1-H10 production hardening from ADR-012)
- H1-H4: close the four latent authority gaps in `exchange_protection`,
  `execution_engine`, `clock._execute_orders`, and `guard` (P0; required before
  any WATCH→REBALANCE tier promotion)
- H5: add rotation logic for `data/daemon/journal/ticks.jsonl` (P1; active
  growth concern at ~1.1 MB/day)
- H6-H8: add dual-write backups for thesis files, working_state.json, and
  funding.json (P1; SPOF mitigation)
- H11: decompose `common/heartbeat.py` (1631 LOC god-file) — deferred (P3) until
  forcing function

---

## 2026-04-07 -- Audit Hardening Session (H1–H5)

**Five fixes shipped over one session, all additive, zero regressions.**

### What shipped
- **F6 — `liquidation_monitor` iterator** (commit `4088602`). New per-position
  cushion-monitoring iterator wired into all 3 daemon tiers, sitting after
  `connector` and before `market_structure`. Tiered alerts: ≥20% safe,
  10–20% warning, <10% critical with 10-tick repeat throttling. Pure
  additive — `exchange_protection` ruin SLs were already in place; this is
  the early-warning layer above them. 19 new tests in
  `tests/test_liquidation_monitor.py`.
- **F9 — chat history continuity diagnostic** (commit `e4e8576`). Bot was
  already stateless across restarts — every message reloads history from
  disk via `_load_chat_history()`. Added a 20-line startup INFO log so the
  operator can confirm prior context is intact at boot. F9 re-scoped from
  "fix" to "diagnostic".
- **H4 — `account_snapshots` table dual-write** (commit `1cde050`). New
  table in `data/memory/memory.db` plus `log_account_snapshot()` helper.
  `account_collector` iterator now writes both the canonical JSON
  (unchanged) and a queryable row. Enables time-range queries that the
  flat JSON files can't answer. Best-effort write — DB failure cannot
  break the snapshot path. 12 new tests.
- **F4 verification** — read-only investigation, no code change.
  `_fetch_account_state_for_harness()` correctly iterates
  `for dex in ['', 'xyz']` and F2 (auto-watchlist) handles the SP500
  symptom that originally triggered the audit item.
- **H5 doc alignment** (commit `41f73b3`). MASTER_PLAN reframed
  (Phase 3 marked Shipped), PHASE_3_REFLECT_LOOP status updated,
  AUDIT_FIX_PLAN status table appended, root CLAUDE.md "approved markets"
  wording clarified (thesis-driven core vs auto-watchlist tracking),
  ADR-011 committed to wiki in `Proposed` status, byte-identical
  `tmp_architecture.md` duplicate deleted from project root.

### Suite
- 1753 → 1765 tests passing. Zero failures throughout the session.
- Full suite ran clean after every commit.

### Process retro — important
The session began with a brainstorming pass that wrote a 600-line ADR
based on a stale picture of the system. During execution it became
clear that:
1. **Phase 3 (REFLECT loop) was already shipped** — `autoresearch`
   iterator runs `ReflectEngine` every cycle and emits round-trip
   metrics. The MASTER_PLAN said "in progress", reality said
   `REFLECT: 1 round trips, 100% WR, $+14.94 net` in the daemon log.
2. **`AUDIT_FIX_PLAN.md` already existed** (written earlier the same
   day by the embedded agent self-audit) and **6 of 9 fixes had
   already shipped** in commits before the session started.
3. **Snapshot bleeding wasn't real** — `_expire_old_snapshots()` had
   been in place all along.
4. **F9 wasn't a real bug** — the bot is stateless by design.
5. **F6 was a different shape than the audit suggested** — ruin SLs
   on all positions were already in `exchange_protection.py`; the gap
   was the early-warning layer.

The lesson: read `docs/plans/AUDIT_FIX_PLAN.md` and the commits since
the last `alignment:` commit BEFORE claiming anything is missing or
unbuilt. Added a gotcha to the root `CLAUDE.md` workflow section so
future sessions don't repeat the mistake.

### Out of scope (deferred at user request)
- Full quant-research-app build (ADR-011 stays `Proposed`)
- Vault BTC fetch in `_fetch_account_state_for_harness` (vault is
  managed independently by the rebalancer; `/status` shows vault
  details correctly via separate path)

---

## 2026-04-05 -- v4: Embedded Agent Runtime + Wiki System

**Major architecture upgrade.** Two parallel efforts:

### Documentation Wiki
- Migrated 123 docs across 5 overlapping systems into `docs/wiki/` (27 pages)
- CLAUDE.md files slimmed to pure routing (434→163 lines)
- 22 memory files pruned, MAINTAINING.md written
- Weekly maintenance task scheduled
- ~15,000 lines of dead code removed (quoting_engine, stale strategies, legacy docs)

### Embedded Agent Runtime (Claude Code port)
- Created `cli/agent_runtime.py` — core agent architecture ported from Claude Code TypeScript
- **System prompt:** Claude Code-quality sections (doing tasks, actions, tool usage, tone)
- **Parallel tools:** READ tools execute concurrently via ThreadPoolExecutor
- **SSE streaming:** Real-time Telegram output via `editMessageText`
- **Context compaction:** Auto-summarize when approaching context window limit
- **Memory dream:** Auto-consolidate learnings after 24h + 3 sessions
- 8 new general tools: read_file, search_code, list_files, web_search, memory_read/write, edit_file, run_bash
- Agent memory system in `data/agent_memory/` (MEMORY.md index + topic files)
- Anthropic direct API with proper OpenAI→Anthropic message format conversion
- 12-iteration tool loop, 12K char results, approval gates for all writes
- Agent can read and modify its own codebase (with user approval)

### Fixes
- Anthropic tool format conversion (role="tool" → tool_result content blocks)
- Rate-limit fallback removed (Anthropic-only mode after testing)
- Default model changed to Haiku 4.5

---

## 2026-04-04 -- v3.2: Interactive UX + Hardening

**Phase 2.5 completed.** Major additions:
- Interactive button menu system (`/menu`, `mn:` callbacks, in-place message editing)
- Write commands: `/close`, `/sl`, `/tp` with Telegram approval flow
- Composable protection chain (4 protections, RiskGate state machine)
- HealthWindow: Passivbot-style 15-min sliding error budget, auto-downgrade on exhaustion
- Renderer ABC: TelegramRenderer + BufferRenderer, 5 commands migrated
- Signal engine: multi-timeframe confluence, exhaustion detection, RSI divergence, BB squeeze
- Daemon at tick 1728+ (WATCH tier, 120s, 19 iterators, 10 market snapshots)

**Status:** Command handlers, agent tools, and test suite all expanded significantly from v3.

---

## 2026-04-02 PM -- v3: Agentic Tool-Calling

**Phase 1.5 completed.** Single-day build on top of v2:
- 9 tools (7 read, 2 write with approval gates)
- Dual-mode tool calling (native + regex fallback for free models)
- Context pipeline: account state + technicals + thesis injected into every AI message
- OpenRouter integration with 18-model selector
- Centralized watchlist, candle cache with 1h freshness

**Key insight:** Rich AI context makes cheap models useful.

---

## 2026-04-02 AM -- v2: Interface-First Rewrite

**Architecture pivot.** Single morning rewrite after the oil trade loss:
- Telegram bot with rich formatting and model selector
- AI chat via OpenRouter (bypassing OpenClaw gateway)
- Per-section CLAUDE.md files for session context
- Abandoned daemon-first approach in favor of visible interface

**Key insight:** Interface-first is dramatically faster to validate than daemon-first.

---

## 2026-04-02 -- INCIDENT: Oil Trade Loss

**BRENTOIL long closed at a loss.** Every safety system failed simultaneously:

1. **Heartbeat blind 21 hours** -- `wallets.json` missing, API returning 422, zero alerting
2. **Thesis frozen 3 days** -- Last evaluation March 30, conviction stuck at 0.95 while geopolitical conditions reversed (Trump de-escalation)
3. **OpenClaw agent dead** -- auth-profiles.json had empty API keys
4. **API rate limiting** -- 9 sequential calls with no delay, 429 errors cascading to JSONDecodeError
5. **636 consecutive failures** -- No notification sent to operator

**Root cause:** Infrastructure/plumbing failures, not strategy failures. The thesis direction was correct (long oil during Hormuz crisis), but when the thesis broke down, no system warned the operator.

**Fixes applied:** Created wallets.json, lazy address resolution, 300ms API delays, 429 detection, auth profile sync, and the v2/v3 rebuild that followed.

---

## 2026-04-01 -- Conviction Engine Wired

- ExecutionEngine connected to heartbeat cycle
- Conviction bands: <0.3 defensive through 0.9+ maximum
- Staleness clamping: >7d tapers, >14d clamps to 0.3
- Six safeguards gating execution
- Kill switch: `conviction_bands.enabled = false`

---

## 2026-03-30 -- ThesisState + Conviction Bands

- ThesisState dataclass with load/save/staleness
- Per-market thesis files (`data/thesis/*_state.json`)
- Druckenmiller-model conviction bands for position sizing
- Exchange protection: SL at liquidation price * 1.02

---

## 2026-03 -- v1: Daemon-Centric Architecture

**Phase 1 + Phase 2 foundations:**
- 19 daemon iterators with ordered execution
- REFLECT meta-evaluation engine (CLI only)
- 4-phase master plan
- Heartbeat (2-min launchd), multi-wallet support
- 22 strategies built (only power_law_btc active)
- Quoting engine, journal engine, memory engine

**Limitation:** No user-facing interface. Failures were invisible. Led to the 21-hour blind heartbeat during the April 2 incident.

---

## Key Learnings (accumulated)

1. **Interface-first beats daemon-first.** A visible bot built in one morning caught more issues than weeks of invisible daemon work.
2. **Rich context unlocks cheap models.** 3500 tokens of live state makes free models surprisingly capable.
3. **Infrastructure fails silently.** 636 failures with zero notification. Alerting is not optional.
4. **Staleness kills.** A 3-day-old thesis at 0.95 conviction drove the system through a regime change.
5. **Each version layers, never replaces.** v1 daemon + v2 context + v3 tools + v3.2 UX = the full stack.
6. **Documentation is load-bearing.** Per-section CLAUDE.md files must stay current or AI sessions start confused.
