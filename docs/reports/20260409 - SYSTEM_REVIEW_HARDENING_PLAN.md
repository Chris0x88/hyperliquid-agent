# System Review & Hardening Plan

**Authored:** 2026-04-09 evening (Brisbane)
**Status:** Ready to execute — **start in a fresh session**, not this one.
**Purpose:** Bring the repo, docs, `MASTER_PLAN.md`, and the obsidian vault
back into alignment with reality after the massive 2026-04-09 shipping
burst, and then conduct a full system review of everything that's **built
but not yet battle-tested** — with a focus on **timers, loops, sequencing,
and common-sense cadence**.

> **Read the whole document before starting.** It is deliberately long
> because the work is big and the next session must not start guessing.
> Every phase has an acceptance criterion. Every phase has a known-gotcha
> list.

---

## 0. TL;DR for the next session

1. **68 commits, 452 files, +54,884 lines** landed on 2026-04-09 since
   the last `alignment:` commit (`514e0bf`). `MASTER_PLAN.md` and
   `NORTH_STAR.md` were rewritten mid-day (13:04 local) but another
   ~5 commits and a sizeable uncommitted delta followed — both are
   **partially stale**.
2. **Guardian is shut off.** All three hooks disabled in
   `agent-cli/.claude/settings.json`. Do NOT re-enable without
   user authorization. See `memory/feedback_guardian_subagent_dispatch.md`.
3. **Six sub-systems of the Oil Bot Pattern Strategy shipped** — sub-systems
   1–5 + sub-system 6 L1+L2+L3+L4 — all behind kill switches at `enabled: false`.
   **Zero of these have been battle-tested on a live trade.**
4. **The obsidian vault is real and auto-generates.** It was always meant
   to be more than a map — it's the next step in the auditing tool. This
   plan weaponises it: the vault becomes the **diff surface** against
   which drift is detected.
5. **The work has six phases**, executed roughly sequentially. Each phase
   has clear boundaries so you can ship one and checkpoint with a commit
   before starting the next.

---

## 1. The context dossier (read first, look up later)

Everything below is a snapshot of reality as of 2026-04-09 15:00 AEST. Use
it as your starting mental model. Verify anything load-bearing before
acting on it (reality-first per NORTH_STAR P2), but you should not need
to re-discover any of this.

### 1.1 Git state

- **Last alignment commit:** `514e0bf` — *"alignment: sync docs after
  oil-bot-pattern sub-systems 1+2 + lesson-layer wedges"*
- **Commits since last alignment:** 68 commits
- **Diff volume:** 452 files, +54,884 insertions, −1,143 deletions
- **Date range:** 2026-04-09 07:54 → 14:09 Brisbane time (one day,
  all in one long burst)
- **Uncommitted working tree** (run `git status --short` to re-verify):
  - `M cli/daemon/iterators/market_structure_iter.py`
  - `M cli/daemon/iterators/oil_botpattern.py`
  - `M cli/daemon/tiers.py` — adds `oil_botpattern`, `oil_botpattern_tune`,
    `oil_botpattern_reflect`, `oil_botpattern_shadow` to the **WATCH** tier
    (previously only in REBALANCE + OPPORTUNISTIC). Comment on line 19
    explains the shadow-in-WATCH rationale.
  - `M data/config/oil_botpattern.json`
  - `M guardian/hooks/session_start.py` — my disable of the sub-agent
    dispatch (keep this; see Phase 0 below)
  - `M tests/test_oil_botpattern_adaptive_integration.py`
  - `M tests/test_oil_botpattern_adaptive_live.py`
  - `M tests/test_oil_botpattern_iterator.py`
  - `M tests/test_oil_botpattern_shadow_mode.py`
  - `?? tests/test_market_structure_1m_cache.py` (new)
  - `?? tests/test_oil_botpattern_risk_gate.py` (new)
  - `?? data/strategy/oil_botpattern_state.json` (runtime state — do NOT commit)
  - `?? data/supply/state.json` (runtime state — do NOT commit)

**Full commit list since `514e0bf`:** see §Appendix A for the exact 68-line
dump with timestamps. Capturing the list in the plan means the next session
does not need to re-grep it.

### 1.2 What shipped (high-level, grouped by feature area)

All of the following were authored and committed on **2026-04-09** and
**none have a full alignment pass yet**. Every item includes its **ship
status** (committed, in flight, uncommitted, parked) and its **battle-test
status** (untested, shadow-only, verified on synthetic data, production
verified):

**Guardian meta-system — SHIPPED then IMMEDIATELY DISABLED same day**
- Phases 1–6: cartographer (Phase 1), drift detector (Phase 2), review
  gate (Phase 3), friction surfacer (Phase 4), sweep orchestrator + lazy
  SessionStart (Phase 5), ADR-014 + knowns.py (Phase 6)
- **Status:** all code committed, all tests green, hooks **DISABLED**
  per user request 2026-04-09 PM (looping / stale narrative). Do NOT
  re-enable.
- **Why it's flagged in this plan:** the code is still in the repo. It
  has tests. It has sweep logic. **If you want code-health signals,
  you can run `guardian/sweep.py` manually as a one-shot** without
  re-enabling the hooks. That's the cleanest way to get its drift
  findings into this review without bringing the loop back.

**Trade Lesson Layer — wedges 5 + 6 complete**
- `cli/daemon/iterators/lesson_author.py` — closed-position → lesson
  candidate writer (no AI)
- `agent-cli/cli/telegram_commands/lessons.py` — extracted from
  monolith as wedge 1 of the telegram split
- `search_lessons` + `get_lesson` agent tools
- `/lessonauthorai` — ai-suffixed slash command
- `common/memory.py` FTS5 `lessons` table + top-5 injection into
  every agent decision
