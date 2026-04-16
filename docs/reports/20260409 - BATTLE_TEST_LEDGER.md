# Battle-Test Ledger — 2026-04-09

> Phase B output of the System Review & Hardening Plan (see
> `docs/plans/SYSTEM_REVIEW_HARDENING_PLAN.md` §5).
> **Cut-off:** HEAD = `42eca28` (Phase A alignment commit). Classification
> compared against the last `alignment:` commit `514e0bf`.

## What this is

A point-in-time snapshot of which system components are
**Production-verified (P)**, **Synthetic-verified (S)**, or **Inert (I)**.

| Tier | Definition |
|------|------------|
| **P** | Actually ran against real market data or real position state, with observable output that matches reality (fresh output on disk OR observed Telegram alert OR live iterator state from a real tick). |
| **S** | Unit / integration tests green, reads/writes in dev mode or against a single synthetic row, no real production observation yet. |
| **I** | Kill switch off, iterator not registered for the current tier, or read-only shadow mode producing zero side effects. |

## How it's used

Read before promoting any sub-system from kill-switch-off to kill-switch-on.
Read before committing to a real-money test. Never trust a "shipped" label
without cross-checking against this ledger.

## Methodology

For each iterator / command / agent tool / sub-system in the ship list,
I checked: (1) source file exists, (2) test file exists, (3) kill-switch
config state (`enabled`), (4) output file on disk, (5) file mtime vs now,
(6) last row content sanity-check, (7) runtime state (`data/daemon/*.json`).
The daemon is running at `tier: watch`, tick 4955 at classification time
(pid 18320, `cli.main daemon start --tier watch --mainnet --tick 120`).
Telegram bot is running (pid 72197). Every assertion in the "Last real
activity" column is derived from `ls -lt` + `tail -1 <file>` run within
this session — no cached values.

**Scope note.** "New since 514e0bf" means the iterator / command / tool was
either added in a commit between `514e0bf` and HEAD, or was meaningfully
re-shaped in that window. Pre-existing rows are included for context and
classified briefly — they are not the focus of this ledger.

---

## Iterators

