# Cohesion Hardening List — 2026-04-09

> **Phase D output** of `SYSTEM_REVIEW_HARDENING_PLAN.md` §7.
> **Derived from:** `BATTLE_TEST_LEDGER.md` (Phase B) +
> `TIMER_LOOP_AUDIT.md` (Phase C).
> **Cut-off:** HEAD `959022d` (Phase C commit).

## What this is

A prioritized hardening backlog. Every item is a concrete fix with a
score, a source pointer, and an acceptance criterion. **Chris works from
this list top-down.**

## Scoring rubric

```
Priority = (Impact × Likelihood) − Effort
  Impact     1 cosmetic · 2 degrades function · 3 can damage capital or trading thesis
  Likelihood 1 unusual sequence · 2 possible in normal ops · 3 will happen next time the code runs
  Effort     1 <1h · 2 half-day · 3 multi-session

  P0  score ≥ 5  → must fix before promoting any sub-system kill switch
  P1  score 3–4 → fix before battle-testing
  P2  score 1–2 → fix when convenient
  P3  score < 1 → note only
```

---

## P0 — must fix before promoting any sub-system kill switch

### P0-1 — `risk` iterator loses gate state across restart
- **Score:** 6 (Impact 3, Likelihood 2, Effort 1)
- **Source:** Phase C §6.1 risk row, R3
- **Problem:** `RiskManager.state.safe_mode` and `consecutive_losses` live
  in process memory only. A crash-loop during a COOLDOWN or CLOSED gate
  event silently clears the gate on restart — worst possible failure mode
  for a risk system.
- **Fix:** persist `RiskManager.state` to `data/daemon/risk_state.json`
  on save; reload in `on_start`.
- **Acceptance:** restart the daemon mid-COOLDOWN in mock mode; gate
  survives restart. New unit test `test_risk_state_persistence.py`.
- **Cheapest P0 to land first.**

### P0-2 — Catalyst-to-strategy pipeline latency unbounded (12+ min worst case)
- **Score:** 5 (Impact 3, Likelihood 2, Effort 2)
- **Source:** Phase C §5.1 C1, R1
- **Problem:** `news_ingest` (60s) → `supply_ledger` (300s) → `bot_classifier`
  (300s) → `oil_botpattern` (60s). Every hop has its own monotonic
  throttle, phases drift randomly, a severity-5 catalyst sits in
  `catalysts.jsonl` for up to 12 minutes before the strategy sees it.
  Defeats the point of a shock-reactive oil strategy.
- **Fix:** document the end-to-end invariant and add a fast-path for
  severity≥5 catalysts that bypasses the `bot_classifier` hop and pushes
  directly into `oil_botpattern`'s next tick (`ctx.urgent_catalysts`
  channel or equivalent).
- **Acceptance:** a unit test that feeds a severity-5 catalyst into
  `news_ingest` and asserts `oil_botpattern` sees it within two ticks
  (≤240s).

### P0-3 — `journal` silently drops trades closed during daemon downtime
- **Score:** 5 (Impact 3, Likelihood 2, Effort 2)
- **Source:** Phase C §6.1 journal row, R2
- **Problem:** `_prev_positions` is in-memory only. On restart, any
  position that was open pre-crash but flat post-crash is treated as
  "never existed." No lesson candidate written, no PnL row, no learning
  signal — the trade vanishes. This directly undermines the lesson
  layer promotion gate.
- **Fix:** on `on_start`, reconcile `ctx.positions` against the last
  persisted position set and emit synthetic close events for any
  missing instruments.
- **Acceptance:** integration test that opens a position in mock mode,
  stops the daemon, closes the position via adapter, restarts the
  daemon, asserts a close event appears in `journal.jsonl`.

### P0-4 — `exchange_protection._tracked` lost on restart → duplicate SL risk
- **Score:** 5 (Impact 3, Likelihood 2, Effort 2)
- **Source:** Phase C §6.1 exchange_protection row, R4
- **Problem:** iterator forgets which SLs it already placed on restart.
  May re-issue stop orders against positions that already have them,
  creating cascading stop orders on the exchange — a real-money risk.
- **Fix:** on `on_start`, fetch current exchange trigger orders and
  repopulate `_tracked` before the first tick.
- **Acceptance:** mock-mode test: place a position + SL, simulate daemon
  restart, assert no duplicate SL is issued on the next tick.