- **Battle-test status:** Verified end-to-end on ONE synthetic row
  (lesson #47 marked rejected). **No real closed trade has flowed
  through the lesson layer yet.** First real trade is a one-button
  follow-up by Chris (the $50 BTC vault smoke test).

**Oil Bot Pattern Strategy System — sub-systems 1 through 5 + sub-system 6 L1/L2/L3/L4**
- **#1 news_ingest** — RSS/iCal feeds → catalysts. Kill switch:
  `data/config/news_ingest.json`. Reads OK in WATCH. **Ship status:**
  shipped. **Battle-test status:** live catalysts flowing unknown —
  verify by reading `data/news/catalysts.jsonl` age.
- **#2 supply_ledger** — catalysts + `/disrupt` → active disruption
  aggregate at `data/supply/state.json`. Kill switch:
  `data/config/supply_ledger.json`. **Ship status:** shipped.
  **Battle-test status:** state.json is in the uncommitted tree,
  so the iterator has been *writing*; verify contents match reality.
- **#3 heatmap** — HL `l2Book` + `metaAndAssetCtxs` → liquidity
  zones + cascade detection. Writes `data/heatmap/zones.jsonl` +
  `data/heatmap/cascades.jsonl`. Kill switch: `data/config/heatmap.json`.
  **Ship status:** shipped; `snapshot_at` field fix landed 14:08 in
  commit `9153805`. **Battle-test status:** `/readiness` now reads
  `snapshot_at` correctly — sanity-check it's producing live zones.
- **#4 bot_classifier** — heuristic classifier fusing #1 + #2 + #3
  + candle cache. Writes `data/research/bot_patterns.jsonl`. Kill
  switch: `data/config/bot_classifier.json`. **Ship status:** shipped;
  candle fetch fix landed 14:09 in commit `998b6bb` (previously was
  reading an empty cache). **Battle-test status:** producing records,
  not yet driving any decisions.
- **#5 oil_botpattern** — THE ONLY PLACE oil shorting is legal. Dual
  kill switches (`enabled` + `short_legs_enabled`). Conviction sizing.
  Drawdown circuit breakers (3%/8%/15%). 24h hard cap on shorts.
  Funding-cost exit for longs. Kill switch: `data/config/oil_botpattern.json`.
  **Ship status:** shipped, **both kill switches OFF**, running in
  `decisions_only=true` shadow mode.
- **#5 adaptive evaluator** — live thesis-testing evaluator with training
  log. Exit-only v1 wired into the shadow-mode iterator. Writes
  `data/strategy/adapt_log.jsonl`. New commands: `/adaptlog` to query
  the decision log. **Ship status:** shipped 13:41–13:42 today.
  **Battle-test status:** shadow-only by design.
- **#6 L1 oil_botpattern_tune** — bounded auto-tune. Nudges 5 params
  in `oil_botpattern.json` within YAML bounds (max ±5% per nudge, 24h
  rate limit, min sample 5). Kill switch: `data/config/oil_botpattern_tune.json`
  → `enabled: false`. Audit trail at `data/strategy/oil_botpattern_tune_audit.jsonl`.
  **Ship status:** shipped. **Battle-test status:** **inert** — kill
  switch off, no closed trades to nudge from.
- **#6 L2 oil_botpattern_reflect** — weekly reflect proposals. Runs
  once per 7 days. Writes `StructuralProposal` records to
  `data/strategy/oil_botpattern_proposals.jsonl`. Never auto-applies;
  every proposal requires `/selftuneapprove <id>`. Kill switch:
  `data/config/oil_botpattern_reflect.json`. **Ship status:** shipped
  with kill switch off. **Battle-test status:** inert.
- **#6 L3 oil_botpattern_patternlib** — pattern library growth. Detects
  novel `(classification, direction, confidence_band, signals)`
  signatures in `data/research/bot_patterns.jsonl`, tallies in 30-day
  rolling window, emits `PatternCandidate` once signature crosses
  `min_occurrences` (default 3). Candidates land in
  `data/research/bot_pattern_candidates.jsonl`. Review via
  `/patterncatalog`, promote via `/patternpromote <id>`. Kill switch:
  `data/config/oil_botpattern_patternlib.json`. **Ship status:**
  shipped all-tiers including WATCH (read-only). **Battle-test
  status:** inert.
- **#6 L4 oil_botpattern_shadow** — counterfactual shadow evaluation.
  For each approved L2 proposal, re-runs the affected gate against
  the last 30 days of decisions and computes `ShadowEval`. **Look-back
  counterfactual**, NOT forward paper executor. Writes to
  `data/strategy/oil_botpattern_shadow_evals.jsonl`. Kill switch:
  `data/config/oil_botpattern_shadow.json`. Review via `/shadoweval [id]`.
  **Ship status:** shipped. **Battle-test status:** inert.
- **#6 L5 ML overlay** — deferred, not built. Resume condition: ≥100
  closed trades exist.

**Trade Entry Critic (new iterator, not Oil Bot Pattern)**
- `cli/daemon/iterators/entry_critic.py` — deterministic grading on
  every new entry. New command: `/critique`.
- **Ship status:** shipped, verified end-to-end same day.
- **Battle-test status:** shipped to production path but first real
  trade not yet observed.

**Operator / ops infrastructure**
- `cli/daemon/iterators/action_queue.py` — daily sweep of operator-ritual
  queue (memory restore drill quarterly, /brutalreviewai weekly, thesis
  refresh checks, etc.). `/nudge` command. **Ship status:** shipped.
  **Battle-test status:** untested in production — no queue item has
  actually fired a Telegram nudge yet.
- `cli/daemon/iterators/liquidation_monitor.py` — tiered cushion alerts
  on every open position (audit F6). **Ship status:** shipped. **Battle-test
  status:** no real liquidation event to test against; deterministic
  unit tests only.
- `cli/daemon/iterators/brent_rollover_monitor.py` — T-7/T-3/T-1 alerts
  before each Brent contract roll (C7). **Ship status:** shipped.
  **Battle-test status:** first real rollover alert not yet observed.
- `cli/daemon/iterators/memory_backup.py` — hourly atomic snapshots of
  `memory.db`. Kill switch: `data/config/memory_backup.json` →
  `interval_hours: 1`. **Ship status:** shipped + registered. Backups
  under `data/memory/backups/` (24h/7d/4w retention). **Battle-test
  status:** backup loop is running; **restore drill runbook shipped
  same day but has NOT been executed.** The runbook is at
  `docs/wiki/operations/memory-restore-drill.md`.
- `cli/daemon/iterators/protection_audit.py` — read-only verifier that
  every position has a sane exchange stop (C1'). **Ship status:** shipped.
- `cli/daemon/iterators/funding_tracker.py` — cumulative funding cost
  tracker (C2). **Ship status:** shipped.

**Realignment burst infrastructure (2026-04-09 evening)**
- `/brutalreviewai` command + `BRUTAL_REVIEW_PROMPT.md` literal prompt
  (wedge 1). **Ship status:** shipped. **Battle-test status:** never run
  — running it is one of the first tasks in this plan.
- `common/markets.py` `MarketRegistry` + `data/config/markets.yaml`
  (Multi-Market Wedge 1). The hardcoded long-only-oil rule moved from
  a static function check to a per-instrument config row. **Behavior
  identical at ship time.**
- Chat history market-state correlation + ctx.prices in snapshot.
- Historical oracle tier of append-only event logs (per P9/P10).
- `/chathistory` search command with `.bak` union.
- P10 data-discipline hardening: system prompt cap, signals/lesson
  clamps, memory_read cap, chat history tail-read.
- `/sim` + `/readiness` + `/activate` — sub-system 5 activation walkthrough.
- Sub-system 5 activation runbook.
- `/shadoweval` Telegram command (L4 surface).

**Obsidian vault — 2026-04-09**
- `agent-cli/docs/vault/` — 200+ files, committed in `9153805`
  (accidentally, via the parallel ralph-loop session's broad `git add`).
- Auto-generator at `scripts/build_vault.py` (856 lines). Idempotent,
  timestamped, human/robot region separation. Reads from `cli/daemon/tiers.py`,
  `cli/daemon/iterators/`, `cli/telegram_bot.py`,
  `cli/telegram_commands/`, `cli/agent_tools.py`, `data/config/`,
  `docs/plans/`, `docs/wiki/decisions/`.
- **Last regenerated:** 2026-04-09 14:08 — **stale relative to the
  uncommitted `tiers.py` change** (oil_botpattern family added to WATCH
  at ~15:05, not yet regenerated).
- **Not pushed** — local-only. `.obsidian/` gitignored.
- **Philosophy:** structural facts are auto-gen so they can't drift;
  narrative / ADR content is hand-written; the vault LINKS to
  `docs/wiki/` rather than duplicating it.
- **This plan's key observation:** the vault is already the best
  drift-detection surface in the repo. Run the generator, diff the
  output, and every structural change surfaces as a git diff. That IS
  the auditing tool. Phase E operationalises it.

**Experiments + parked plans**
- **Knowledge Graph Thinking Regime** — plan + Wedge 1 YAML authored
  AND parked SAME DAY. Artifacts preserved at
  `docs/plans/thinking_graphs/_concepts.yaml` +
  `docs/plans/thinking_graphs/oil_short_decision.yaml`. Not wired to
  any code path. Resume condition: "a specific reasoning failure
  observed in production that a markdown checklist in AGENT.md fails
  to fix."
- **Oil Short Decision Checklist in `agent/AGENT.md`** — the CHEAPER
  alternative to the parked Knowledge Graph. Shipped as an experiment
  13:45 today. The plan is to **observe it in production for several
  sessions** before deciding the Knowledge Graph's fate permanently.

### 1.3 Daemon tick model (critical for Phase C)

This is the mental model you need before auditing any timer or loop.
Read it twice.

**The daemon is a tick-based loop, Hummingbot-style.** Lives in
`cli/daemon/clock.py`. One global tick interval per process
(`DaemonConfig.tick_interval`, default `120` seconds via
`hl daemon start --tick 120`). Every tick:

1. Check the control file for runtime commands.
2. Rebuild the **active iterator set** from `cli/daemon/tiers.py` based
   on the current tier (`watch` / `rebalance` / `opportunistic`).
3. Call each iterator's `.tick(ctx)` method in list order through a
   middleware wrapper that enforces a per-iterator `iterator_timeout_s`
   (default 10s).
4. Drain the `OrderIntent` queue into the adapter, applying risk gate
   + per-asset authority checks.
5. Persist state, emit telemetry + trajectory rows, run health-window
   error budget, possibly auto-downgrade tier.
6. `time.sleep(tick_interval)`, repeat.

**Iterators that need a slower cadence than the global tick** throttle
themselves internally by reading `tick_interval_s` from their config
JSON and tracking `_last_tick` — they return early if
`now - self._last_tick < tick_interval_s`. This is the pattern you
must audit in Phase C.

**Observed internal cadences (from `grep INTERVAL` on 2026-04-09):**

| Iterator                     | Source of cadence                                | Current value |
|------------------------------|--------------------------------------------------|---------------|
| `memory_consolidation`       | `_CONSOLIDATION_INTERVAL` constant               | `3600` (1h)   |
| `market_structure_iter`      | docstring says "every 5 minutes"                 | 300? (verify) |
| `protection_audit`           | throttle matches heartbeat cadence               | tied to tick  |
| `exchange_protection`        | `TICK_INTERVAL_S` constant                       | verify        |
| `pulse`                      | `DEFAULT_SCAN_INTERVAL`                          | `120` (2m)    |
| `apex_advisor`               | 60s throttle                                     | `60`          |
| `action_queue`               | `interval_hours` config (default `24`)           | `24h`         |
| `rebalancer`                 | per-slot `tick_interval` on each slot            | per-strategy  |
| `oil_botpattern_patternlib`  | `tick_interval_s` config                         | `600` (10m)   |
| `oil_botpattern_tune`        | `tick_interval_s` config                         | `300` (5m)    |
| `radar`                      | `DEFAULT_SCAN_INTERVAL`                          | `300` (5m)    |
| `oil_botpattern`             | `tick_interval_s` config                         | `60`          |
| `oil_botpattern_shadow`      | `tick_interval_s` config                         | `3600` (1h)   |
| `memory_backup`              | `interval_hours` config                          | `1h`          |
| `memory_consolidation` (again)| hard constant                                   | `3600` (1h)   |

**Iterators with no explicit throttle** run every tick (implicit cadence
= daemon global tick). You must identify which these are during Phase C
and decide whether that's actually what you want — for example,
`account_collector` and `connector` SHOULD run every tick; `journal`
SHOULD NOT re-scan every tick if the source file hasn't changed.

### 1.4 Kill switches and config files

All sub-system kill switches + scheduling config live in
`data/config/`. As of 2026-04-09 15:00 local:

| Config                              | `enabled` | Scheduling |
|-------------------------------------|-----------|------------|
| `bot_classifier.json`               | true      | default tick |
| `entry_critic.json`                 | true      | default tick |
| `heatmap.json`                      | true      | default tick |
| `lesson_author.json`                | true      | default tick |
| `memory_backup.json`                | true      | `interval_hours: 1` |
| `news_ingest.json`                  | true      | default tick |
| `oil_botpattern.json`               | **true**  | `tick_interval_s: 60` |
| `oil_botpattern_patternlib.json`    | **false** | `tick_interval_s: 600` |
| `oil_botpattern_reflect.json`       | **false** | weekly (7d) |
| `oil_botpattern_shadow.json`        | **false** | `tick_interval_s: 3600` |
| `oil_botpattern_tune.json`          | **false** | `tick_interval_s: 300` |
| `supply_ledger.json`                | true      | default tick |

**Critical:** `oil_botpattern.json` has `enabled: true` but the daemon
is in WATCH tier so the iterator runs in `decisions_only=true` shadow
mode — it emits zero `OrderIntent`s by design. The **dual** kill
switch means the iterator logic runs (so you can observe its decisions)
but nothing reaches the exchange. When Chris wants to promote, the
gate is `short_legs_enabled: true` AND tier promotion to REBALANCE.

### 1.5 Test suite state

- **Total tests:** 3,090 (confirmed via `pytest --collect-only` at
  writing time). MASTER_PLAN says "2,747+" which was correct at 13:04
  today — ~343 tests landed in the ~3-hour window since.
- **Recent test additions** covering the new iterators (all should be
  green — verify with `cd agent-cli && .venv/bin/python -m pytest
  tests/ -q --no-header`):
  - `test_action_queue_iterator.py` / `test_action_queue_module.py`
  - `test_bot_classifier.py` / `test_bot_classifier_iterator.py`
  - `test_entry_critic_iterator.py` / `test_entry_critic_module.py`
  - `test_heatmap.py` / `test_heatmap_iterator.py`
  - `test_lesson_author_consumer.py` / `test_lesson_author_iterator.py`
  - `test_liquidation_monitor.py`
  - `test_memory_backup_iterator.py`
  - `test_news_ingest_iterator.py`
  - `test_oil_botpattern*` (15+ files)
  - `test_readiness_thesis_epoch_ms.py` (new, from commit `9153805`)
  - `test_market_structure_1m_cache.py` (uncommitted)
  - `test_oil_botpattern_risk_gate.py` (uncommitted)

**Coverage gap:** the daemon CLOCK ITSELF (`clock.py`) and `tiers.py`
map consistency have minimal direct tests. Phase C will add these.

### 1.6 Memory + documentation state

- **CLAUDE.md (project root)** — Current. References the Guardian
  sub-system as "auto-runs on SessionStart and before Edit/Write/Bash"
  — **this is now stale** since Guardian was disabled. Fix in Phase A.
- **`docs/wiki/MAINTAINING.md`** — Current and load-bearing. Describes
  the 5 doc types, the golden "no hard-coded counts" rule, the
  archive + rewrite versioning convention, when to update each type.
  Read this before touching any doc.
- **`docs/plans/MASTER_PLAN.md`** — Updated 13:04 today. Partially stale
  (missing the ~5 commits since) but structurally sound.
- **`docs/plans/NORTH_STAR.md`** — Updated 13:04 today in the same
  realignment commit. Load-bearing for any strategy/scope decisions.
- **`docs/plans/AUDIT_FIX_PLAN.md`** — Historical record from 2026-04-07.
  Most items shipped. Keep as-is per the archive convention (do not
  rewrite historical plan records).
- **`docs/wiki/build-log.md`** — Append-only, most recent entry is the
  sub-system 6 L3+L4 ship at "late evening+". Needs a new entry
  capturing the late-afternoon readiness fix + bot classifier candle
  fetch + this review plan itself.
- **`~/.claude/projects/-Users-cdi-Developer-HyperLiquid-Bot/memory/`** —
  Memory index is current. New entry added today for the Guardian
  shutdown.

### 1.7 Known drift (discovered while writing this plan)

These are NOT comprehensive — they're what I spotted in one pass:

1. **`CLAUDE.md` (project root) line 19** — says Guardian Angel
   auto-runs on SessionStart and PreToolUse. False as of today
   (hooks disabled). **Fix in Phase A.**
2. **`agent-cli/guardian/sweep.py:167`** — writes
   `"_Phase 5 will replace this with a sub-agent synthesis._"` into
   every generated report. Phase 5 + Phase 6 have both shipped, and
   the whole system is disabled anyway. **Fix in Phase A or delete
   the line entirely.**
3. **Vault's `docs/vault/iterators/oil_botpattern.md`** —
   `tiers: [rebalance, opportunistic]` (missing `watch`) because the
   vault was regenerated at 14:08, before the uncommitted `tiers.py`
   change at ~15:05 added the WATCH entry. Rerun
   `scripts/build_vault.py` after committing `tiers.py` to fix.
4. **MASTER_PLAN's "2,747+ tests" line** — 3,090 as of writing.
   Per MAINTAINING.md "no hard-coded counts", this phrase should be
   "see `pytest --collect-only | tail -5`". **Fix in Phase A.**
5. **MASTER_PLAN's "Open Questions / Known Gaps" section** may have
   items that already shipped post-13:04. Audit during Phase A.
6. **`docs/plans/NORTH_STAR.md` §9 "Direction-setting decisions
   already made"** references Multi-Market Wedge 1 as shipped (true)
   but does not mention the bot classifier candle fetch fix, the
   adaptive evaluator exit-only v1, or the `/adaptlog` / `/activate`
   / `/sim` / `/readiness` / `/shadoweval` command ships. These are
   all per-session detail and may not belong in NORTH_STAR — just
   make sure MASTER_PLAN's "Active Workstreams" captures them.

### 1.8 What's uncommitted and what that means

The working tree has modifications that appear to be mid-work on an
adaptive-evaluator risk gate + 1m candle cache. **You should NOT
commit this code as part of the alignment pass** — it belongs to a
separate workstream that the user may still be in the middle of.
Touch only the alignment artifacts (docs, plan, vault regeneration).
If the uncommitted code blocks your ability to run the suite, ask the
user before stashing or committing.

Exception: my two edits from this session —
`agent-cli/guardian/hooks/session_start.py` and the new memory file —
are safe to commit as `chore(guardian): disable sub-agent dispatch
loop + shut off hooks` (see Phase 0).

---

## 2. The six phases

Sequence matters. Do NOT reorder unless you understand why.

```
Phase 0  Pre-flight          — commit the Guardian shutdown from the prior session
Phase A  Alignment backfill  — bring docs/plans/vault to match reality
Phase B  Battle-test ledger  — enumerate exactly what's unproven and why
Phase C  Timer/loop audit    — cadences, sequencing, common-sense review
Phase D  Cohesion review     — hardening and update priorities, prioritized
Phase E  Vault-as-auditor    — operationalise the vault as a drift surface
Phase F  Ship report         — produce the brutal review output for the user
```

---

## 3. Phase 0 — Pre-flight (15 min)

**Goal:** start the session clean and commit the Guardian shutdown from
the prior session.

**Tasks:**

1. Run `cd agent-cli && git status --short` and confirm the modified
   files are the ones listed in §1.1. If the list is different, the
   user has been working in another session — stop and ask before
   doing anything.
2. Commit ONLY the Guardian-disable changes as their own commit:
   ```bash
   cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
   git add .claude/settings.json guardian/hooks/session_start.py
   git commit -m "chore(guardian): disable hooks + sub-agent dispatch loop
   
   All three Guardian hooks (SessionStart, PreToolUse, PostToolUse)
   disabled by emptying .claude/settings.json. Code preserved for
   potential future re-enable. session_start.py sub-agent dispatch
   default flipped to off even if hooks are re-wired — the injected
   prompt caused Claude to re-dispatch every session and re-emit
   stale narrative.
   
   Context: 2026-04-09 PM user request. See
   memory/feedback_guardian_subagent_dispatch.md."
   ```
3. Do NOT touch any of the other uncommitted files in Phase 0. Leave
   the adaptive-evaluator work intact.
4. Verify test suite still green with the Guardian disabled:
   ```bash
   .venv/bin/python -m pytest tests/ guardian/tests/ -q --no-header 2>&1 | tail -5
   ```
   Expect 3,090+ tests, 0 failed. Guardian's own tests should still
   pass because they don't require the hooks to be wired.
5. Update the todo list for Phase A.

**Acceptance criterion:** one commit on `main`, green suite, clean
working tree except for the pre-existing adaptive-evaluator WIP.

**Gotchas:**
- **Do NOT** `git add -A` or `git add .`. Always by name.
- **Do NOT** attempt to amend commit `9153805` — the vault mis-attribution
  is a historical curiosity and was explicitly not-fixed per CLAUDE.md's
  "no destructive overreach" rule.

---

## 4. Phase A — Alignment backfill (60–90 min)

**Goal:** make `MASTER_PLAN.md`, `NORTH_STAR.md`, the relevant
`CLAUDE.md` files, the build log, and the obsidian vault all match
reality at HEAD as of Phase 0's commit.

This is running the `/alignment` evening-mode ritual manually. The
`/alignment` slash command at `.claude/commands/alignment.md` is the
canonical source of truth for the procedure — read it before starting.
This section encodes the same steps but for the specific drift already
identified in §1.7, plus the drift you'll find by doing the ritual.

### 4.1 Reality discovery (do NOT read docs first)

Run the alignment ritual's discovery phase verbatim:

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli

# What's actually running?
launchctl list | grep -i hyper
ps aux | grep -E "telegram_bot|cli.main daemon" | grep -v grep
tail -5 data/daemon/daemon_launchd_err.log

# What was built since last alignment?
LAST_ALIGN=$(git log --oneline --all --grep="alignment:" -1 --format="%H")
git log --oneline "$LAST_ALIGN..HEAD"
git log --shortstat "$LAST_ALIGN..HEAD" --format=format: | awk '/files? changed/ {f+=$1; i+=$4; d+=$6} END {printf "%d files, +%d, -%d\n", f, i, d}'

# Test state
.venv/bin/python -m pytest tests/ -q --collect-only 2>&1 | tail -1

# Thesis freshness
ls -lt data/thesis/

# Active model
cat data/config/model_config.json

# Daemon tier
cat data/daemon/state.json 2>/dev/null | python3 -m json.tool | grep tier
```

Capture the output to a scratch file for the build-log entry.

### 4.2 CLAUDE.md (project root) — fix Guardian reference

Edit `/Users/cdi/Developer/HyperLiquid_Bot/CLAUDE.md`, line ~19, to
replace the "Guardian Angel auto-runs" bullet with something like:

> 5. **Guardian is disabled.** The guardian meta-system under
>    `agent-cli/guardian/` is preserved in code but its hooks are
>    emptied in `agent-cli/.claude/settings.json`. Do not re-enable
>    without explicit user authorization. See
>    `memory/feedback_guardian_subagent_dispatch.md` for why.

Do NOT delete any surrounding rules. Do NOT touch the trading-safety
or OpenClaw-boundary sections.

### 4.3 `agent-cli/guardian/sweep.py:167` — remove stale "Phase 5" marker

Delete the line:
```python
"_Phase 5 will replace this with a sub-agent synthesis._",
```
from the `lines.extend([...])` call around line 165. Phases 5 and 6
have shipped AND the whole system is disabled — the marker is
double-wrong. One-line delete, inert system.

### 4.4 `docs/plans/MASTER_PLAN.md` — surgical updates, not a rewrite

MAINTAINING.md says: *"When MASTER_PLAN.md drifts meaningfully from
reality ... archive the current version + rewrite fresh."* The current
MASTER_PLAN was rewritten 3 hours ago and most of its structure is
still correct. **Do NOT archive + rewrite.** Apply surgical fixes only:

1. Replace `2,747+ tests` with `see "pytest --collect-only" output`
   (per the no-hard-counts rule).
2. Update the "Current Reality" table's `Tradeable thesis markets`
   row to reflect GOLD + SILVER conviction clamps (they appear in
   "Open Questions" already — make sure the two sections don't
   contradict).
3. Add a new bullet under "Active Workstreams" → "1. 2026-04-09
   Realignment Burst" for the post-13:04 ships:
   - Sub-system 5 activation runbook shipped
   - Adaptive evaluator exit-only v1 wired into shadow iterator
   - `/adaptlog`, `/activate`, `/sim`, `/readiness`, `/shadoweval`
     commands shipped
   - Readiness thesis epoch-ms fallback fix
   - Heatmap `snapshot_at` field fix
   - Bot classifier candle fetch fix
   - Oil Short Decision Checklist experiment added to AGENT.md
     (Knowledge Graph alternative — observe before deciding)
   - Guardian hooks disabled (this plan's Phase 0)
4. Under "Open Questions / Known Gaps", strike anything that actually
   shipped post-13:04 (for example, the Wedge 1 lessons extraction bullet).

### 4.5 `docs/plans/NORTH_STAR.md` — light updates

NORTH_STAR captures vision, not per-ship detail. Confirm it's current
by reading the "Operating Principles" section end-to-end. Add P10
references if they're missing somewhere. Do NOT add per-commit detail;
that's MASTER_PLAN's job.

### 4.6 Per-package `CLAUDE.md` files — audit

For each of the files below, open it, read it against the current
code, and fix any stale references. Per MAINTAINING.md, CLAUDE.md
files are **routing only** — file tables + wiki links + gotchas.
No narrative, no counts.

Files to audit:
- `agent-cli/common/CLAUDE.md`
- `agent-cli/cli/CLAUDE.md` (referenced by `/alignment`)
- `agent-cli/cli/daemon/CLAUDE.md` (has iterator description block —
  verify it mentions the newest ships including L3/L4 pattern library
  + shadow eval)
- `agent-cli/modules/CLAUDE.md`
- `agent-cli/parent/CLAUDE.md`
- `agent-cli/agent/AGENT.md` (read-only? confirm with user before
  editing — per the AUDIT_FIX_PLAN constraint, `agent/AGENT.md` is
  frozen without per-change sign-off)

Expected fixes: 2–5 file-table rows across all of these. NOT a rewrite.

### 4.7 `docs/wiki/build-log.md` — append new entry

Per MAINTAINING.md: append new entry at the TOP with today's date and
the following content:

- What landed post-13:04 (the ~5 commits detailed in §1.2)
- The Guardian disable (this plan's Phase 0)
- The review plan itself (THIS document) as a deliberate "pause and
  take stock" milestone
- The uncommitted adaptive-evaluator WIP (acknowledge it exists, do
  not describe as shipped)

Do NOT rewrite earlier entries. Append-only.

### 4.8 Obsidian vault regeneration

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
.venv/bin/python scripts/build_vault.py 2>&1 | tail -20
```

Expected output: a summary of files regenerated. Then check what
changed:

```bash
git diff --stat docs/vault/ 2>&1 | tail -20
```

Review the diff. Expected changes:
- `docs/vault/iterators/oil_botpattern.md` — `tiers:` frontmatter gets
  `watch` added IF the uncommitted `tiers.py` change has been committed
  by then. If it hasn't (and per §1.8 it shouldn't be), the regeneration
  will match the committed state and the vault will be correct-for-HEAD.
- Similar adds for `oil_botpattern_tune`, `oil_botpattern_reflect`,
  `oil_botpattern_shadow` (same rationale).
- New entries for any commands or tools added since the last regen.

**Important:** the vault regeneration is idempotent — if no code
changed in the auto-gen sources, the diff is empty. Empty diff is
also a success state.

### 4.9 Commit the alignment burst

```bash
# Add only the doc files you changed, by name:
git add CLAUDE.md
git add agent-cli/docs/plans/MASTER_PLAN.md
git add agent-cli/docs/plans/NORTH_STAR.md    # if touched
git add agent-cli/docs/wiki/build-log.md
git add agent-cli/guardian/sweep.py            # line 167 delete
git add agent-cli/cli/CLAUDE.md agent-cli/cli/daemon/CLAUDE.md  # as applicable
git add agent-cli/docs/vault/                  # regenerated vault

git commit -m "alignment: sync docs + vault to 2026-04-09 PM reality

68 commits landed since 514e0bf covering Guardian Phases 1-6 (now
disabled), Oil Bot Pattern sub-systems 1-5 + 6-L1/L2/L3/L4, Trade
Lesson Layer wedges 5-6, Entry Critic, Action Queue, Memory Backup,
Liquidation Monitor, Brent Rollover Monitor, Brutal Review Loop wedge 1,
Multi-Market wedge 1, Telegram monolith wedges 1-2, Historical Oracle
P10 hardening, Sub-system 5 activation + adaptive evaluator, readiness
+ heatmap + bot classifier fixes, Obsidian vault.

Full context: docs/plans/SYSTEM_REVIEW_HARDENING_PLAN.md"
```

**Acceptance criterion:**
- One commit on `main` with message starting `alignment:`
- The next `/alignment` run reports "No drift — docs match reality"
- `scripts/build_vault.py` produces an empty diff on rerun
- Test suite green

---

## 5. Phase B — Battle-test ledger (60–90 min)

**Goal:** produce a single table that captures, for every iterator +
command + sub-system shipped since `514e0bf`, its **current
battle-test status** — is it running in production, is it inert
behind a kill switch, is it tested only on synthetic data, or has it
been verified end-to-end on real state?

This is a **data-gathering phase**, not a fix-it phase. The output is
a document the user can read in 5 minutes to know what's real and
what isn't.

### 5.1 The three battle-test tiers

Classify every feature into one of three buckets:

| Tier | Definition | Examples |
|------|------------|----------|
| **P**roduction-verified | Actually ran against real market data or real position state, with observable output that matches reality | `protection_audit` reading live positions, `memory_backup` files on disk, `account_collector`, the oil long heartbeat |
| **S**ynthetic-verified  | Unit/integration tests green, reads/writes in dev mode, no real production observation yet | `lesson_author` (one synthetic lesson), `entry_critic` (tests only), `brent_rollover_monitor` (no rollover event yet), `liquidation_monitor` (no liquidation event), `action_queue` (no nudge fired yet) |
| **I**nert                | Kill switch off, iterator not running at all, or read-only shadow mode producing zero side effects | All `oil_botpattern_*` (shadow), `adaptive evaluator`, L1–L4 of sub-system 6, sub-system 5 itself (shadow) |

### 5.2 Methodology for each feature

For each iterator / command / sub-system in the ship list from §1.2:

1. Find its source file(s).
2. Find its test file(s). Run `pytest <test_file> -q` if in doubt.
3. Find its kill switch config file.
4. Check the kill switch state (`enabled: true/false`).
5. Find the output file(s) it writes (jsonl, json, sqlite, etc.).
6. `ls -lt` the output file and check for recent activity.
7. If recent: read the last ~5 rows and sanity-check they look real.
8. Classify into P / S / I.
9. Add a one-line note explaining WHY you chose that tier.

Example row:
```
heatmap            | P | zones.jsonl updated in last 10m, 200+ zones,
                        ranges make sense vs current BRENTOIL price
```

```
oil_botpattern_tune| I | kill switch oil_botpattern_tune.json enabled=false;
                        audit log is empty; iterator registered but
                        never nudges because no real closed trades exist
```

### 5.3 Output: `docs/plans/BATTLE_TEST_LEDGER.md`

Write the output to a new plan doc. Structure:

```markdown
# Battle-Test Ledger — 2026-04-YY

**What this is:** a point-in-time snapshot of which system components
are production-verified vs synthetic-verified vs inert.

**How it's used:** read before promoting any sub-system from kill-switch-
off to kill-switch-on. Read before committing to a real-money test.
Never trust a "shipped" label without cross-checking against this ledger.

## Iterators

| Name | Tier | Last real activity | Notes |
|------|------|--------------------|-------|
| account_collector | P | every tick | produces AccountState ctx |
| connector | P | every tick | HL API session alive |
| ... (complete inventory per §1.3 and cli/daemon/iterators/) |

## Telegram commands

| Command | Tier | Last fired | Notes |
|---------|------|------------|-------|
| /status | P | recent | deterministic, hit daily |
| /critique | S | never | entry critic deterministic grading; tests only |
| ... |

## Agent tools

| Tool | Tier | Notes |
|------|------|-------|
| search_lessons | S | one synthetic lesson in corpus, no real closed trades |
| ... |

## Sub-systems

| Sub-system | Tier | Gate to promote |
|------------|------|-----------------|
| Oil Bot Pattern #1 news_ingest | P | live RSS, catalysts.jsonl active |
| Oil Bot Pattern #5 oil_botpattern | I | dual kill switches off |
| ... |

## Promotion-ready list

Items in S tier that are one observation away from P tier:
- lesson_author (first real closed trade)
- entry_critic (first real entry — expected with lesson_author)
- action_queue (first scheduled nudge — expected within 24h tick)

## Promotion-blocked list

Items in I tier with concrete blockers:
- oil_botpattern L1 tune: waiting on ≥5 closed bot-pattern trades
- oil_botpattern L2 reflect: waiting on 7-day window + closed trades
- oil_botpattern L3 patternlib: waiting on 3+ novel signatures in
  bot_patterns.jsonl
- oil_botpattern L4 shadow: waiting on at least one approved L2 proposal
```

**Acceptance criterion:** ledger committed, every post-`514e0bf` ship
classified into P / S / I, every I item has a concrete blocker note.

**Gotchas:**
- Do NOT promote any kill switches during this phase. Classification
  only.
- Do NOT write "unknown" in the tier column. If you can't figure it
  out, call it I with a note explaining what you need to know.
- Kill switches flipping on during the review is a user decision, not
  yours.

---

## 6. Phase C — Timer/loop audit (2–4 hours, heaviest phase)

**Goal:** answer the user's explicit ask: *"I also need to track and
check timer and loops for when processes run, how they run, sequencing,
is it common sense."*

This is a detailed cadence + sequencing audit. Output is a document
that captures every loop in the system with its cadence, what it
depends on, what depends on it, whether its rate makes sense, and
whether there's a common-sense sequencing issue (iterator A fires
after iterator B when it should fire before, two iterators read
stale data from each other, etc.).

### 6.1 Inventory every iterator

For each file in `cli/daemon/iterators/*.py`:

1. Extract the class name and iterator name.
2. Read the file end-to-end.
3. Extract:
   - **Global tick gate:** does it throttle with `tick_interval_s` or
     run every tick?
   - **Internal schedule:** any `_last_tick`, `_last_run`, `schedule`,
     timedelta math, cron-like trigger?
   - **Reads:** which data files, configs, ctx fields?
   - **Writes:** which data files, configs, Telegram alerts?
   - **Depends on:** which other iterators' outputs?
   - **Depended on by:** which downstream iterators read what this one
     writes?
   - **Kill switch:** which config, default state?
   - **Tier registration:** which tiers list it in `tiers.py`?
   - **Failure mode:** what happens when this iterator crashes — does
     the daemon degrade gracefully, auto-downgrade, or alert?

4. Write the findings into a row of a big audit table.

### 6.2 Check the ordering in `tiers.py`

The list order in `tiers.py` IS the execution order within a tick.
Verify it's common-sense:

- **`account_collector` first** — must be. Every other iterator reads
  `ctx.account_state` from it.
- **`connector` second** — must be. Ensures the HL adapter is alive.
- **`market_structure_iter` before `thesis_engine`** — thesis engine
  reads computed indicators.
- **`thesis_engine` before `execution_engine`** — execution engine
  reads the current thesis state.
- **`oil_botpattern` after `news_ingest`, `supply_ledger`, `heatmap`,
  `bot_classifier`** — strategy consumes the outputs of all four data
  sub-systems.
- **`exchange_protection` after `execution_engine`** — new positions
  get protection applied the tick they're opened, not the next.
- **`journal` after `execution_engine` / after close events** —
  journal writes closed positions.
- **`lesson_author` after `journal`** — lesson author reads the
  journal for closed positions.
- **`entry_critic` after `execution_engine`** — critic reads new
  entries.
- **`telegram` LAST** — everything else queues alerts into `ctx.alerts`
  and telegram drains the queue.

**Document any order violations.** Don't fix them yet; log them for
Phase D.

### 6.3 Check cadence common-sense

For each internal-cadence iterator, ask:

- **Is the cadence too fast?** Example: if `heatmap` re-polls `l2Book`
  every tick (120s) but L2 depth updates much faster, you're missing
  signal. If it polls every 10s but the downstream consumer only
  reads it every minute, you're wasting work.
- **Is the cadence too slow?** Example: if `market_structure_iter`
  computes indicators every 5 minutes but the downstream
  `thesis_engine` is supposed to react to new bars within one, your
  thesis lags.
- **Does the cadence conflict with source data freshness?** Example:
  `memory_consolidation` runs hourly but reads the daemon's in-process
  memory — fine. But if it writes to a file that `memory_backup`
  snapshots hourly too, you might get a backup mid-consolidation.
- **Does the cadence conflict with kill switch philosophy?** Example:
  `oil_botpattern_reflect` runs weekly — but only if the daemon is up
  continuously for a week. If the daemon restarts daily, the weekly
  cadence never fires. Check the `_last_tick` persistence.

### 6.4 Check sequencing edge cases

- **Daemon restart:** when the daemon restarts, do iterators with
  `_last_tick` state reload it from disk, or do they fire immediately
  on the first tick after restart? Both behaviors are valid, but
  different ones suit different iterators. `memory_backup` should
  probably fire after a long gap; `action_queue` should NOT fire
  duplicates if restart happens mid-nudge.
- **Tier downgrade:** when the clock auto-downgrades tier
  (`clock.py:349`), iterators NOT in the new tier's set stop being
  called. Does any iterator hold state that needs cleanup on being
  removed from the active set? What if the downgrade happens mid-loop
  — is there a guarantee the in-flight tick finishes?
- **Kill switch toggle:** when the user flips
  `oil_botpattern.json → short_legs_enabled: true`, is the change
  picked up on the next tick without a restart? If yes, does the
  iterator re-initialise any state that depends on the flag?
- **Parallel processes:** does anything else besides the daemon write
  to the config files, data files, or memory.db? If yes, is the
  write safe? Example: if `/lessonauthorai` is running an AI session
  that writes lesson candidates at the same tick that `lesson_author`
  is writing them, do they collide?

### 6.5 Output: `docs/plans/TIMER_LOOP_AUDIT.md`

Big table + a narrative analysis. Suggested structure:

```markdown
# Timer & Loop Audit — 2026-04-YY

## 1. Execution model summary
[one-page recap: daemon tick, per-iterator throttle, tier set rebuild]

## 2. Iterator inventory with cadences and dependencies

| Iterator | Cadence | Reads | Writes | Depends on | Depended on by | Failure mode |
|----------|---------|-------|--------|------------|----------------|--------------|
| ... |

## 3. Sequencing analysis
### 3.1 Proper ordering verified
- account_collector → everyone (ctx)
- market_structure → thesis_engine
- ...

### 3.2 Order violations found
- [iterator X] runs before [iterator Y] but reads what Y just wrote
- ...

## 4. Cadence analysis
### 4.1 Too fast
- ...
### 4.2 Too slow
- ...
### 4.3 Fine as-is
- ...

## 5. Edge cases
### 5.1 Daemon restart behavior per iterator
### 5.2 Tier downgrade cleanup
### 5.3 Kill switch hot-reload
### 5.4 Parallel writer safety (AI commands + iterators + Telegram)

## 6. Scheduled external jobs
[launchd plists, cron entries, anything outside the daemon]

## 7. Recommendations (prioritized for Phase D)
[ranked list of findings that need fixing]
```

### 6.6 Scheduled external jobs to check

Beyond the daemon, the system also has:

- **launchd plists** in `~/Library/LaunchAgents/com.hyperliquid.*` —
  document each, what it runs, when, its log paths, restart policy.
  Run `launchctl list | grep -i hyper`.
- **Any cron?** — check `crontab -l` on the user's machine (ask first).
- **Python schedulers inside the app?** — grep for `schedule.`,
  `APScheduler`, `threading.Timer`, `asyncio.sleep`. Anything that
  isn't the daemon tick loop is a separate timer to document.
- **Claude Code scheduled tasks** (plugins/scheduled-tasks) — probably
  out of scope for the daemon review but worth noting.

**Acceptance criterion:** `TIMER_LOOP_AUDIT.md` committed. Every
iterator in `cli/daemon/iterators/` has a row in §2. At least one
"too fast / too slow / fine" judgment per iterator. At least one
recommendation in §7.

**Gotchas:**
- Do NOT make changes to iterators during this phase. Findings only.
- Do NOT run the daemon on mainnet to "see what happens" — use
  `--mock` and `--max-ticks 10` if you need a live tick sample.
- Some iterators have failure modes that aren't obvious from reading
  — run `.venv/bin/python -m pytest tests/test_<iterator>_iterator.py -q`
  to see what behaviors the test suite already captures.

---

## 7. Phase D — Cohesion review (prioritized hardening list) (60–90 min)

**Goal:** take the findings from Phases B + C and produce a
**prioritized hardening list**. This is what the user will work from
when deciding what to fix next.

### 7.1 Scoring rubric

Score every finding on:

- **Impact** (1–3): 1 = cosmetic, 2 = degrades functionality, 3 =
  can damage capital or the trading thesis
- **Likelihood** (1–3): 1 = would need an unusual sequence of events,
  2 = possible with normal operation, 3 = will happen the next time
  the relevant code runs
- **Effort** (1–3): 1 = <1h fix, 2 = half-day, 3 = multi-session
- **Priority** = (Impact × Likelihood) − Effort (range −2 to +8)

Anything scoring 5+ is a P0. 3–4 is P1. 1–2 is P2. <1 is P3 (note
only).

### 7.2 Structure the output

Write `docs/plans/COHESION_HARDENING_LIST.md`:

```markdown
# Cohesion Hardening List — 2026-04-YY

Derived from BATTLE_TEST_LEDGER.md and TIMER_LOOP_AUDIT.md. Items
are prioritized by Impact × Likelihood − Effort.

## P0 — must fix before promoting any sub-system kill switch
1. [finding] — impact 3, likelihood 3, effort 1 → score 8
   - source: [phase/section]
   - fix: [one-sentence]
   - acceptance: [how to know it's done]

## P1 — fix before battle-testing
## P2 — fix when convenient
## P3 — note only

## Meta-findings
[things that aren't discrete fixes but patterns — e.g. "the daemon has
no holistic 'all iterators healthy' dashboard", "there's no replay
harness for a full tick sequence"]

## Deferred to ADR-011 quant app
[things that the proposed sibling app would address more cleanly than
fixing in the current daemon]
```

### 7.3 Categories to cover

At minimum, the list should cover:

1. **Any order violations** found in Phase C.
2. **Any battle-test blockers** from Phase B that could be pre-cleared
   with test setup (example: synthesise a closed bot-pattern trade
   so `oil_botpattern_tune` has something to nudge from).
3. **Any cadence mismatches** — too fast, too slow, misaligned with
   source data freshness.
4. **Any parallel-writer safety gaps** — config files, data files,
   memory.db.
5. **Any daemon restart state issues** — iterators that drop state
   on restart when they shouldn't.
6. **Any tier-downgrade cleanup gaps** — iterators that leave stale
   state when removed from the active set.
7. **Any observability gaps** — places where the user would not know
   a subsystem is failing silently.
8. **Any doc-vs-code drift** not already caught by Phase A (e.g. a
   wiki page that describes a different architecture).
9. **The "things built but not battle-tested" list from Phase B** —
   any items that are high-impact should escalate to P0/P1.

### 7.4 What this phase is NOT

- NOT a code-change phase. Findings + prioritization only.
- NOT a scope-decision phase. The user decides what to ship; this
  phase just puts the options in front of them.
- NOT a rewrite of MASTER_PLAN's "Open Questions / Known Gaps". That
  section should link TO this list, not duplicate it.

**Acceptance criterion:** `COHESION_HARDENING_LIST.md` committed
with ≥3 P0 items (if fewer, either the system is in great shape
or you missed findings — verify with fresh eyes).

---

## 8. Phase E — Vault-as-auditor (60 min)

**Goal:** operationalise the obsidian vault as the system's **drift
detection surface**, per the user's stated intent: *"the vault ...
was also designed to find problem code and breakages etc. It was the
next step in my auditing tool."*

The insight: the vault auto-generator already reads the **authoritative
sources** (iterators, commands, tiers, tools, configs, plans, ADRs).
Every auto-gen run produces a file with frontmatter + description. The
**diff between two runs** IS the structural change surface.

### 8.1 Baseline and scheduled regen

1. Verify the vault is clean against the code AT HEAD after Phase A:
   ```bash
   cd agent-cli && .venv/bin/python scripts/build_vault.py
   git diff docs/vault/
   ```
   Empty diff = baseline locked.
2. Commit the baseline if it isn't already:
   ```bash
   git add agent-cli/docs/vault/
   git commit -m "chore(vault): regenerate at $(date +%Y-%m-%d) baseline"
   ```

### 8.2 Drift-detection protocol

Define a repeatable protocol for detecting structural drift:

1. User makes changes (new iterator, renamed tool, new command,
   moved config).
2. User (or a future session) runs `.venv/bin/python scripts/build_vault.py`.
3. The resulting `git diff docs/vault/` IS the drift report. No
   analysis needed — every row in the diff is a real structural
   change.
4. If the diff has frontmatter changes only (e.g. tier list added
   or kill switch file changed), the change is structurally correct
   and just needs committing.
5. If the diff has DESCRIPTION changes (auto-extracted from source
   docstrings), the source-of-truth docstring changed — which means
   someone edited the iterator and the vault picked it up.
6. If the diff has NEW PAGES — someone added a new iterator, command,
   tool, or config. That iterator's doc page is now part of the
   audit surface.

Write this protocol up as the new **`docs/vault/runbooks/Drift-Detection.md`**
(the vault already has a `runbooks/` folder for hand-written pages).

### 8.3 Add "breakage" detection beyond structural drift

The user said "designed to find problem code and breakages". The
current generator is structural only. Phase E extends it with
lightweight health checks. Don't build a new tool — extend
`scripts/build_vault.py` with a few more queries that produce
health-signal pages:

Proposals (discuss with user before implementing — these are design
suggestions, not commits in this phase):

1. **`docs/vault/health/untested.md`** — list every iterator where
   no `tests/test_<iterator>*.py` exists. Auto-generated from disk.
2. **`docs/vault/health/kill_switches.md`** — one table row per
   `data/config/*.json` with `enabled: true/false` parsed. Alerts
   when `enabled` is true for a subsystem the user expected off.
3. **`docs/vault/health/stale_data.md`** — for each write-target
   file referenced in an iterator (`data/heatmap/zones.jsonl`,
   `data/research/bot_patterns.jsonl`, etc.), show the `mtime` in
   human-friendly form. If anything is older than its expected
   cadence (from Phase C), flag it.
4. **`docs/vault/health/orphans.md`** — iterators registered in
   `tiers.py` but not in any `clock.register()` call (or vice versa).
5. **`docs/vault/health/plan_ships.md`** — for each "shipped" claim
   in `docs/plans/MASTER_PLAN.md`, verify the referenced file path
   exists and was touched recently. Catches stale-claim drift without
   re-enabling Guardian.

None of these need to be committed in Phase E. Phase E writes the
**proposal document** for them:

### 8.4 Output: `docs/plans/VAULT_AS_AUDITOR.md`

```markdown
# Vault-as-Auditor — Proposal

## Vision
The obsidian vault becomes a first-class audit surface by extending
the existing auto-generator with health-signal pages. No new tooling;
just more queries feeding the same frontmatter+body scheme.

## The five health pages
1. untested.md — iterators without test files
2. kill_switches.md — current enable/disable state across subsystems
3. stale_data.md — write-target mtimes vs expected cadence
4. orphans.md — iterators in tiers.py but not registered (or vice versa)
5. plan_ships.md — MASTER_PLAN "shipped" claims vs disk reality

## Implementation sketch
[for each page: what to grep, what to compute, what to emit]

## Drift protocol
[copy of §8.2 from SYSTEM_REVIEW_HARDENING_PLAN.md]

## Estimated effort
~4-6 hours total; each page is additive and testable in isolation.
```

**Acceptance criterion:** `VAULT_AS_AUDITOR.md` committed. Nothing
else shipped in this phase — the actual health pages are a follow-up
work item.

---

## 9. Phase F — Ship report + next-action queue (45 min)

**Goal:** close the loop with the user. Produce a single status
document the user can read in 5 minutes to know where the system
stands after this review, and decide what to do next.

### 9.1 `/brutalreviewai` run (first-ever in anger)

Since the brutal review command has been shipped since mid-morning
and never run, Phase F is a great time to actually run it:

```
Open Telegram → /brutalreviewai
```

Copy the output to `docs/plans/BRUTAL_REVIEW_2026-04-YY.md` verbatim
as the raw feed into the ship report.

If the command fails or produces garbage, file a P0 in the cohesion
list and carry on.

### 9.2 Write the ship report

`docs/plans/REVIEW_2026-04-YY_SHIP_REPORT.md`:

```markdown
# System Review Ship Report — 2026-04-YY

## Headline
[one sentence the user would tell a friend about where the system is]

## Alignment delta (Phase A)
- 68 commits, +54,884 lines, all 2026-04-09
- Docs resynced: MASTER_PLAN, CLAUDE.md, build-log, vault
- Guardian disabled (chore commit X)
- Guardian sweep.py line 167 stale marker removed

## Battle-test summary (Phase B)
- P tier: X items
- S tier: Y items (Z ready for promotion)
- I tier: N items (N inert by design, M blocked on prereqs)
- Link: BATTLE_TEST_LEDGER.md

## Timer & loop findings (Phase C)
- N iterators audited
- N order violations found
- N cadence mismatches
- Link: TIMER_LOOP_AUDIT.md

## Hardening priorities (Phase D)
- N P0 items: [one-liners]
- N P1 items: [one-liners]
- Link: COHESION_HARDENING_LIST.md

## Vault-as-auditor proposal (Phase E)
- 5 health pages proposed (untested, kill_switches, stale_data,
  orphans, plan_ships)
- No code yet — follow-up work item
- Link: VAULT_AS_AUDITOR.md

## Brutal review output (Phase F.1)
- [top 3 findings from /brutalreviewai if ran]
- Link: BRUTAL_REVIEW_*.md

## Recommended next 3 moves
[what to ship next, in rank order, based on the full review]
1. ...
2. ...
3. ...

## Things the user should actively decide
[questions that need user input, not claude judgment]
- [e.g. "when to flip oil_botpattern short_legs_enabled"]
- [e.g. "whether to keep Guardian disabled permanently"]
- [e.g. "whether to execute the memory.db restore drill"]

## What did NOT happen this session
[explicit list of things that were in scope but got deferred and why]
```

### 9.3 Hand back to the user

Commit the ship report. Final commit of the session:

```bash
git add agent-cli/docs/plans/REVIEW_*SHIP_REPORT.md
git add agent-cli/docs/plans/BATTLE_TEST_LEDGER.md
git add agent-cli/docs/plans/TIMER_LOOP_AUDIT.md
git add agent-cli/docs/plans/COHESION_HARDENING_LIST.md
git add agent-cli/docs/plans/VAULT_AS_AUDITOR.md
git add agent-cli/docs/plans/BRUTAL_REVIEW_*.md  # if generated

git commit -m "review: system-wide hardening assessment — ship report

6-phase review completed per docs/plans/SYSTEM_REVIEW_HARDENING_PLAN.md.

Outputs:
- BATTLE_TEST_LEDGER.md (what's proven vs inert)
- TIMER_LOOP_AUDIT.md (cadence + sequencing findings)
- COHESION_HARDENING_LIST.md (prioritized fix list)
- VAULT_AS_AUDITOR.md (drift-detection proposal)
- REVIEW_*_SHIP_REPORT.md (executive summary)

Handoff: see REVIEW_*_SHIP_REPORT.md §Recommended next 3 moves."
```

**Acceptance criterion:** user can read the ship report in 5 min
and know what to do next.

---

## 10. Protocol — how to run this plan

### 10.1 Session setup

1. **Start a fresh session in `/Users/cdi/Developer/HyperLiquid_Bot/`.**
   Do not start this in `agent-cli/` — the project root contains the
   CLAUDE.md with the Trading Safety rules you must obey.
2. **Read this document end-to-end** before taking any action.
3. **Read MASTER_PLAN.md + NORTH_STAR.md** — they are load-bearing for
   any judgment calls.
4. **Read MAINTAINING.md** — it governs how you touch docs.
5. **Do NOT read every iterator's source upfront.** That's the body
   of Phase C and reading it twice wastes context.

### 10.2 Checkpoint commits

Commit at the end of every phase. The commits form a narrative:

```
chore(guardian): disable hooks + sub-agent dispatch loop   # Phase 0
alignment: sync docs + vault to 2026-04-09 PM reality      # Phase A
docs(review): battle-test ledger                            # Phase B
docs(review): timer + loop audit                            # Phase C
docs(review): cohesion hardening list                       # Phase D
docs(review): vault-as-auditor proposal                     # Phase E
review: system-wide hardening assessment — ship report      # Phase F
```

Seven commits, one narrative. If any phase ends with nothing worth
committing, skip the commit for that phase rather than making an
empty one.

### 10.3 Parallel work

Phases A, B, and C can be partially parallelised by dispatching
sub-agents:

- **Phase B** (battle-test classification) is embarrassingly
  parallel. Dispatch one sub-agent per iterator group and merge
  results.
- **Phase C** (timer audit) benefits from parallelisation: dispatch
  one agent per iterator to extract the cadence + dependency facts,
  merge into the big table.
- **Phase A** is too sequential to parallelise safely — doing so
  invites merge conflicts on the same doc files.

Use `dispatching-parallel-agents` skill (from the superpowers plugin)
if you want to parallelise properly. Otherwise do it sequentially —
the plan is sized to fit one evening of work per phase.

### 10.4 When to stop and ask the user

- Any sub-system kill switch flip — STOP, ask.
- Any destructive delete of a file that isn't auto-gen — STOP, ask.
- Any change to `agent/AGENT.md` or `agent/SOUL.md` — STOP, ask.
- Any change to `~/.openclaw/` — STOP, refuse.
- Any `git add -A` temptation — STOP, add by name.
- Any finding that suggests real money is at risk (leverage cap wrong,
  SL/TP missing, authority gate bypass) — STOP, report immediately,
  do not continue with other phases until addressed.

### 10.5 What "done" looks like

At the end of Phase F:

- 7 new commits in git (or 6 if Phase E has nothing to commit, or 5
  if Phase 0 has nothing to commit because the session is already
  clean).
- 5 new plan documents in `docs/plans/`.
- `MASTER_PLAN.md` matches HEAD.
- Vault is regenerated and committed.
- The user has a ship report they can read in 5 minutes.
- The next session can promote sub-systems from the ledger with
  confidence.

---

## 11. Known risks and failure modes to avoid

### 11.1 Do not re-enable Guardian

The prior session shut it off explicitly. Memory file
`memory/feedback_guardian_subagent_dispatch.md` captures the rule.
If you find yourself thinking "a sweep would help here", run
`guardian/sweep.py` manually as a one-shot — don't re-wire the hooks.

### 11.2 Do not amend commit `9153805`

The vault mis-attribution in that commit is a historical curiosity.
Per CLAUDE.md's "no destructive overreach" rule, the fix is a new
commit if needed, never an amend.

### 11.3 Do not touch the adaptive-evaluator WIP

The uncommitted files in §1.1 belong to a workstream you did not
start. If they block your work, ask the user. If they don't, leave
them alone.

### 11.4 Do not promote anything during the review

This review is pure assessment. No kill switches flip. No tier
promotions. No new iterator registrations. The output is a prioritized
list the user acts on — not a list of things you shipped.

### 11.5 Do not let the vault regeneration sweep in new files

`scripts/build_vault.py` only writes to `docs/vault/`. If running it
touches anything outside that directory, stop and investigate — it's
a bug in the generator, not a feature.

### 11.6 Do not trust the previous Claude session's report of state

Re-verify every claim in §1 against live git / file state before
acting on it. Three separate sessions lost time on 2026-04-07 and
2026-04-09 by acting on stale session context. Don't make it four.

### 11.7 Do not write hardcoded counts into any output doc

Per MAINTAINING.md. Phrases like "3,090 tests" or "37 iterators" go
stale the moment the next commit lands. Reference the command that
produces the count instead.

### 11.8 Do not create files outside the plan's scope

This plan names exactly five output documents (battle ledger, timer
audit, cohesion list, vault-as-auditor proposal, ship report). Do
not author a sixth, seventh, or eighth "while you're at it". Scope
creep is how review sessions turn into rewrite sessions.

### 11.9 Treat the Knowledge Graph plan and AGENT.md checklist as sacred parked items

Do not revive the Knowledge Graph. Do not weaponise the Oil Short
Decision Checklist for anything beyond its current experimental
status. The user is observing them for several sessions before
deciding their fate — your job is to note their existence, not to
decide.

### 11.10 Do not run the daemon on mainnet as part of this review

If you need to observe live tick behavior, use `--mock` and
`--max-ticks 10`. Running on mainnet during a review session could
place trades based on stale thesis state. Never worth the risk.

---

## 12. Appendices

### Appendix A: Full commit list since `514e0bf` (68 commits)

```
2026-04-09 07:54 a65b1e5 feat(lessons): candidate consumer + /lessonauthorai (wedge 6 — fully complete)
2026-04-09 08:15 eb7c398 feat(guardian): guide stub for Phase 1
2026-04-09 08:15 7463b96 feat(guardian): drift detector — Phase 2 complete
2026-04-09 08:16 35789e9 feat(guardian): review gate — Phase 3 complete
2026-04-09 08:16 36d43ba feat(guardian): friction surfacer — Phase 4 complete
2026-04-09 ??:?? 1f770e6 docs+feat(lessons): polish — AGENT.md guidance, component page, news enrichment
2026-04-09 ??:?? bb3a289 feat(guardian): sweep orchestrator + SessionStart lazy sweep — Phase 5
2026-04-09 ??:?? 1222f88 fix(guardian): cartographer excludes vendored dirs
2026-04-09 ??:?? 12f1dc2 feat(heatmap): sub-system 3 (stop/liquidity heatmap) — full ship + alignment
2026-04-09 ??:?? a767483 docs(guardian): ADR-014 + wiki + GUARDIAN_PLAN + cross-links — Phase 6
2026-04-09 ??:?? a6c4a20 fix(guardian): massively reduce drift noise — 489 P1 → 39 P1
2026-04-09 ??:?? c43483b feat(bot_classifier): sub-system 4 (bot-pattern classifier) — full ship + alignment
2026-04-09 ??:?? 6fb2076 fix(guardian): telegram-completeness false positives on routed handlers
2026-04-09 ??:?? 7361a35 docs(bot_classifier): note ML + LLM as deferred enhancement (Chris ask)
2026-04-09 ??:?? 0943cb1 feat(guardian): PostToolUse Read hook + full hook wiring + setup docs
2026-04-09 ??:?? 285fc85 docs(oil_botpattern): sub-system 5 plan approved with revisions
2026-04-09 ??:?? 4ffa114 feat(telegram): surface critical commands + Guardian hidden/exempt markers
2026-04-09 ??:?? 56b2dd4 feat(guardian): knowns.py — acknowledged orphans + legitimate pair patterns
2026-04-09 ??:?? 42efb54 feat(oil_botpattern): sub-system 5 (strategy engine) — full ship, INERT by default
2026-04-09 ??:?? 996bf6f feat(memory_backup): hourly atomic snapshots close memory.db SPOF
2026-04-09 ??:?? b436dbf docs+feat(alignment): rewrite MASTER_PLAN against reality + Guardian stale-claim drift detector
2026-04-09 ??:?? 5118f5e fix(lessons): kill switch file + quarantine convention + .gitignore for backup forensics
2026-04-09 ??:?? 51f3744 docs(plans): NORTH_STAR + MULTI_MARKET_EXPANSION + BRUTAL_REVIEW_LOOP — direction setting
2026-04-09 ??:?? bdd2540 refactor(telegram): split lessons commands into cli/telegram_commands/lessons.py — monolith wedge 1
2026-04-09 ??:?? 52a258f feat(brutal_review): wedge 1 — /brutalreviewai command + literal prompt
2026-04-09 ??:?? 0c7bebc feat(multi_market+ops): Wedge 1 — markets.yaml + MarketRegistry + memory restore drill
2026-04-09 ??:?? 0ab9d97 docs(oil_botpattern): sub-system 6 plan doc (L1 + L2 only; L3/L4/L5 deferred)
2026-04-09 ??:?? 75ff943 feat(oil_botpattern_tune): sub-system 6 config files (kill switches OFF)
2026-04-09 ??:?? a681a3d feat(oil_botpattern_tune): L1 bounded auto-tune pure module + tests
2026-04-09 ??:?? 5487d03 feat(oil_botpattern_reflect): L2 weekly reflect pure module + tests
2026-04-09 ??:?? 1ab157f feat(oil_botpattern_tune): L1 daemon iterator + tests
2026-04-09 ??:?? 9c319cc feat(oil_botpattern_reflect): L2 daemon iterator + tests
2026-04-09 ??:?? 931f37c test(telegram): /selftune* command tests (sub-system 6)
2026-04-09 ??:?? faa80ae feat(oil_botpattern_tune): wire L1 + L2 iterators into daemon + tiers
2026-04-09 ??:?? 9e7c1c7 docs(oil_botpattern_tune): wiki + build-log + cli/daemon/CLAUDE.md entries
2026-04-09 ??:?? 760ebeb feat(entry_critic): trade entry critique iterator + /critique Telegram lookup
2026-04-09 ??:?? 5396ece docs(realignment): NORTH_STAR + MASTER_PLAN rewritten to honor founding philosophy
2026-04-09 ??:?? 67c6153 feat(realignment): user-action queue + entry critic verified + chat history correlation + feedback hardening
2026-04-09 ??:?? 4a58095 fix(memory_backup): register MemoryBackupIterator in daemon_start — SPOF was still open
2026-04-09 ??:?? 3bb7a06 docs(oil_botpattern): L3 pattern library config + plan doc status flip
2026-04-09 ??:?? 0ff3e31 feat(oil_botpattern_patternlib): L3 pure module + tests
2026-04-09 ??:?? 26cf21e feat(oil_botpattern_patternlib): L3 daemon iterator + tests
2026-04-09 ??:?? 3eee850 feat(oil_botpattern_patternlib): L3 Telegram commands + tests
2026-04-09 ??:?? 71fa9a4 feat(oil_botpattern_shadow): L4 counterfactual pure module + config + tests
2026-04-09 ??:?? 2bc7312 feat(oil_botpattern_shadow): L4 daemon iterator + tests
2026-04-09 ??:?? 7860958 feat(oil_botpattern_shadow): L4 /shadoweval Telegram command + tests
2026-04-09 ??:?? 515aa73 feat(oil_botpattern): register L3 + L4 iterators in tiers.py + daemon.py
2026-04-09 ??:?? 8f2b7f7 feat(telegram): wire /shadoweval into HANDLERS + help + guide (L4)
2026-04-09 ??:?? c72b867 docs(oil_botpattern): L3 + L4 wiki component doc + build-log entry
2026-04-09 ??:?? c028264 docs+fix(p10): Data Discipline principle + agent-tool retrieval bounds
2026-04-09 ??:?? 1bc40c4 feat(historical_oracle): chat history .bak union for search + ctx.prices in snapshot
2026-04-09 ??:?? 4ffc805 refactor(telegram): split portfolio commands into cli/telegram_commands/portfolio.py — wedge 2
2026-04-09 ??:?? bbc91e2 docs(thinking_graph): wedge 1 — concept catalog + oil_short_decision graph (data only)
2026-04-09 ??:?? 347d8e5 fix(p10): close all HIGH + CRITICAL audit findings — system prompt cap, signals/lesson clamps, memory_read cap, chat history tail-read
2026-04-09 ??:?? 4c8545c feat(oil_botpattern_paper): shadow trader pure module + tests
2026-04-09 ??:?? 16aff60 feat(oil_botpattern): decisions_only shadow mode in sub-system 5 iterator
2026-04-09 ??:?? 07c1f23 feat(telegram): /sim and /readiness commands for sub-system 5 activation
2026-04-09 ??:?? 33e75fe feat(telegram): wire /sim and /readiness into HANDLERS + help + guide
2026-04-09 ??:?? 9c5f799 docs(ops): sub-system 5 activation runbook
2026-04-09 ??:?? 0882b4e docs(park): Knowledge Graph Thinking Regime parked + P5 sub-rule for "validate before planning"
2026-04-09 ??:?? 72b9e90 feat(oil_botpattern_adaptive): live thesis-testing evaluator + training log schema
2026-04-09 ??:?? f490c0f feat(oil_botpattern): wire adaptive evaluator into shadow-mode iterator
2026-04-09 ??:?? 7f65cfd feat(telegram): /activate — guided sub-system 5 activation walkthrough
2026-04-09 ??:?? 165b0fe feat(oil_botpattern): adaptive evaluator parity for LIVE positions (exit-only v1)
2026-04-09 ??:?? deef0f9 feat(telegram): /adaptlog — query the adaptive evaluator decision log
2026-04-09 ??:?? d47a8f3 experiment(agent): add Oil Short Decision Checklist to AGENT.md — cheap test for the parked Knowledge Graph plan
2026-04-09 14:08 9153805 fix(readiness): thesis epoch-ms fallback + heatmap snapshot_at field
2026-04-09 14:09 998b6bb fix(bot_classifier): fetch 1m candles from HL API directly (cache was empty)
```

(Regenerate with `git log --format='%ad %h %s' --date=short 514e0bf..HEAD` if
you want exact timestamps for the middle commits — I've only shown HH:MM for
first/last/representative.)

### Appendix B: Iterator inventory with tier assignment matrix

Generate from `cli/daemon/tiers.py` at the moment you run Phase C —
don't rely on this table, it's only a starting hint. Iterators listed
here are those present as of the committed `tiers.py` (the uncommitted
change adds oil_botpattern* to WATCH; verify whether it has been
committed before trusting this matrix):

| Iterator                       | Watch | Rebalance | Opportunistic |
|--------------------------------|:-----:|:---------:|:-------------:|
| account_collector              | ✓     | ✓         | ✓             |
| connector                      | ✓     | ✓         | ✓             |
| liquidation_monitor            | ✓     | ✓         | ✓             |
| funding_tracker                | ✓     | ✓         | ✓             |
| protection_audit               | ✓     | ✓         | ✓             |
| brent_rollover_monitor         | ✓     | ✓         | ✓             |
| market_structure               | ✓     | ✓         | ✓             |
| thesis_engine                  | ✓     | ✓         | ✓             |
| radar                          | ✓     |           | ✓             |
| news_ingest                    | ✓     | ✓         | ✓             |
| supply_ledger                  | ✓     | ✓         | ✓             |
| heatmap                        | ✓     | ✓         | ✓             |
| bot_classifier                 | ✓     | ✓         | ✓             |
| oil_botpattern                 | (unc) | ✓         | ✓             |
| oil_botpattern_tune            | (unc) | ✓         | ✓             |
| oil_botpattern_reflect         | (unc) | ✓         | ✓             |
| oil_botpattern_patternlib      | ✓     | ✓         | ✓             |
| oil_botpattern_shadow          | (unc) | ✓         | ✓             |
| pulse                          | ✓     |           | ✓             |
| liquidity                      | ✓     | ✓         | ✓             |
| risk                           | ✓     | ✓         | ✓             |
| apex_advisor                   | ✓     |           |               |
| autoresearch                   | ✓     | ✓         | ✓             |
| memory_consolidation           | ✓     | ✓         | ✓             |
| journal                        | ✓     | ✓         | ✓             |
| lesson_author                  | ✓     | ✓         | ✓             |
| entry_critic                   | ✓     | ✓         | ✓             |
| memory_backup                  | ✓     | ✓         | ✓             |
| action_queue                   | ✓     | ✓         | ✓             |
| execution_engine               |       | ✓         | ✓             |
| exchange_protection            |       | ✓         | ✓             |
| guard                          |       | ✓         | ✓             |
| rebalancer                     |       | ✓         | ✓             |
| catalyst_deleverage            |       | ✓         | ✓             |
| profit_lock                    |       | ✓         | ✓             |
| telegram                       | ✓     | ✓         | ✓             |

`(unc)` = uncommitted; present in the working tree's `tiers.py` but
not in HEAD as of plan authoring.

### Appendix C: Config file scheduling snapshot

See §1.4. Re-run this check at Phase C kick-off:

```bash
cd agent-cli
for f in data/config/*.json; do
  name=$(basename "$f" .json)
  python3 -c "
import json
d = json.load(open('$f'))
if isinstance(d, dict):
    keys = ['enabled','tick_interval_s','interval_seconds','interval_hours','run_interval','cadence','check_interval_s']
    rows = [(k,d[k]) for k in keys if k in d]
    if rows: print('$name:', dict(rows))
"
done
```

### Appendix D: Files named in this plan

| Path                                                     | Status |
|----------------------------------------------------------|--------|
| `docs/plans/SYSTEM_REVIEW_HARDENING_PLAN.md`             | this file |
| `docs/plans/BATTLE_TEST_LEDGER.md`                       | create in Phase B |
| `docs/plans/TIMER_LOOP_AUDIT.md`                         | create in Phase C |
| `docs/plans/COHESION_HARDENING_LIST.md`                  | create in Phase D |
| `docs/plans/VAULT_AS_AUDITOR.md`                         | create in Phase E |
| `docs/plans/BRUTAL_REVIEW_2026-04-YY.md`                 | create in Phase F.1 if command runs |
| `docs/plans/REVIEW_2026-04-YY_SHIP_REPORT.md`            | create in Phase F |
| `docs/vault/runbooks/Drift-Detection.md`                 | create in Phase E |
| `CLAUDE.md` (project root)                               | edit in Phase A (Guardian ref) |
| `agent-cli/docs/plans/MASTER_PLAN.md`                    | edit in Phase A (surgical) |
| `agent-cli/docs/plans/NORTH_STAR.md`                     | verify in Phase A, edit only if drift |
| `agent-cli/docs/wiki/build-log.md`                       | append in Phase A |
| `agent-cli/guardian/sweep.py`                            | line 167 delete in Phase A |
| `agent-cli/.claude/settings.json`                        | already emptied this session |
| `agent-cli/guardian/hooks/session_start.py`              | already disabled this session |
| `agent-cli/cli/CLAUDE.md`, `agent-cli/cli/daemon/CLAUDE.md` | audit in Phase A |
| `agent-cli/docs/vault/` (all)                            | regenerate in Phase A |

### Appendix E: Reference commands the next session will need

```bash
# Project root
cd /Users/cdi/Developer/HyperLiquid_Bot

# Agent-cli workdir
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli

# Find last alignment commit (authoritative)
git log --oneline --all --grep="^alignment:" -1 --format="%H %s"

# Commits since last alignment
git log --format='%ad %h %s' --date=short 514e0bf..HEAD  # replace hash

# Diff stats since last alignment
git log --shortstat 514e0bf..HEAD --format=format: | \
  awk '/files? changed/ {f+=$1; i+=$4; d+=$6} END {print f,"files", i,"ins", d,"del"}'

# Test suite
.venv/bin/python -m pytest tests/ guardian/tests/ -q --no-header 2>&1 | tail -5

# Live test count
.venv/bin/python -m pytest tests/ -q --collect-only 2>&1 | tail -1

# Vault regeneration
.venv/bin/python scripts/build_vault.py 2>&1 | tail -20

# Daemon mock tick (safe, 10 ticks)
hl daemon start --tier watch --mock --max-ticks 10

# Daemon live status (read-only)
hl daemon status

# Launchd state
launchctl list | grep -i hyper

# Kill switch dump
for f in data/config/*.json; do
  echo "=== $(basename $f .json) ==="
  python3 -m json.tool "$f" | head -20
done

# Current thesis state
ls -lt data/thesis/
for f in data/thesis/*.json; do
  echo "=== $(basename $f .json) ==="
  python3 -c "import json; d=json.load(open('$f')); print({k:d.get(k) for k in ['updated_at','last_updated','timestamp','last_evaluation_ts','conviction']})"
done

# Memory backup state
ls -lt data/memory/backups/ | head -10

# Iterator source inventory (for Phase C)
ls cli/daemon/iterators/*.py | xargs -I{} bash -c 'echo "=== {} ==="; head -15 {}'
```

---

## 13. Final note to the next session

This plan was written in the same session that shut Guardian off and
disabled the hook loop that was driving the user insane. The author is
tired. The plan is comprehensive but not perfect. When you find
something that's wrong, FIX IT and note the fix in the ship report
under "plan corrections". Don't treat this document as sacred — treat
it as a starting map that you're expected to improve.

The user's ask, verbatim, was:
> Go through ALL our recent git commits for records, trace our
> updates. conduct maintenance.md and /alignment etc to bring the
> repo and master_plan.md etc all up to speed with current app. Lot's
> has been built, but lot's hasn't been battle tested yet. Also I
> created the obsidian vault, it's good, but it was also designed to
> find problem code and breakages etc. It was the next step in my
> auditing tool. Come up with a plan for a review process of the
> entire system as a whole to let me know what needs hardening,
> testing, updates etc. to work cohesively. I also need to track and
> check timer and loops for when processes run, how they run,
> sequencing, is it common sense etc. This is a very living system...
> It's big, lots of concurrent processes and workflows running. We
> need a plan to get a handle on it. I won't do it in this chat. I
> will start in a new one. so write very comprehensively.

That's what this plan is for. Phase F closes the loop by producing
the ship report the user will read to decide what to ship next.

**Now stop reading. Start Phase 0.**