| Iterator | Tier | Last real activity | Kill switch | Since 514e0bf? | Notes |
|----------|------|--------------------|-------------|----------------|-------|
| `account_collector` | P | every tick (daemon.log live) | none | modified | Produces `ctx.account_state` that every other iterator reads. Daemon tier = watch, tick 4955. |
| `connector` | P | every tick | none | pre-existing | HL API session alive; `data/daemon/roster.json` updated 16:10. |
| `market_structure_iter` | P | every tick (WIP in working tree) | none | pre-existing | Adaptive-evaluator WIP untouched per instructions. Classify from code only. |
| `pulse` | P | tick-throttled, 120s | n/a | pre-existing | Pre-existing. |
| `radar` | P | tick-throttled, 300s | n/a | pre-existing | Pre-existing. |
| `apex_advisor` | P | 60s throttle | n/a | pre-existing | Pre-existing. |
| `rebalancer` | P | per-slot tick_interval | per-slot | pre-existing | `data/daemon/roster.json` contains `power_law_btc` slot, last_tick 1774773914 (stale — verify Phase C). |
| `thesis_engine` | P | every tick | none | pre-existing | Pre-existing. |
| `execution_engine` | P | every tick | none | pre-existing | Pre-existing. |
| `exchange_protection` | P | every tick | none | pre-existing | Pre-existing. |
| `risk` | P | every tick | none | pre-existing | Pre-existing. |
| `guard` | P | every tick | none | pre-existing | Pre-existing. |
| `profit_lock` | P | every tick | none | pre-existing | Pre-existing. |
| `journal` | P | `data/research/trades/` has files through 2026-04-08 | none | pre-existing | 7 trade files, last at 2026-04-08 05:47. No closed trades in the 2026-04-09 burst window. |
| `memory_consolidation` | P | `data/agent_memory/MEMORY.md` mtime 10:01 | n/a | pre-existing | Hourly consolidation confirmed by file mtime. |
| `telegram` | P | 72197 live, `Bot online` | n/a | pre-existing | Last chat_history entry 16:11 local (hormuz blockade question from Chris). |
| `autoresearch` | S | no output file touched today | n/a | pre-existing | Registered but not driving decisions. |
| `liquidity` | P | every tick | n/a | pre-existing | Pre-existing. |
| `catalyst_deleverage` | P | reads `data/daemon/external_catalyst_events.json` (mtime 16:05) | n/a | pre-existing | Live bridge to news_ingest — external_catalyst_events.json is the handoff file. |
| `news_ingest` (sub-system 1) | **P** | `data/news/catalysts.jsonl` mtime 16:05, last row is live Hormuz chokepoint_blockade catalyst for xyz:BRENTOIL + CL | `news_ingest.json` enabled=true | pre-existing, modified | Real RSS feed producing real catalysts. Observed end-to-end: news → catalyst → Telegram alert (Chris asked about it in chat history at 16:11). |
| `supply_ledger` (sub-system 2) | **P** | `data/supply/state.json` mtime 16:05, 8 active disruptions computed from news rule | `supply_ledger.json` enabled=true | pre-existing, modified | state.json rebuilt from live disruptions.jsonl; `/disrupt` manual path untested but auto-extract path is active. |
| `heatmap` (sub-system 3) | **P** | `data/heatmap/zones.jsonl` mtime 16:08, BRENTOIL zones at mid=95.33 matching current price | `heatmap.json` enabled=true | **new** | Live l2Book polling, fresh snapshot_at field (post `9153805` fix), zones look real. Cascades file not yet present — no cascade event observed. |
| `bot_classifier` (sub-system 4) | **P** | `data/research/bot_patterns.jsonl` mtime 16:08, 22 rows, latest is BRENTOIL classification with confidence=0.7 | `bot_classifier.json` enabled=true | **new** | 1m candle fetch fix landed 14:09 (commit `998b6bb`); post-fix rows look valid. Output does NOT yet drive any decisions — downstream consumer (sub-system 5) is in shadow. |
| `oil_botpattern` (sub-system 5) | **I** (shadow) | `data/strategy/oil_botpattern_journal.jsonl` 36 rows mtime 15:52, `oil_botpattern_adaptive_log.jsonl` 461 rows mtime 16:05 | `oil_botpattern.json` enabled=true, **short_legs_enabled=false, decisions_only=true** | **new** | Iterator runs but emits zero OrderIntents. Dual kill switch. Shadow paper positions maintained with starting $100k bankroll. Adaptive evaluator exit-only v1 wired in and producing decisions ("hypothesis intact" etc) against LIVE position context. **All side effects are file writes only.** |
| `oil_botpattern_tune` (L1) | **I** | `data/strategy/oil_botpattern_tune_audit.jsonl` does **not exist** | `oil_botpattern_tune.json` enabled=false | **new** | Kill switch off. Even if enabled, requires ≥5 closed bot-pattern trades to nudge from. Zero exist. |
| `oil_botpattern_reflect` (L2) | **I** | `data/strategy/oil_botpattern_proposals.jsonl` does **not exist** | `oil_botpattern_reflect.json` enabled=false | **new** | Kill switch off. Requires 7-day window + closed trades before a proposal can be emitted. |
| `oil_botpattern_patternlib` (L3) | **I** | `data/research/bot_pattern_candidates.jsonl` does **not exist** | `oil_botpattern_patternlib.json` enabled=false | **new** | Kill switch off. Requires ≥3 novel signatures in `bot_patterns.jsonl` to emit a candidate. Currently 22 rows but no signature diversity check run. |
| `oil_botpattern_shadow` (L4) | **I** | `data/strategy/oil_botpattern_shadow_evals.jsonl` does **not exist** | `oil_botpattern_shadow.json` enabled=false | **new** | Kill switch off. Requires at least one approved L2 proposal to run a counterfactual. |
| `lesson_author` | **S** | `data/daemon/lesson_author_state.json` shows `processed_ids: ["BTC-smoketest-2026-04-09"]`, lessons table has 1 row | `lesson_author.json` enabled=true | **new** | Iterator is live and has processed ONE synthetic smoke-test journal entry. `data/daemon/lesson_candidates/` directory is empty. Waiting on first real closed trade. |
| `entry_critic` | **P** | `data/research/entry_critiques.jsonl` 2 rows mtime 13:58, entry_critic_state.json fingerprint `xyz:CL\|long\|95.578\|39.306` | `entry_critic.json` enabled=true | **new** | Processed a real live CL entry — NOT just a synthetic test row. Grade was `MIXED ENTRY` with `no thesis for this market` warning (real thesis gap exposed). This is P-tier: observation matches reality. |
| `action_queue` | **P** | `data/research/action_queue.jsonl` 7 rows mtime 14:25, 4 rows show `last_nudged_ts > 0` (including `backup_health_check` with `last_done_ts` set) | none | **new** | Real nudges have fired in production (not just queued). Each nudge rows show deterministic cadence tracking. One item (`backup_health_check`) shows a successful completion. |
| `memory_backup` | **P** | `data/memory/backups/` contains 10 hourly snapshots, newest 13:58 local | `memory_backup.json` enabled=true, interval_hours=1 | **new** | Hourly atomic snapshots of `memory.db` are on disk. Backup cadence correct. **Restore drill NOT yet executed** — runbook shipped same day. |
| `liquidation_monitor` | S | no liquidation event observed | n/a | pre-existing | Deterministic unit tests green. No real liquidation event to observe. |
| `brent_rollover_monitor` | S | no rollover event observed | n/a | pre-existing | Tests green. First real rollover alert not yet observed. |
| `protection_audit` | P | every tick | n/a | pre-existing | Read-only verifier; runs against live positions; no alert logged today. |
| `funding_tracker` | P | every tick | n/a | pre-existing | Pre-existing, running. |