### P0-5 — `thesis_engine` silently drops half-written thesis files
- **Score:** 5 (Impact 3, Likelihood 2, Effort 2)
- **Source:** Phase C §5.1 C2, R6
- **Problem:** when the AI agent is mid-write of a thesis JSON file
  (via `update_thesis` tool), the daemon's thesis_engine iterator can
  read the partial file. On `JSONDecodeError` the iterator falls
  through silently and uses the last successfully-parsed thesis —
  stale conviction drives live trading decisions.
- **Fix:** audit every write path in `common/thesis.py`; enforce
  atomic-rename on all of them. In the iterator, on `JSONDecodeError`,
  retry once 100 ms later before falling through.
- **Acceptance:** unit test that simulates a half-written thesis file
  and asserts the iterator retries rather than using stale conviction.

### P0-6 — `data/heatmap/cascades.jsonl` silent write-path audit
- **Score:** 5 (Impact 3, Likelihood 2, Effort 2) *(B-finding)*
- **Source:** Phase B §Notes 1
- **Problem:** `zones.jsonl` is live and fresh; `cascades.jsonl` does
  not exist on disk at all. Either BRENTOIL has genuinely had zero
  cascade events (plausible given quiet market), or the cascade
  writer path is silent-failing.
- **Fix:** trace the cascade write path in `cli/daemon/iterators/heatmap.py`
  end-to-end. Add a "no events detected in last 24h" INFO log line so
  silence becomes observable.
- **Acceptance:** either (a) confirmed real silence with an observability
  log line, or (b) bug fix + unit test.

---

## P1 — fix before battle-testing

### P1-1 — `oil_botpattern_adaptive_log.jsonl` unbounded growth
- **Score:** 4 (Impact 2, Likelihood 3, Effort 2) *(B-finding)*
- **Source:** Phase B §Notes 2
- **Problem:** 432 KB / 461 rows after one day of exit-only shadow.
  When entry side is wired in, growth rate doubles or more. No rotation.
- **Fix:** daily rotation (same pattern `journal.py` uses for
  `ticks-YYYYMMDD.jsonl`).
- **Acceptance:** rotation after 24h; archived file under a
  `_YYYYMMDD` suffix; live file resets.

### P1-2 — `zones.jsonl` and `cascades.jsonl` unbounded growth
- **Score:** 4 (Impact 2, Likelihood 3, Effort 2)
- **Source:** Phase C §5.1 C6, R8
- **Problem:** heatmap writes append-only with no retention. Each tick
  writes ~200 zones. Linear growth indefinitely.
- **Fix:** hour-retention rotation (~24h trailing window retained
  live; older rotated to `.archive`).
- **Acceptance:** `zones.jsonl` stays bounded after 48h of daemon uptime.

### P1-3 — Triple-writer race on `data/config/oil_botpattern.json`
- **Score:** 3 (Impact 3, Likelihood 1, Effort 2, with latent P0 once
  switches flip)
- **Source:** Phase C §5.2, R5
- **Problem:** `oil_botpattern_tune` (daemon), Telegram `/activate`
  (separate process), manual edits — three writers, zero serialization.
  Last-writer-wins silently. Bounded today only by both sides being
  kill-switched. **When either side activates, this becomes a silent
  corruption path.**
- **Fix:** `fcntl.lockf` on a sidecar `.lock` file around every
  `_write_strategy_config_atomic` call (daemon + Telegram).
- **Acceptance:** integration test that dispatches two concurrent
  writes and asserts both land correctly serialized.
- **Note:** escalate to P0 at the moment either side's kill switch flips.

### P1-4 — `entry_critic_state.json` fingerprint collision
- **Score:** 4 (Impact 2, Likelihood 2, Effort 1) *(B-finding)*
- **Source:** Phase B §Notes 4
- **Problem:** current fingerprint format is
  `xyz:CL|long|95.578|39.306`. Two positions at the same price + size
  collide — the critic will skip-grade the second. Not a bug today
  (`xyz:CL` has been the only live entry since ship) but a time bomb.
- **Fix:** append a position UUID or open-timestamp to the fingerprint.
- **Acceptance:** unit test that opens two same-price same-size
  positions sequentially and asserts both receive independent critiques.

### P1-5 — `lesson_author` byte-offset into rotated journal
- **Score:** 4 (Impact 2, Likelihood 2, Effort 1) *(B-finding)*
- **Source:** Phase B §Notes 5
- **Problem:** `lesson_author` stores a byte offset into the upstream
  journal. When the journal rotates (per H5 daily-rotation convention),
  the offset becomes stale — the iterator skips every post-rotation
  trade.
