# System Review Ship Report — 2026-04-09

> **Phase F output** of `SYSTEM_REVIEW_HARDENING_PLAN.md` §9.
> **Review window:** 2026-04-09, one evening.
> **Read this first.** Every link below points to a deeper doc.

## Headline

**After 68 shipping commits on 2026-04-09, the bot is bigger than any
operator can hold in their head. This review audited all of it,
disabled Guardian, classified every new component, traced every
timer, and produced a prioritized hardening backlog. All five P0s
cluster at process-boundary transitions — happy-path is fine; the
pathologies live at restarts.**

## Review commits

One narrative across seven commits on branch `public-release`:

```
a9cc94e chore(guardian): gut all three hooks + land SYSTEM_REVIEW_HARDENING_PLAN    [Phase 0]
42eca28 alignment: sync docs + vault to 2026-04-09 PM reality (Phase A)             [Phase A]
32403ee docs(review): battle-test ledger (Phase B)                                  [Phase B]
959022d docs(review): timer + loop audit (Phase C)                                  [Phase C]
828c29a docs(review): cohesion hardening list (Phase D)                             [Phase D]
<E>     docs(review): vault-as-auditor proposal + cohesion layer (Phase E)          [Phase E]
<F>     review: system-wide hardening assessment — ship report                      [Phase F]
```

## Alignment delta (Phase A)

- **68 commits, +54,884 lines, all on 2026-04-09** between last
  `alignment:` (`514e0bf`) and the Phase 0 commit.
- **Guardian DISABLED** at every layer: `.claude/settings.json`
  emptied (gitignored, local-only); all three hook scripts
  (`session_start.py`, `pre_tool_use.py`, `post_tool_use.py`) gutted
  to no-op stubs; five hook tests deleted; `sweep.py` stale "Phase 5"
  marker removed. Re-enable policy: **none without explicit user
  authorization**.
- **Docs resynced**: `CLAUDE.md` (project root, out-of-repo edit),
  `MASTER_PLAN.md`, `NORTH_STAR.md`, `cli/daemon/CLAUDE.md`,
  `common/CLAUDE.md`, `modules/CLAUDE.md`, `cli/CLAUDE.md`,
  `build-log.md` (new entry at top). Surgical, not rewritten.
- **Vault regenerated** (`scripts/build_vault.py`). 4 new auto-gen
  plan pages picked up in Phase E.

Full detail: commit message of `42eca28`.

## Battle-test summary (Phase B)

31 iterators classified:
- **P (production-verified):** 21 — pre-existing iterators running
  against real account state (account_collector, connector,
  protection_audit, memory_backup, etc.)
- **S (synthetic-verified):** 4 — new iterators wired and tested
  but awaiting first real observation (`lesson_author`,
  `entry_critic`, `action_queue`, `brent_rollover_monitor`)
- **I (inert by design):** 6 — kill-switched or shadow-only
  (`oil_botpattern` family L1–L4 + sub-system 5 in shadow mode)

Sub-systems: 19 classified (7 P / 3 S / 9 I + split-tier items).

**Promotion-ready (one observation from P):**
1. `lesson_author` / Trade Lesson Layer — needs first real closed
   trade (the $50 BTC vault smoke test Chris mentioned).
2. Memory Backup restore drill — runbook shipped, never executed.
3. `/readiness` + `/sim` — observed once in fix commits, need a
   clean operator dry-run.

**Promotion-blocked (I with concrete blockers):**
1. `oil_botpattern_tune` (L1) — 0 closed bot-pattern trades; needs
   ≥5.
2. `oil_botpattern_reflect` (L2) — 7-day window + closed trades.
3. `oil_botpattern_shadow` (L4) — ≥1 approved L2 proposal.

**Full ledger:** [BATTLE_TEST_LEDGER.md](BATTLE_TEST_LEDGER.md)

## Timer + loop findings (Phase C)

33 iterators audited. One clean sequencing order violation found
plus three "looked wrong, verified OK" near-misses and one
dead-channel waste (`radar` in OPPORTUNISTIC with no
`apex_advisor` consumer).

**Top 3 time-loop interweaving findings most likely to bite:**

1. **Catalyst-to-strategy pipeline latency is 12+ minutes worst
   case.** `news_ingest` (60 s) → `supply_ledger` (300 s) →
   `bot_classifier` (300 s) → `oil_botpattern` (60 s). Phase drift
   makes a severity-5 catalyst sit for up to 12 minutes before
   the strategy sees it. Defeats the point of a shock-reactive
   oil strategy.

2. **Triple-writer race on `data/config/oil_botpattern.json`.**
   `oil_botpattern_tune` (daemon), Telegram `/activate` (telegram
   process), manual edits — three atomic-rename writers with zero
   serialization. Last-writer-wins silently. Bounded today only by
   both sides being kill-switched. **Hot the moment either flips.**

3. **`journal` silently drops trades closed during daemon
   downtime.** `_prev_positions` is in-memory only. Any position
   that was open pre-crash but flat post-crash is treated as
   "never existed." No lesson, no PnL, no learning signal — the
   trade vanishes.