> **Sub-total:** 21 P, 4 S, 6 I across 31 iterators. Every iterator in
> `cli/daemon/iterators/*.py` at HEAD has a row above.

---

## Telegram commands

Only commands **new** (or meaningfully re-shaped) since `514e0bf` are
tier-classified below. Pre-existing commands (`/status`, `/price`, `/orders`,
`/pnl`, `/brief`, `/briefai`, `/chart*`, `/health`, etc.) are P-tier via daily
operator use and are not individually listed — see `cli/telegram_bot.py`
HANDLERS dict for the full set.

| Command | Tier | Last fired / test state | Notes |
|---------|------|-------------------------|-------|
| `/heatmap` | P | reads live `data/heatmap/zones.jsonl` (16:08) | Command runs deterministic formatting over real heatmap zones. |
| `/botpatterns` | P | reads live `data/research/bot_patterns.jsonl` (16:08) | Deterministic reader, real data. |
| `/oilbot` | S | state file present but decisions_only shadow | Reads `oil_botpattern_state.json` (real file) but the underlying iterator is in shadow. Tests cover the command. |
| `/oilbotjournal` | S | reads `oil_botpattern_journal.jsonl` (shadow decisions) | Same shadow-only caveat. |
| `/oilbotreviewai` | I | never fired | AI command; suffix correct. Needs real closed trades before output is meaningful. |
| `/selftune` | I | state file does not exist | L1 kill switch off. |
| `/selftuneproposals` | I | proposals file does not exist | L2 kill switch off. |
| `/selftuneapprove` | I | never fired | No proposals to approve. Tests exist (`test_telegram_oil_botpattern_commands.py`). |
| `/selftunereject` | I | never fired | Same. |
| `/patterncatalog` | I | candidates file does not exist | L3 kill switch off. |
| `/patternpromote` | I | never fired | Same. |
| `/patternreject` | I | never fired | Same. |
| `/shadoweval` | I | evals file does not exist | L4 kill switch off. |
| `/sim` | S | reads shadow state file | Sub-system 5 activation walkthrough helper; tests green. |
| `/readiness` | S | thesis epoch-ms fallback fixed post `9153805` | Activation preflight checklist; observed one successful render end-to-end during fix commit. |
| `/activate` | S | never fired by Chris (activation not yet attempted) | Guided activation walkthrough; tests cover the rung logic. |
| `/adaptlog` | P | reads live `oil_botpattern_adaptive_log.jsonl` (461 rows, 16:05) | Filters real shadow decisions. |
| `/lessonauthorai` | S | lessons table has 1 row (synthetic smoke-test) | AI command (suffix correct). No real closed trade has driven the author yet. |
| `/brutalreviewai` | I | **never fired** | AI-suffixed command; prompt literal at `docs/plans/BRUTAL_REVIEW_PROMPT.md`. Flagged in SYSTEM_REVIEW_HARDENING_PLAN §1.2 as "running it is one of the first tasks in this plan". |
| `/critique` | P | reads `entry_critiques.jsonl` with real CL entry | Deterministic reader, real row. |
| `/nudge` | P | reads `action_queue.jsonl`; real nudges have fired | Real Telegram alerts dispatched (see `last_nudged_ts > 0` rows). |
| `/chathistory` / `/ch` | P | `data/daemon/chat_history.jsonl` 299 lines, .bak union implemented in `1bc40c4` | Daily operator-reachable browse command. |
| `/feedback` (new behavior) | P | `data/feedback.jsonl` 13,756 bytes, mtime 2026-04-07 | Pre-existing but kill-switch file + quarantine convention added `5118f5e`. Production path. |
| `/todo` (new behavior) | P | pre-existing command; no recent writes | Behavior adjustment only. |
| `/disrupt` / `/disruptions` | P | real disruptions.jsonl live; `/disruptions` reads real state | Manual-entry path not exercised; auto-extract path is (see `news_auto` source tags). |
| `/addmarket` / `removemarket` | S | tests in `test_market_registry.py` green | Multi-market wedge 1 surface. No new market added in production yet (no non-BTC/BRENTOIL/CL market rows in markets.yaml beyond the thesis-driven list). |
| `/delegate` / `/reclaim` / `/authority` | P | pre-existing, used daily | Not re-shaped. |
| `/models` / `/model` (show-model) | P | pre-existing | Not re-shaped. |