- **Fix:** switch to a row-identity key (trade ID or filename+offset
  pair) rather than bare byte offset. OR: catch journal rotation and
  reset the offset.
- **Acceptance:** rotation-simulation test: write N lesson candidates,
  trigger a journal rotation, write M more candidates, assert all
  N + M are processed.

### P1-6 — `action_queue` never fires if daemon restarts more often than 24h
- **Score:** 3 (Impact 2, Likelihood 2, Effort 1)
- **Source:** Phase C §5.4, R7
- **Problem:** monotonic `_last_run` is in-memory; 24h cadence gets
  reset every restart. A daemon that auto-restarts every 6h will
  never fire a nudge.
- **Fix:** replace monotonic `_last_run` with a persisted
  `last_sweep_ts` in the state JSONL.
- **Acceptance:** integration test that restarts the daemon 3× within
  a simulated 24h window and asserts `action_queue` still fires once.

### P1-7 — `news_ingest` re-alerts same catalyst after restart
- **Score:** 3 (Impact 1, Likelihood 3, Effort 1)
- **Source:** Phase C §6.1 news_ingest row, R9
- **Problem:** `_alerted_catalyst_ids` is in-memory only.
- **Fix:** persist to `data/news/alerted.json` (same pattern `entry_critic`
  uses).
- **Acceptance:** restart test: alert once, restart, assert no re-alert.

### P1-8 — `brent_rollover_monitor._fired` set lost on restart
- **Score:** 3 (Impact 1, Likelihood 3, Effort 1)
- **Source:** Phase C §6.1 brent row, R10
- **Problem:** same pattern as P1-7.
- **Fix:** persist to state file.
- **Acceptance:** same pattern as P1-7.

### P1-9 — Double candle fetch: `market_structure` + `bot_classifier`
- **Score:** 3 (Impact 1, Likelihood 3, Effort 1)
- **Source:** Phase C §3.2 V5, R11
- **Problem:** both iterators fetch 1m candles for BRENTOIL/CL
  independently.
- **Fix:** `bot_classifier` reads from `CandleCache` first; direct HL
  fetch only on cache miss.
- **Acceptance:** integration test asserting only one HL fetch per
  candle per tick.

### P1-10 — `autoresearch` appends unchanged output every 30 min
- **Score:** 3 (Impact 1, Likelihood 3, Effort 1)
- **Source:** Phase C §4.2 autoresearch row, R12
- **Problem:** `learnings.md` grows with mostly-redundant reflection
  entries.
- **Fix:** hash the reflection dict; skip append if unchanged.
- **Acceptance:** 30 min run in mock mode produces at most one new
  `learnings.md` section when inputs don't change.

### P1-11 — `radar` dead in OPPORTUNISTIC (consumer is WATCH-only)
- **Score:** 3 (Impact 1, Likelihood 3, Effort 1)
- **Source:** Phase C §3.2 V3, R18
- **Problem:** `radar` runs in OPPORTUNISTIC but `apex_advisor` (its
  only consumer) is WATCH-only. Pure waste.
- **Fix:** either add `apex_advisor` to OPPORTUNISTIC (reads same ctx
  fields) or remove `radar` from OPPORTUNISTIC.
- **Acceptance:** pick one; update `tiers.py`; no behavior change on
  WATCH.

### P1-12 — Missing test: sub-system 5 `decisions_only` hot-reload
- **Score:** 4 (Impact 2, Likelihood 2, Effort 1) *(B-finding)*
- **Source:** Phase B §Notes 11
- **Problem:** activation flow assumes flipping `decisions_only: true
  → false` is picked up on next tick. No test verifies this.
- **Fix:** add `test_oil_botpattern_decisions_only_hotreload.py`.
- **Acceptance:** test passes; promotion runbook references the test.

### P1-13 — Missing test: BRENTOIL exception_subsystems precondition
- **Score:** 4 (Impact 2, Likelihood 2, Effort 1) *(B-finding)*
- **Source:** Phase B §Notes 10
- **Problem:** `markets.yaml` defines `exception_subsystems` for the
  long-only-oil rule. No regression test asserts `oil_botpattern` is
  in BRENTOIL's list. A typo or yaml re-indent could silently disable
  the only legal short path.
- **Fix:** add a test in `test_markets_registry.py` that asserts
  `oil_botpattern in markets["BRENTOIL"].exception_subsystems`.