**Full audit:** [TIMER_LOOP_AUDIT.md](TIMER_LOOP_AUDIT.md)

## Hardening priorities (Phase D)

**6 P0s (score ≥5) — must fix before promoting any sub-system kill switch:**

1. **P0-1 `risk` iterator gate state across restart** (score 6, 1h)
   — **cheapest P0, land first**. Persist `RiskManager.state` to
   `data/daemon/risk_state.json`.
2. **P0-2 Catalyst-to-strategy pipeline latency unbounded** (score
   5). Fast-path for severity≥5 catalysts.
3. **P0-3 `journal` misses trades closed during daemon downtime**
   (score 5). Reconcile positions on `on_start`.
4. **P0-4 `exchange_protection._tracked` lost on restart → duplicate
   SL risk** (score 5). Repopulate from exchange trigger orders on
   `on_start`.
5. **P0-5 `thesis_engine` silently drops half-written thesis files**
   (score 5). Enforce atomic rename + retry on `JSONDecodeError`.
6. **P0-6 `heatmap/cascades.jsonl` silent write-path audit** (score
   5). Either a real silence (observability log) or a bug fix.

**14 P1s, 7 P2s, 3 P3s.** Full list: [COHESION_HARDENING_LIST.md](COHESION_HARDENING_LIST.md).

**Meta-pattern (M1 in the hardening list):** every P0 is a failure
mode that manifests only across a restart or across a process
boundary. The daemon's happy-path within stable uptime is mostly
correct. **Fix pattern:** formalize a `RestartSafeIterator` mix-in
base class that enforces `state_to_dict` + `state_from_dict` on any
iterator with in-memory state.

## Vault-as-auditor proposal (Phase E)

The obsidian vault is already the system's best drift-detection
surface — regen + `git diff` = drift report. Phase E extends it
with **two layers**:

- **Drift-detection layer (shipped):**
  - [`docs/vault/runbooks/Drift-Detection.md`](../vault/runbooks/Drift-Detection.md)
    — the protocol.
  - [`docs/vault/architecture/Cohesion-Map.md`](../vault/architecture/Cohesion-Map.md)
    — hand-written parallel-writer matrix (daemon ↔ telegram ↔
    heartbeat). Identifies 4 RACE-unacceptable files bounded only
    by kill switches being OFF.
  - [`docs/vault/architecture/Time-Loop-Interweaving.md`](../vault/architecture/Time-Loop-Interweaving.md)
    — hand-written catalog of cross-iterator signal chains with
    worst-case end-to-end latencies. The time-loop layer the user
    explicitly asked for.

- **Health-signal layer (proposed, not shipped):**
  7 new auto-gen pages (`untested.md`, `kill_switches.md`,
  `stale_data.md`, `orphans.md`, `plan_ships.md`,
  `parallel_writers.md`, `cadence_interweaving.md`). ~14h total
  across 6 implementation wedges. Several of these would have
  caught Phase B + C findings automatically.

**Proposal:** [VAULT_AS_AUDITOR.md](VAULT_AS_AUDITOR.md).

## Brutal review output (Phase F.1)

**DEFERRED** — `/brutalreviewai` is Telegram-only and cannot be
invoked from this CLI review session. Filed as N2 in the
COHESION_HARDENING_LIST (P3 note). User action: open Telegram →
`/brutalreviewai` → copy the output into
`docs/plans/BRUTAL_REVIEW_2026-04-09.md` → incorporate any new
findings into the Phase D list.

## Recommended next 3 moves

Ranked on Phase D priority + real-money risk + prerequisite
unblocking:

### 1. Land the 5 "restart safety" P0s as one focused commit burst

The meta-pattern (M1) says all 5 P0s fix the same architectural
gap: iterators with in-memory state that don't persist across
restart. The cheapest is **P0-1 risk state** (~1 h). Ship it first
to prove the pattern, then ship P0-3, P0-4, P0-5, P0-2 in the
same session. Target: one commit per fix, all tests green before
each commit.

**Why this first:** these are the failures that would silently
damage real capital if sub-system 5 or any active sizing iterator
was promoted to REBALANCE tier. They block every promotion.

### 2. Run the $50 BTC vault smoke test

The single hand-run trade that unblocks six promotion decisions
(M4 in the hardening list): `lesson_author`, `entry_critic`,
`action_queue` (via the lesson pipeline), the first `learn` cycle,
the first restore-drill rehearsal, and `/critique` on a real entry.

**Why this second:** it's the cheapest way to flip six S-tier
items to P-tier in one observation. Without it, the lesson layer
and the entry critic remain synthetic-verified indefinitely.

### 3. Run `/brutalreviewai` once

Phase F could not run it from CLI. Chris opens Telegram, types
`/brutalreviewai`, copies the output into a new plan doc, and
compares against this ship report. Any novel findings get added
to the cohesion hardening list.

**Why this third:** the review loop has shipped but never been
used. The inaugural run IS the test that the command produces
useful output. If it does, weekly cadence is next. If it doesn't,
file a P0 and triage.