> **Sub-total (new commands since 514e0bf):** 7 P, 8 S, 11 I across 26
> classified commands.

---

## Agent tools

No new agent tools were added between `514e0bf` and HEAD — `search_lessons`,
`get_lesson`, `introspect_self`, `read_reference` all pre-date the cut-off
(commits `dda624f` and `7fab372`). The only agent-tool changes since
`514e0bf` are the P10 data-discipline clamps in `347d8e5` + `c028264`
(bounded retrieval caps, not new tools). Classified for completeness
because the review plan explicitly lists them:

| Tool | Tier | Notes |
|------|------|-------|
| `search_lessons` | S | FTS5 search over lessons table; 1 row in corpus (synthetic smoke-test). Tests green. Bounded by retrieval clamp from `347d8e5`. |
| `get_lesson` | S | Fetches by id; only 1 id exists. Bounded by clamp. |
| `introspect_self` | P | Reads real reference docs shipped with `7fab372`. Deterministic, used by the agent runtime. |
| `read_reference` | P | Same — reads the 4 bundled reference docs. |
| `memory_read` / `memory_write` | P | Pre-existing; clamps added in `347d8e5`. |
| All other agent tools | P | Pre-existing (no changes in the window beyond P10 clamps). See `cli/agent_tools.py` for the live count. |

---

## Sub-systems