- **Acceptance:** test passes; unit-test-only.

### P1-14 — `rebalancer` last_tick stale by 4 days while paused=false
- **Score:** 3 (Impact 2, Likelihood 2, Effort 1) *(B-finding)*
- **Source:** Phase B §Notes 8
- **Problem:** power-law BTC rebalancer looks silently not-ticking.
  `roster.json` shows `paused: false` but `last_tick` is 2026-04-05.
- **Fix:** investigate the silence. Either a genuine pause (fix roster
  state) or a bug (iterator not being called). Add a "last_tick older
  than X" warning log on startup.
- **Acceptance:** root cause identified; either roster state corrected
  or iterator wired correctly.

---

## P2 — fix when convenient

### P2-1 — `oil_botpattern_proposals.jsonl` rewrite race (shadow vs telegram)
- **Score:** 1 (Impact 2, Likelihood 1, Effort 2)
- **Source:** Phase C §5.1 C7, R13
- **Fix:** `fcntl.lockf` guard (same primitive as P1-3).

### P2-2 — `thesis_engine` poll at 60s vs multi-month thesis validity
- **Score:** 2 (Impact 1, Likelihood 2, Effort 1)
- **Source:** Phase C §4.1 thesis row, R14
- **Fix:** switch to mtime-watch or bump cadence to 300s.

### P2-3 — `catalyst_deleverage` inert in WATCH tier
- **Score:** 2 (Impact 3, Likelihood 1, Effort 2)
- **Source:** Phase C §6.2 catalyst_deleverage row, R15
- **Fix:** register in WATCH as read-only warning, or add a startup
  alert if a pending catalyst is within 24h when the iterator isn't
  in the active tier set.

### P2-4 — Document `memory_consolidation → memory_backup` ordering invariant
- **Score:** 2 (Impact 1, Likelihood 2, Effort 1)
- **Source:** Phase C §5.1 C5, R16
- **Fix:** add an invariant comment to `cli/daemon/CLAUDE.md` so future
  edits to `tiers.py` don't silently reverse the order.

### P2-5 — Document `oil_botpattern_tune → oil_botpattern` config write-read order
- **Score:** 1 (Impact 2, Likelihood 1, Effort 2)
- **Source:** Phase C §3.2 V1, R17
- **Fix:** invariant comment + regression test in `test_tiers.py` that
  fails if someone reorders the list.

### P2-6 — `supply_ledger` volume-offline bridge for catalysts
- **Score:** 2 (Impact 1, Likelihood 2, Effort 2) *(B-finding)*
- **Source:** Phase B §Notes 6
- **Problem:** `news_ingest` emits a Hormuz severity-5 blockade with
  `volume_offline: null`. `supply_ledger` picks it up but
  `total_offline_bpd: 0.0` — no downstream risk signal. Cosmetic or
  real?
- **Fix:** decide whether a catalyst → volume-estimate lookup table is
  worth building. Small lookup table for the big chokepoints
  (Hormuz ≈ 21 mbbl/d, Suez ≈ 9, Bab el-Mandeb ≈ 5).
- **Acceptance:** either (a) a simple lookup table is wired, or (b)
  explicit ADR that says "null is correct because we rely on human
  override".

### P2-7 — Adaptive evaluator decision cadence audit
- **Score:** 1 (Impact 1, Likelihood 2, Effort 2) *(B-finding)*
- **Source:** Phase B §Notes 7
- **Problem:** 461 decisions/day = one every ~3 min per open shadow
  position. Is the evaluator re-grading the same snapshot across
  consecutive ticks?
- **Fix:** verify the dedup logic in the adaptive evaluator. Add a
  snapshot-hash check.

---

## P3 — note only

- **N1** `dream_consolidation.md` has content but `.last_dream` is
  zero-byte. Expected (marker file) or silent-failure? Phase B §Notes 12.
  Needs 5 min of observation.
- **N2** `brutalreviewai` has never been fired. Phase B §Notes 9.
  Phase F of this review plan fires it — that closes this note.
- **N3** `heartbeat` launchd job has `KeepAlive=false` — deliberate
  one-shot pattern. Documented in Phase C §1.1. Mention for future
  readers, no fix.

---

## Meta-findings (pattern-level, not individual fixes)

These aren't discrete fixes; they're shapes that emerged from the audit.

### M1 — All five P0s cluster at process-boundary transitions