## Things the user should actively decide

- **Is `common/file_lock.py` (M2) the right shape for the
  cross-process write coordination?** Alternative is event-log
  reduction (`oil_botpattern_proposals.jsonl` becomes append-only;
  current state reconstructs from events). Event-log reduction is
  NORTH_STAR P9-aligned but bigger refactor.
- **Does the 2026-04-09 `oil_botpattern` adaptive WIP stay parked
  or get committed?** It's been sitting in the working tree
  untouched throughout this review. The next session either
  commits it, evolves it, or garbage-collects it.
- **Should the 5 Phase D P1-7/P1-8/P1-9/P1-10/P1-11 fixes (small
  restart-state persistence items) be batched into one "chore:
  restart-state discipline" commit or shipped individually?** They
  share the pattern; batching is cheaper but harder to revert.
- **Does GOLD + SILVER thesis refresh happen now or park?** Both
  are stale, conviction auto-clamps them (safe), but MASTER_PLAN
  Open Questions still lists them as live.
- **Guardian re-enable?** Default answer is no. Ask explicitly if
  the answer changes.
- **Implementation wedges for VAULT_AS_AUDITOR.md — should any of
  the 6 wedges be promoted to P1 / Phase D items, or kept as a
  separate follow-up track?** Recommendation: keep separate; do
  Wedges 1+2 (untested + kill_switches) first because they catch
  regressions in the Phase D fixes automatically.

## What did NOT happen this session

Explicit list of scope items that were deferred:

- **`/brutalreviewai` not run** — Telegram-only. Handed back to
  Chris.
- **Phase D P0s not fixed** — findings only per plan design; the
  fixes are the NEXT session's work.
- **`data/config/.claude/settings.json` not committed** — it's
  gitignored and a prior-session local file. Never was in scope.
- **Guardian NOT re-enabled** — explicit user demand. All three
  hooks permanently gutted. Five tests deleted.
- **Adaptive-evaluator WIP untouched** — the working tree still
  contains modifications to `tiers.py`, `oil_botpattern.py`,
  `market_structure_iter.py`, associated tests, and runtime state
  files. Per review plan §1.8 / §11.3, these belong to a separate
  workstream.
- **Vault health pages NOT implemented** — only the proposal.
  Implementation is a follow-up track.
- **`agent/AGENT.md` NOT edited** — frozen without per-change
  sign-off (AUDIT_FIX_PLAN constraint). Phase A explicitly
  skipped it.
- **Per-commit detail NOT added to NORTH_STAR** — Phase A rule
  said light touch on NORTH_STAR; that's MASTER_PLAN's job.
- **Hard-coded counts remain in NORTH_STAR's "What to do next"
  list** — the plan said don't rewrite vision docs for per-commit
  drift; the list is somewhat stale but was explicitly out of
  scope.

## Test suite state

**Final state:** 3,181 tests passed, 0 failed. Verified immediately
after Phase 0 (commit `a9cc94e`). No Phase A–E change touched
source code except the Guardian hook gut, the `sweep.py` stale
marker, and five deleted guardian tests. The suite is green at
HEAD of Phase F.

## The lesson from the review

Three sessions in 2026-04-07 and 2026-04-09 lost time to stale
session state. The 2026-04-09 morning rewrote NORTH_STAR.md
without reading git history. The 2026-04-09 afternoon shipped 60+
commits without an alignment pass in the middle. The 2026-04-09
evening shut Guardian off because it was looping + re-emitting
stale narrative about those same 60+ commits.

This Phase A–F review is the first time the project has formally
stopped to classify a shipping burst. The SYSTEM_REVIEW_HARDENING_PLAN
is the enforcement mechanism: when the build-log entry has
sub-headings for "today's ships" that exceed the 1-page mental
limit, stop and run the review.

**NORTH_STAR P8 ("honest feedback over comfortable consensus")
says this should happen. This is the first time it has.**

## Links

- [SYSTEM_REVIEW_HARDENING_PLAN.md](SYSTEM_REVIEW_HARDENING_PLAN.md) — the parent plan
- [BATTLE_TEST_LEDGER.md](BATTLE_TEST_LEDGER.md) — Phase B output
- [TIMER_LOOP_AUDIT.md](TIMER_LOOP_AUDIT.md) — Phase C output
- [COHESION_HARDENING_LIST.md](COHESION_HARDENING_LIST.md) — Phase D output (the backlog)
- [VAULT_AS_AUDITOR.md](VAULT_AS_AUDITOR.md) — Phase E output (proposal)
- `docs/vault/runbooks/Drift-Detection.md` — the protocol
- `docs/vault/architecture/Cohesion-Map.md` — parallel-writer matrix
- `docs/vault/architecture/Time-Loop-Interweaving.md` — signal-chain catalog
- [MASTER_PLAN.md](MASTER_PLAN.md) — current living plan (updated in Phase A)
- [NORTH_STAR.md](NORTH_STAR.md) — vision (lightly touched in Phase A)
- `docs/wiki/build-log.md` — append-only history (entry at top from Phase A)