| Sub-system | Tier | Gate to promote |
|------------|------|-----------------|
| Oil Bot Pattern #1 news_ingest | **P** | Already production. Promotion path = wire more feeds + tune severity rules. No kill switch flip needed. |
| Oil Bot Pattern #2 supply_ledger | **P** | Already production on the auto-extract path. Promotion = observe `/disrupt` manual path end-to-end. |
| Oil Bot Pattern #3 heatmap | **P** | Already production at the zones level. Promotion = first real cascade detection event (cascades.jsonl is empty). |
| Oil Bot Pattern #4 bot_classifier | **P** (data path), **I** (decision path) | Data path is live; decision path is gated behind sub-system 5's shadow mode. Promote by flipping sub-system 5 out of decisions_only. |
| Oil Bot Pattern #5 oil_botpattern | **I** | Dual kill switch: `short_legs_enabled=true` AND tier promotion to REBALANCE. Precondition: run `/readiness` + `/activate` walkthrough and pass; also want shadow balance to show expected edge over a multi-day window first. |
| Oil Bot Pattern #5 adaptive evaluator | **P** (shadow) | 461 live decision rows against real position state. Promotion = wire entry-side evaluator (currently exit-only v1) once exit-side data validates. |
| Oil Bot Pattern #6 L1 tune | **I** | Kill switch + ≥5 closed bot-pattern trades (current: 0). |
| Oil Bot Pattern #6 L2 reflect | **I** | Kill switch + 7-day window + closed trades. |
| Oil Bot Pattern #6 L3 patternlib | **I** | Kill switch + ≥3 novel signatures in 30-day rolling window of `bot_patterns.jsonl`. Need to verify whether the 22 current rows include ≥3 distinct `(classification, direction, confidence_band, signals)` tuples — if yes, promotion is gated only by the kill switch. |
| Oil Bot Pattern #6 L4 shadow (counterfactual) | **I** | Kill switch + at least one approved L2 proposal. Cannot promote before L2. |
| Trade Lesson Layer | **S** | First real closed trade flows through `lesson_author`. |
| Entry Critic | **P** | Already live — one real CL entry processed. Promotion = observe multi-entry stability, wire into pre-trade agent prompt if desired. |
| Action Queue | **P** | Live; `backup_health_check` already shows a successful completion. Promotion = tune cadences once Chris has observed a full week of nudges. |
| Memory Backup | **P** (backup loop), **S** (restore drill) | Backups on disk. **Restore drill has NOT been executed** — runbook exists at `docs/wiki/operations/memory-restore-drill.md`. Promote by executing the drill once. |
| Brutal Review Loop Wedge 1 | **I** | `/brutalreviewai` never fired. Flagged as "run it" in the top of the review plan. |
| Multi-Market Wedge 1 (MarketRegistry) | **S** | `markets.yaml` + registry shipped, tests green. Behavior identical to pre-ship (long-only-oil rule moved from code to config). No new market has been added to the registry in production. |
| Telegram monolith split Wedges 1–2 | **P** | `cli/telegram_commands/lessons.py` + `portfolio.py` extracted; live Telegram bot is importing them (process 72197 running). |
| Historical Oracle P10 hardening | **P** | Clamps + tail-read live in `cli/agent_tools.py`; system prompt cap live in `agent_runtime`. |
| Guardian meta-system | **I** (disabled) | **Shipped then immediately shut off same day.** `.claude/settings.json` hooks emptied. `guardian/hooks/session_start.py` sub-agent dispatch disabled. Do NOT re-enable without explicit user authorization. See `memory/feedback_guardian_subagent_dispatch.md`. |

---

## Promotion-ready list

Items in **S** tier that are ONE observation away from **P**:

1. **`lesson_author`** — needs the first real closed trade to flow through.
   Precondition: any journal row with a non-synthetic `entry_id`. Chris's
   $50 BTC vault smoke test (mentioned in review plan §1.2) is the
   intended trigger.
2. **Trade Lesson Layer (end-to-end)** — same trigger as above; once
   `lesson_author` produces a real candidate, `/lessons` + `/lessonauthorai`
   round-trips become P-tier.
3. **Memory Backup (restore drill)** — the backup loop is already P; the
   restore drill half is S because the runbook has not been executed. One
   successful drill promotes the whole sub-system. See
   `docs/wiki/operations/memory-restore-drill.md`.
4. **`/readiness`** — ran once successfully in the `9153805` fix commit,
   but has not been exercised by Chris as part of the activation
   walkthrough. One real operator run promotes it.
5. **`/sim`** — same shape as `/readiness`; reads the real shadow state
   file, but has not been operator-exercised.

## Promotion-blocked list

Items in **I** tier with concrete blockers:

1. **`oil_botpattern_tune` (L1)** — blocked on ≥5 closed bot-pattern
   trades. Current count: **0**. Unblocking requires either (a) real
   trades after sub-system 5 kill-switch promotion, OR (b) synthesising
   closed trades into the journal for a dev-only tune run (flagged as
   Phase D candidate in review plan).
2. **`oil_botpattern_reflect` (L2)** — blocked on 7-day window of closed
   trades. Even with L1 unblocked, L2 needs continuous daemon uptime for
   7 days plus non-zero closed-trade volume. Verify `_last_tick`
   persistence across daemon restarts (Phase C task).
3. **`oil_botpattern_shadow` (L4)** — blocked on ≥1 approved L2 proposal.
   Cannot promote before L2. Hard dependency chain L2 → L4.
4. **`oil_botpattern_patternlib` (L3)** — blocked on ≥3 novel signatures
   in `bot_patterns.jsonl` 30-day rolling window. Unknown whether the
   22 current rows already satisfy this — needs a one-shot diversity
   query. If yes, this is actually **promotion-ready** (only the kill
   switch stands in the way).