Every P0 (P0-1 through P0-5) is a failure mode that manifests only
across a restart or across a process boundary. The daemon's happy-path
behaviour within a stable uptime window is mostly correct. This
suggests a pattern:

> **Every iterator with in-memory state should have a
> `state_to_dict` + `state_from_dict` pair and persist to
> `data/daemon/<iterator>_state.json` on save.**

This is a recurring fix, not a one-off. Phase D implements it per
iterator; a follow-up wedge could formalize it as a base class
mix-in (`RestartSafeIterator`).

### M2 — Telegram + daemon write the same files without coordination

`telegram_bot.py` (PID 72197) and the daemon (PID 18320) both write to
`data/config/oil_botpattern.json`, `data/config/watchlist.json`,
`data/authority.json`, and `data/strategy/oil_botpattern_proposals.jsonl`.
There is no IPC, no lock, no atomic-swap discipline consistently
applied. **Pattern fix**: a small `common/file_lock.py` helper that
wraps `fcntl.lockf` around atomic-rename, used by both processes.

### M3 — Long-cadence iterators (>1h) need wall-clock, not monotonic, schedules

`oil_botpattern_reflect` (7d), `action_queue` (24h), `memory_backup`
(1h — already wall-clock), `memory_consolidation` (1h — not wall-clock).
Any iterator whose cadence is longer than expected daemon uptime between
restarts MUST be wall-clock-scheduled or it will never fire. Pattern fix:
**all iterators with `interval_hours` or cadence >1h use
`last_run_wallclock_ts` in the state file, not `time.monotonic()`**.

### M4 — The promotion gate for every sub-system is "first real closed trade"

L1 tune, L2 reflect, L3 patternlib, L4 shadow, lesson layer, entry critic
are all blocked on the same prerequisite: the first real closed trade
flowing through the system. This suggests a single hand-run smoke test
(the $50 BTC vault run Chris mentioned) unblocks ~6 promotion decisions
simultaneously. **Promotion gate**: land one real trade end-to-end, then
re-classify the Battle-Test Ledger in one pass.

### M5 — Vault drift is already happening, quietly

The obsidian vault's `iterators/oil_botpattern.md` currently reflects
the adaptive-evaluator WIP's `tiers.py` modification (WATCH tier added),
but HEAD does not. This is a **feature**, not a bug — it tells you the
WIP has diverged from HEAD. But there's no surface showing the diff. A
`vault health/drift.md` page (proposed in Phase E) would make this
visible.

---

## Deferred to ADR-011 quant app

Items that the proposed sibling `quant/` app (ADR-011) would address
more cleanly than patching the current daemon:

- **Replay harness for any past tick.** Phase C wanted mock-mode tick
  sampling; a real replay harness against the Parquet data catalog is
  much cleaner.
- **Daily report data-driven.** The current daily report is hand-assembled.
  ADR-011 §1 Tier 1 names this as a prerequisite; it IS Phase D-adjacent
  but belongs to the quant app.
- **Backtesting for every Phase D fix.** Items like P0-2 (catalyst fast
  path) would benefit from a backtest against real catalyst history
  before shipping. Today the best we can do is unit tests + mock-mode
  integration tests; the quant app would add real replay.
- **Signal-generator refactoring.** The move from "strategy = trader"
  to "strategy = signal generator" is an ADR-011 goal; several P2
  iterator-cadence concerns go away entirely under signal-generator
  semantics.

---

## How to use this list

1. Work top-down. Do not skip P0 items.
2. Each fix lands as its own commit with the `P0-` / `P1-` / `P2-` ID
   in the message.
3. After every P0 commit, rerun the full suite (`.venv/bin/python -m
   pytest tests/ guardian/tests/ -q`).
4. After every P0 commit, update the Battle-Test Ledger if the fix
   changes a classification.
5. After all P0s land, re-run `scripts/build_vault.py` and commit the
   vault diff.
6. Items flagged `(B-finding)` came from Phase B; items without are
   from Phase C. All items were scored consistently using the same
   rubric.

---

## What this phase is NOT

- NOT a code-change phase — findings + prioritization only.
- NOT a scope-decision phase — the user decides what to ship.
- NOT a rewrite of `MASTER_PLAN.md` "Open Questions / Known Gaps".
  That section should link TO this list, not duplicate it.
- NOT a complete audit of pre-existing code. Pre-`514e0bf` code is in
  scope ONLY where Phase B or Phase C surfaced a specific issue.