5. **`/brutalreviewai`** — no hard blocker; just requires Chris (or this
   session) to fire it once. Review plan §1.2 flags this as the intended
   first real run of the loop.
6. **`oil_botpattern` (sub-system 5) REBALANCE promotion** — blocked on
   `/readiness` pass + Chris's explicit go-ahead. The `/activate`
   walkthrough is the gate.
7. **Guardian** — blocked by user directive. Do not re-enable.

---

## Notes for Phase D (cohesion hardening)

Items noticed during classification that are NOT tier judgements but
should feed Phase D:

1. **Missing cascade events in heatmap.** `data/heatmap/zones.jsonl`
   is live but `data/heatmap/cascades.jsonl` does not exist. Either the
   cascade detector has never fired a real cascade (plausible —
   BRENTOIL is quiet today), or the writer path is silent-failing.
   Phase C should trace the cascade write path end-to-end.

2. **`/adaptlog` is doing the heaviest write in the system.** The
   adaptive log is 432 KB / 461 rows across a single day of shadow
   operation with exit-only v1. If entry-side is wired later without a
   rotation policy, this file will become unbounded. Recommend Phase D
   rotation spec similar to the tick-journal daily rotation (see
   `f8bbb57` H5 precedent).

3. **Action queue cadence vs tick cadence mismatch.** `action_queue`
   iterator default tick_interval is 24h (interval_hours), but the daemon
   global tick is 120s. Reloading state across daemon restarts is
   untested — the review plan §6.4 explicitly asks this. `last_nudged_ts`
   values on disk look deterministic but there's no unit test covering
   "daemon restarted mid-24h-window" behaviour.

4. **`entry_critic_state.json` fingerprint uniqueness gap.** Current
   fingerprint is `xyz:CL|long|95.578|39.306`. Two positions at the same
   price + size would collide. Not a bug today (xyz:CL has been the only
   live entry since ship), but Phase D should consider adding a timestamp
   or position UUID to the fingerprint.

5. **`lesson_author` `last_offset: 586`** in state file — reads a byte
   offset from an upstream journal. If the journal is rotated (per H5),
   the offset becomes stale. Verify `lesson_author` handles journal
   rotation cleanly. Unknown today.

6. **`news_ingest` + `supply_ledger` coupling.** `news_ingest` writes
   `catalysts.jsonl` with a live Hormuz chokepoint_blockade event at
   severity 5. `supply_ledger` picked it up (disruption auto-extract
   path) and computed `total_offline_bpd: 0.0` because `volume_offline`
   is null in the rule-generated disruption. This means the sub-system
   recognises the chokepoint but has no volume estimate to feed into
   any downstream risk calculation. Cosmetic or real? Phase D should
   decide whether the bridge needs a volume-estimate table.

7. **`oil_botpattern_adaptive_log` decision density.** 461 shadow
   decisions in one day = one every ~3 minutes while the daemon has
   been up. That's the adaptive evaluator running on every cycle per
   open shadow position. Verify in Phase C that this is intended
   cadence and that the evaluator isn't re-grading the same snapshot.

8. **Pre-existing iterator `rebalancer`** has `last_tick: 1774773914`
   (2026-04-05) which is 4 days stale. Either the power-law BTC
   strategy was intentionally paused or the rebalancer isn't ticking.
   `paused: false` in roster.json. Worth investigating in Phase C.

9. **`/brutalreviewai` has never been fired** — this is the user's own
   review tool and the review plan calls it out as the intended first
   task. If it IS fired during Phase F, it will generate its own
   findings that feed Phase D.

10. **Multi-market wedge 1 `markets.yaml`** defines direction_bias +
    exception_subsystems but there's no test verifying that the
    `oil_botpattern` sub-system actually appears in BRENTOIL's
    exception_subsystems list before the short-legs path runs. Worth
    a Phase D regression test.

11. **No test covers the `decisions_only=true` → `decisions_only=false`
    hot-reload transition.** Sub-system 5 activation assumes the flag
    flip is picked up on the next tick. Verify in Phase C + add a test
    in Phase D if missing.

12. **`data/agent_memory/.last_dream` is zero bytes** (touched 10:01).
    Dream consolidation file `dream_consolidation.md` is 5188 bytes
    (same mtime). Expected behaviour or silent-failure marker? Unknown.
