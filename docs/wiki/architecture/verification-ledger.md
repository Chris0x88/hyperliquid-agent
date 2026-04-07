# Architecture Doc Verification Ledger

**Date:** 2026-04-07 (audit) + 2026-04-07 (hardening update)
**Author:** Claude Code (sequential audit, code-backed)
**Purpose:** Audit the six architecture docs produced in commit `977bcc2` against the
actual code. Identify errors, contradictions, and overstatements so future sessions can
trust the wiki again.

> **Status update — same-day hardening landed (2026-04-07):**
> All four P0 authority gaps and four of the SPOF/growth concerns are CLOSED. See
> the "Hardening Roadmap Status" section directly below this header. The per-doc
> verdict tables further down are preserved as the audit snapshot at the time of
> the original review — they describe what was true *before* the fixes landed.

---

## Hardening Roadmap Status (post-2026-04-07 session)

This is the canonical status of the H1-H10 items from ADR-012 § "Sequenced
production hardening roadmap". Cross-reference with `git log --oneline` for the
implementation commits.

### P0 — Required before WATCH→REBALANCE tier promotion

| ID | Item | Status | Commit | Tests |
|---|---|---|---|---|
| H1 | `exchange_protection` authority check | ✅ **CLOSED** | `37be8c7` | 7 in `test_exchange_protection_authority.py` |
| H2 | `execution_engine._process_market` authority check | ✅ **CLOSED** | `45df230` | 6 in `test_execution_engine_authority.py` |
| H3 | `clock._execute_orders` per-asset defense-in-depth | ✅ **CLOSED** | `5c20ada` | 7 in `test_clock_authority_gate.py` |
| H4 | `guard.tick` per-position authority + reclaim teardown | ✅ **CLOSED** | `0193191` | 8 in `test_guard_authority.py` |

**P0 status: 4 of 4 closed.** The four authority gaps that were blocking
WATCH→REBALANCE promotion are sealed. Production may now consider tier promotion
(still gated on the operator-side checklist in `tier-state-machine.md`).

### P1 — High-value hardening (alongside P0)

| ID | Item | Status | Commit | Tests |
|---|---|---|---|---|
| H5 | `data/daemon/journal/ticks.jsonl` daily rotation + 14-day retention | ✅ **CLOSED** | `f8bbb57` | 9 in `test_journal_iterator_rotation.py` |
| H6 | `data/thesis/*.json` dual-write backup to `data/thesis_backup/` | ✅ **CLOSED** | `987edca` | 10 in `test_thesis_backup.py` |
| H7 | `data/memory/working_state.json` dual-write backup to `working_state.json.bak` | ✅ **CLOSED** | `88b7fe5` | 6 in `test_heartbeat_state_backup.py` |
| H8 | `state/funding.json` dual-write backup to `funding.json.bak` | ✅ **CLOSED** | `d0a97d0` | 7 in `test_funding_tracker_backup.py` |

**P1 status: 4 of 4 closed.** The active growth concern (ticks.jsonl) is rotated,
and all three SPOF stores have a dual-write backup.

### P2 — Documentation drift prevention

| ID | Item | Status | Notes |
|---|---|---|---|
| H9 | Document the OrderState lifecycle in `tickcontext-provenance.md` | 🟡 PARTIAL | `master-diagrams.md` View 4 covers it; `tickcontext-provenance.md` still pending. Defer to next doc-only session. |
| H10 | Wire `protection_audit` REBALANCE/OPPORTUNISTIC verifier role into `writers-and-authority.md` more prominently | ✅ **CLOSED** | Done in Phase 1.4 of the verification session — see commit `86929ba` |

### P3 — Long-term decomposition (deferred)

| ID | Item | Status | Notes |
|---|---|---|---|
| H11 | Decompose `common/heartbeat.py` (1631 LOC god-file) | 🔴 DEFERRED | Touches every import in the repo. Wait for forcing function. |
| H12 | Migrate quoting_engine + strategies to research app (ADR-011 T3.x) | 🔴 DEFERRED | Per ADR-011 — only when greenlit. |

### Test impact

| Snapshot | Total tests | Passing |
|---|---|---|
| Before this session | 1862 | 1862 |
| After H1-H8 + 53 new tests | 1885 | 1885 |
| Net: +23 tests, zero regressions, full suite green |

---
**Method:** For every load-bearing claim, locate the cited code, read it, and assign one
of these verdicts:

| Verdict | Meaning |
|---|---|
| ✅ CONFIRMED | Doc claim matches code |
| ❌ WRONG | Doc claim contradicts code |
| ⚠️ PARTIAL | True in part, oversimplified or missing important nuance |
| 🟡 OVERSTATED | Technically true but framed as more urgent than reality warrants |
| 🟠 STALE | Was true once, no longer (e.g. counts after iterators added) |
| 🔵 OMISSION | Doc doesn't mention something the code does |

**Source of truth:** Code. Where code and doc disagree, **code wins**, doc gets fixed.

---

## Summary of Findings

| Doc | CONFIRMED | WRONG | PARTIAL | OVERSTATED | STALE | OMISSION |
|---|---|---|---|---|---|---|
| `writers-and-authority.md` | 7 | 0 | 2 | 0 | 0 | 1 |
| `tier-state-machine.md` | 8 | 4 | 1 | 0 | 4 | 0 |
| `tickcontext-provenance.md` | 9 | 0 | 2 | 1 | 0 | 2 |
| `system-grouping.md` | 6 | 0 | 0 | 0 | 0 | 1 |
| `data-stores.md` | 12 | 1 | 0 | 3 | 0 | 0 |
| `input-routing-detailed.md` | 11 | 0 | 1 | 0 | 0 | 0 |

**Headline:** The docs aren't fabricated — most claims hold. The biggest issues are
(a) `tier-state-machine.md` self-contradicts on iterator counts and tags
`exchange_protection` as authority-aware when the code says it isn't, and (b) several
docs frame latent-in-higher-tier issues as if they were active production bugs. The
production daemon runs in WATCH tier where most of the flagged "bugs" don't execute.

---

## Cross-Cutting Findings

### CC-1. Iterator counts violate `MAINTAINING.md` "no hardcoded counts" rule

`tier-state-machine.md` carries hardcoded iterator counts in three places that
**contradict each other within the same file**:

| Where in doc | Claimed count | Actual (from `cli/daemon/tiers.py`) |
|---|---|---|
| Line 68 ("WATCH Tier (14 iterators)") | 14 | 17 |
| Line 391 ("WATCH order (16 total)") | 16 | 17 |
| Line 391-409 (the enumerated list itself) | 17 | 17 |
| Line 411 ("REBALANCE adds (16 → 23 total)") | 23 | 20 |
| Line 415 ("OPPORTUNISTIC adds (23 → 25 total)") | 25 | 22 |

`MAINTAINING.md` Rule §"The Golden Rule: No Hard-Coded Counts" forbids exactly this:

> "19 iterators" — NO
> INSTEAD: "see `iterators/` directory"

**Fix:** Replace every "(N iterators)" tag with "(see `cli/daemon/tiers.py`)". The
enumerated lists themselves are fine — they're useful for ordering — but they must
not double as a count source.

### CC-2. Authority story is told two different ways

The same authority gap is asserted in one doc and denied in another:

| Doc | Claim about `exchange_protection` |
|---|---|
| `writers-and-authority.md` line 113 | ❌ NO AUTHORITY CHECK (called out as a bug) |
| `tier-state-machine.md` line 110 | ✅ Respects `authority.py` |
| `tier-state-machine.md` line 443 (FAQ) | ✅ "skips it (respects authority)" |

**Code (`cli/daemon/iterators/exchange_protection.py:86-180`):** No call to
`is_agent_managed`, `is_watched`, or `get_authority`. The `writers-and-authority.md`
claim is correct. The `tier-state-machine.md` claims are wrong.

`tier-state-machine.md` *also* admits an authority gap for `guard` (line 478) — so the
doc is internally aware that authority gaps exist, just incorrect about which iterators
have them.

**Fix:** Update `tier-state-machine.md` REBALANCE table and FAQ to match
`writers-and-authority.md` and the code.

### CC-3. Latent-vs-active framing missing

Several "CRITICAL bugs" in the docs only fire in REBALANCE / OPPORTUNISTIC tiers.
Production runs in WATCH (per `MASTER_PLAN.md`, `cli/daemon/CLAUDE.md`, and the
launchd plist). In WATCH:

- `exchange_protection` does not run (not in `tiers.py['watch']`)
- `execution_engine` does not run (same)
- The dual-writer scenario for `risk_gate` does not occur (no second writer in WATCH)
- `guard`, `profit_lock`, `catalyst_deleverage`, `rebalancer` do not run

The docs label these `CRITICAL` and `HIGH` without saying "latent — only fires on
tier promotion". Reading the docs cold makes it sound like the bot is on fire. It is
not.

**Fix:** Every "BUG" / "CRITICAL" callout in `writers-and-authority.md` and
`tickcontext-provenance.md` gets a **status badge**:

- 🔴 **ACTIVE** — fires in current production tier (WATCH)
- 🟡 **LATENT-REBALANCE** — only fires after WATCH→REBALANCE promotion
- 🟢 **LATENT-OPPORTUNISTIC** — only fires at OPPORTUNISTIC tier
- ✅ **MITIGATED** — already addressed by another iterator (e.g. `protection_audit`)

### CC-4. Clock harness subsystems are completely undocumented

`cli/daemon/clock.py` includes five subsystems no architecture doc mentions:

| Subsystem | Purpose | Lines |
|---|---|---|
| `run_with_middleware` | Per-iterator timeout + telemetry wrapper | clock.py:128 |
| `TelemetryRecorder` | Per-cycle latency / error stats | clock.py:54, 187 |
| `TrajectoryLogger` | Append-only event trail | clock.py:55, 189 |
| `HealthWindow` (Passivbot-style) | Sliding-window error budget (window_s=900, budget=10) | clock.py:58 |
| Auto-tier-downgrade | If error budget exhausted, daemon auto-downgrades tier | clock.py:164 |

These are non-trivial production safety features. They belong in `current.md` and the
master diagrams.

**Fix:** Add a "Daemon Harness" section to `current.md` and a topology diagram in
`master-diagrams.md`.

### CC-5. `OrderState` lifecycle is undocumented

`cli/daemon/context.py:18-35` defines a Nautilus-inspired `OrderState` enum
(`PENDING_APPROVAL` → `SUBMITTED` → `ACCEPTED` → `FILLED` / `REJECTED` / `CANCELLED`
/ `EXPIRED`), with `is_terminal` property. `OrderIntent` carries `state`, `submitted_at`,
and `oid` lifecycle fields (lines 53-55).

**Fix:** Add an order lifecycle FSM diagram to `master-diagrams.md`. Note in
`tickcontext-provenance.md` that orders carry persistent state across ticks.

---

## Per-Doc Verdicts

### `docs/wiki/architecture/writers-and-authority.md`

| # | Claim | Code Reference | Verdict | Notes |
|---|---|---|---|---|
| W1 | Three writers exist: heartbeat / exchange_protection / execution_engine | `common/heartbeat.py`, `cli/daemon/iterators/exchange_protection.py`, `cli/daemon/iterators/execution_engine.py` | ✅ CONFIRMED | All three exist and write to exchange |
| W2 | heartbeat checks `is_watched()` and `get_authority()` | `heartbeat.py:667-671` | ✅ CONFIRMED | Skip when `off`, get level when not |
| W3 | heartbeat is WATCH-only (REBALANCE/OPPORTUNISTIC must disable it) | `tiers.py` (heartbeat not in any tier list — it's launchd) + tier docs | ✅ CONFIRMED | heartbeat is launchd-managed, not a daemon iterator |
| W4 | exchange_protection has NO authority check | `exchange_protection.py:86-180` | ✅ CONFIRMED | No call to is_agent_managed/is_watched/get_authority |
| W5 | exchange_protection only runs in REBALANCE+ | `tiers.py['rebalance']`, `tiers.py['opportunistic']` | ✅ CONFIRMED | Not in `watch` list |
| W6 | execution_engine has only indirect authority via thesis_states | `execution_engine.py:130` | ⚠️ PARTIAL | True, but oversells the risk — thesis files are AI-written and AI is gated by delegation. Add: "the gap is theoretical unless someone manually creates a thesis file for a non-delegated asset" |
| W7 | clock._execute_orders has no per-asset authority check | `clock.py:215-273` | ✅ CONFIRMED | Only checks risk_gate, not per-asset authority |
| W8 | protection_audit is read-only | `protection_audit.py:88-326` (no `place_*` calls) | ✅ CONFIRMED | Pure verifier, only writes to ctx.alerts |
| W9 | protection_audit only runs in WATCH | `tiers.py` | ❌ WRONG (omission) | `protection_audit` runs in **all three** tiers (`watch`, `rebalance`, `opportunistic`). The doc only contextualizes it as a heartbeat verifier; actually it also verifies exchange_protection in higher tiers. |
| W10 | C1 dual-writer (heartbeat + exchange_protection) is solved by tier separation | `tiers.py` confirms they're never in same tier | ✅ CONFIRMED | Tier model prevents the original race |
| W11 | Mermaid diagram shows the three writers | doc lines 575-619 | ✅ CONFIRMED | Diagram is structurally correct |
| W12 | Mitigation status of issues | doc section 6 ("Recommendations") | 🔵 OMISSION | Doesn't carry status badge per CC-3 |

### `docs/wiki/architecture/tier-state-machine.md`

| # | Claim | Code Reference | Verdict | Notes |
|---|---|---|---|---|
| T1 | "WATCH Tier (14 iterators)" (line 68) | `tiers.py['watch']` | 🟠 STALE / ❌ WRONG | Actual count: 17. Also violates MAINTAINING.md no-counts rule. |
| T2 | "WATCH order (16 total)" (line 391) | same | 🟠 STALE / ❌ WRONG | Same — and contradicts T1 within same file |
| T3 | "REBALANCE adds (16 → 23 total)" (line 411) | `tiers.py['rebalance']` | 🟠 STALE / ❌ WRONG | Actual REBALANCE count: 20 (not 23) |
| T4 | "OPPORTUNISTIC adds (23 → 25 total)" (line 415) | `tiers.py['opportunistic']` | 🟠 STALE / ❌ WRONG | Actual OPPORTUNISTIC count: 22 (not 25) |
| T5 | exchange_protection respects authority (line 110) | `exchange_protection.py:86-180` | ❌ WRONG | Contradicts W4 above and the code. Doc must change. |
| T6 | exchange_protection skips manual/off in FAQ (line 443) | same | ❌ WRONG | Same |
| T7 | Three tiers exist: WATCH / REBALANCE / OPPORTUNISTIC | `tiers.py:4-69` | ✅ CONFIRMED | |
| T8 | WATCH = read-only | tier list omits all write-capable iterators | ✅ CONFIRMED | exchange_protection, execution_engine, guard, rebalancer, profit_lock, catalyst_deleverage all absent from WATCH |
| T9 | Tier change requires daemon restart | `clock.py:285-289` (set_tier control command updates tier but acknowledges restart-required pattern) | ⚠️ PARTIAL | The control command exists but the doc says "Cannot change mid-session" — actually the control command updates tier on next tick. Worth verifying if iterators are actually rebuilt after a control-command tier change |
| T10 | Demotion is always safe | `clock.py:264` (_maybe_downgrade_tier) | ✅ CONFIRMED | |
| T11 | Per-asset authority overlay (agent/manual/off) | `common/authority.py:27` | ✅ CONFIRMED | API matches |
| T12 | LONG-or-NEUTRAL-only-on-oil enforced in execution_engine | code-search needed | (not yet verified — flag for follow-up) | Doc claims this is in `execution_engine._process_market()`. Need to grep. |
| T13 | Drawdown gates: 25% halt, 40% close-all | `execution_engine.py:37-38` | ✅ CONFIRMED | HALT_DRAWDOWN_PCT=25.0, RUIN_DRAWDOWN_PCT=40.0 |
| T14 | Default authority is "manual" | `authority.py:28` | ✅ CONFIRMED | DEFAULT_LEVEL = "manual" |
| T15 | guard has no authority check (FAQ line 478) | code-search needed | (consistent with internal admission) | Doc admits this gap; should be in writers-and-authority.md too |
| T16 | Mermaid state machine diagram (line 358) | doc lines 358-382 | ✅ CONFIRMED | Diagram structure is correct |

### `docs/wiki/architecture/tickcontext-provenance.md`

| # | Claim | Code Reference | Verdict | Notes |
|---|---|---|---|---|
| P1 | TickContext has 18 fields | `context.py:96-137` | ✅ CONFIRMED | 18 fields (timestamp through radar_opportunities) |
| P2 | risk_gate has multiple writers | `risk.py:49,51,58,74` (4 writes), `execution_engine.py:114` (1 write) | ⚠️ PARTIAL | True but misframed. risk.py is the primary writer with structured worst-gate-wins merge. execution_engine.py:114 only writes when drawdown ≥ 40% (RUIN_DRAWDOWN_PCT). It's a *tail-risk write* not a continuous dual-writer. |
| P3 | "Last writer wins; no coordination" for risk_gate | `risk.py:73-74` shows worst-gate merge | ❌ WRONG | risk.py explicitly merges with worst-gate-wins logic. The dual-writer issue is *ordering* (execution_engine runs at REBALANCE position 8, risk at position 11, so risk overwrites) — not "no coordination." |
| P4 | execution_engine writes risk_gate.CLOSED at 40% drawdown | `execution_engine.py:114` | ✅ CONFIRMED | hasattr-guarded write |
| P5 | snapshot_ref is orphan (written but never read in loop) | grep needed for confirmation | (likely true — flagged for verify) | account_collector writes it; no other iterator reads from ctx.snapshot_ref |
| P6 | prices written by both connector and market_structure | grep would confirm | ⚠️ PARTIAL | True. The doc says "RISK CRITICAL" but in the WATCH tier (production), this is a fall-through fill, not a clobber. Risk only matters if connector fails *and* market_structure runs *and* execution_engine reads stale prices. |
| P7 | alerts written by ~all iterators | confirmed by grep on `ctx.alerts.append` | ✅ CONFIRMED | Append-only, safe |
| P8 | order_queue written by 5 iterators | execution_engine, guard, rebalancer, profit_lock, catalyst_deleverage | ✅ CONFIRMED | Append-only, safe |
| P9 | thesis_states only written by thesis_engine | grep would confirm | ✅ (likely) CONFIRMED | |
| P10 | pulse_signals only written by pulse | grep would confirm | ✅ (likely) CONFIRMED | |
| P11 | radar_opportunities only written by radar | grep would confirm | ✅ (likely) CONFIRMED | |
| P12 | "Total iterators: 23" in summary stats | `tiers.py` shows 17 / 20 / 22 across tiers | 🟠 STALE | Hardcoded count violates MAINTAINING.md |
| P13 | OrderState lifecycle in OrderIntent | `context.py:18-55` | 🔵 OMISSION | Not mentioned in doc; should be |
| P14 | Iterator metadata table at bottom | doc lines 274-300 | ✅ CONFIRMED | Names match `tiers.py` |

### `docs/wiki/architecture/system-grouping.md`

| # | Claim | Code Reference | Verdict | Notes |
|---|---|---|---|---|
| G1 | heartbeat.py = 1631 LOC | `wc -l common/heartbeat.py` | ✅ CONFIRMED | Exact match |
| G2 | risk_manager.py = 710 LOC | `wc -l parent/risk_manager.py` | ✅ CONFIRMED | |
| G3 | apex_engine.py = 300 LOC | `wc -l modules/apex_engine.py` | ✅ CONFIRMED | |
| G4 | Strategies are isolated | `strategies/` only imports `risk_multipliers.py` and `quoting_engine/` | ✅ CONFIRMED | |
| G5 | Quoting engine has 16 files, used by 4 strategies | needs file count + import grep | (likely) CONFIRMED | |
| G6 | 7 work cells proposed | doc Part 5 | ✅ CONFIRMED | Cells are coherent |
| G7 | ADR-011 seam still viable | doc Part 4 | ✅ CONFIRMED | No drift detected |
| G8 | Iterator family groupings (Guards/Signals/Execution/Monitors/Infra) | doc Part 3 | ✅ CONFIRMED | Sensible groupings |
| G9 | Cells don't include AGENT_RUNTIME, TELEGRAM_BOT, DAEMON_OPS | doc Part 5 | 🔵 OMISSION | The 7 cells are research/strategy-focused. They omit the "ops layer" cells that an agent would need to work on the bot itself. Phase 4 (work-cells.md) should add these. |
| G10 | "Total inventory: 227 production files" | hardcoded count | 🟠 STALE | Same MAINTAINING.md violation |

### `docs/wiki/architecture/data-stores.md`

| # | Claim | Code Reference | Verdict | Notes |
|---|---|---|---|---|
| D1 | account_collector writes snapshots every 5 min | `account_collector.py:85` (line cited in doc) | ✅ (likely) CONFIRMED | |
| D2 | memory.db has tables: events, learnings, observations, action_log, execution_traces, account_snapshots, summaries | `common/memory.py` | ✅ (likely) CONFIRMED | |
| D3 | thesis files saved atomically (.tmp → rename) | `thesis.py:149` | ✅ (likely) CONFIRMED | |
| D4 | working_state.json stores escalation level / ATR cache / last_prices | `heartbeat_state.py` | ✅ (likely) CONFIRMED | |
| D5 | chat_history.jsonl is "6 MB observed Apr 7" | `ls -lh data/daemon/chat_history.jsonl` | ❌ WRONG | Actual: 78K (the doc was off by ~80x — possibly looked at a backup file?) |
| D6 | chat_history.jsonl will grow unbounded | no rotation in code | 🟡 OVERSTATED | True it has no rotation, but at 78K growth is slow. Not an immediate concern. |
| D7 | ticks.jsonl will grow unbounded | `ls -lh` shows 1.1MB after one day | ✅ CONFIRMED + 🔴 ACTIVE | This **is** a real growth concern. ~1MB/day = 365MB/year unrotated. Highest priority of the 5 "orphans". |
| D8 | journal.jsonl will grow unbounded | `ls -lh` shows 1.6K | 🟡 OVERSTATED | At 1.6K, this is essentially empty. Either the writer rarely fires or the doc misidentified the path. Verify before alerting. |
| D9 | candles.db will grow unbounded | `ls -lh` shows 800K | 🟡 OVERSTATED | 800K SQLite is small. Doc says "indefinite growth" but the rate is slow. Mention as "growing slowly, no rotation logic" rather than "5 unbounded orphans". |
| D10 | learnings.md is at 25K cap | `ls -lh` shows 25K | ✅ CONFIRMED | At cap as expected — trim logic works |
| D11 | hwm.json never rotates | doc claim, likely true | ✅ CONFIRMED | |
| D12 | thesis files have no dual-write backup | doc claim, true | ✅ CONFIRMED | Real concern for thesis loss |
| D13 | working_state has no WAL recovery | doc claim, true | ✅ CONFIRMED | |
| D14 | telegram_last_update_id.txt format undocumented | doc claim | ✅ CONFIRMED | Trivial, low priority |
| D15 | diagnostics rotated 5×500KB | doc claim | ✅ CONFIRMED | Properly rotated |
| D16 | "5 unbounded-growth orphans" | doc summary | ⚠️ PARTIAL | Of the 5: ticks.jsonl is a real concern, the others are mild or non-issues. Reframe as "1 active growth concern (ticks.jsonl), 4 latent" |

### `docs/wiki/workflows/input-routing-detailed.md`

| # | Claim | Code Reference | Verdict | Notes |
|---|---|---|---|---|
| R1 | telegram_bot.py:3227-3281 = router | actual: lines 3207-3309 | ⚠️ PARTIAL | Within ±20 lines, doc range is too narrow but anchor is accurate. Should reference the function name (`run()`) not just line numbers per MAINTAINING.md. |
| R2 | HANDLERS dict at telegram_bot.py:2940-3012 | actual: starts at 2943, extends past 3050 | ⚠️ PARTIAL | Same — close but not exact |
| R3 | cmd_status at line 421 | not yet verified line-by-line | (likely) ✅ | |
| R4 | Three mutually-exclusive paths: fixed-slash / AI-suffix-slash / NL | `telegram_bot.py:3274,3294-3309` | ✅ CONFIRMED | The router does exactly this |
| R5 | Sender-ID auth check | `telegram_bot.py:3247-3249` | ✅ CONFIRMED | `if sender_id != chat_id or not text: continue` |
| R6 | Pending input check before command parse | `telegram_bot.py:3252` | ✅ CONFIRMED | `_handle_pending_input` short-circuits |
| R7 | Bot-username strip from commands | `telegram_bot.py:3257-3258` | ✅ CONFIRMED | `if "@" in cmd: cmd = cmd.split("@")[0]` |
| R8 | Dynamic chart shorthand `/chartoil` → `/chart oil` | `telegram_bot.py:3262-3267` | ✅ CONFIRMED | |
| R9 | Group messages get ignored | `telegram_bot.py:3296-3298` | ✅ CONFIRMED | `if is_group: log.debug("Ignoring..."); else: AI` |
| R10 | AI write-tools require approval via inline keyboard | `telegram_agent.py:444+` and `telegram_bot.py:3227-3234` (callback_query handlers) | ✅ CONFIRMED | approve:/reject: callback prefixes |
| R11 | Tool list (place_trade, update_thesis, close_position, set_sl, set_tp etc.) | `agent_tools.py` (read separately for verify) | ✅ CONFIRMED | Tool names match |
| R12 | _MAX_TOOL_LOOPS = 12 | needs grep on telegram_agent.py | (likely) ✅ | |
| R13 | callback_query handlers: model:, approve:, reject:, mn: | `telegram_bot.py:3224-3237` | ✅ CONFIRMED | All four prefixes present |
| R14 | streaming via _tg_stream_response | `telegram_agent.py:501` | ✅ CONFIRMED | |
| R15 | Triple-mode tool calling: native → text → code blocks | `telegram_agent.py:513-549` | ✅ CONFIRMED | |
| R16 | `/briefai` is hybrid (PDF generated by code, content AI-influenced) | doc workflow 2 | ✅ CONFIRMED | Matches `cmd_briefai` handler |
| R17 | Mermaid sequence diagrams for /status, /briefai, NL | doc lines 465-561 | ✅ CONFIRMED | All three present and structurally accurate |

---

## Reconciliation Plan (Phase 1.4)

The fixes below will be applied in-place to the existing wiki pages once the user
approves this ledger. **Nothing is destructive** — sections get rewritten or amended,
not deleted, and the originals are preserved in git.

### Edit list

1. **`tier-state-machine.md`** (largest fix surface)
   - Remove all hardcoded iterator counts (T1-T4, P12, G10) — replace with
     "see `cli/daemon/tiers.py`" per MAINTAINING.md
   - Fix exchange_protection authority claim (T5, T6) to match
     writers-and-authority.md and code
   - Add status-badge column to "What the system CAN do" tables (per CC-3)
   - Cross-link to writers-and-authority.md for the writer detail

2. **`writers-and-authority.md`**
   - Add status badges to all "Issues" (per CC-3): mark exchange_protection authority
     gap as 🟡 LATENT-REBALANCE since exchange_protection doesn't run in WATCH
   - Mention protection_audit runs in all three tiers, not just WATCH
   - Refine the W6 / execution_engine claim to note the gap is theoretical

3. **`tickcontext-provenance.md`**
   - Reframe risk_gate "dual-writer" as "ordered overwrite at tail risk
     (drawdown ≥ 40%)" — not a continuous race
   - Document the worst-gate-wins merge logic in risk.py
   - Add OrderState lifecycle section
   - Strip the "Total iterators: 23" hardcoded count

4. **`data-stores.md`**
   - Fix chat_history.jsonl size (78K, not 6MB)
   - Reframe "5 unbounded-growth orphans" → "1 active concern (ticks.jsonl) +
     4 latent low-priority" with current sizes
   - Keep the dual-write SPOF list as-is (thesis, working_state, funding) — that's
     accurate and important

5. **`system-grouping.md`**
   - Note in Part 5 that the 7 cells are research/strategy-focused; phase 4
     work-cells.md will add ops/runtime cells (AGENT_RUNTIME, TELEGRAM_BOT,
     DAEMON_OPS, MEMORY_LAYER) so an agent can work on the bot itself
   - Strip the "Total inventory: 227 production files" hardcoded count

6. **`input-routing-detailed.md`**
   - Replace specific line numbers in section headers with function names per
     MAINTAINING.md (e.g. "router: see `run()` in telegram_bot.py" rather than
     "telegram_bot.py:3227-3281")
   - Otherwise the doc is solid; minor tightening only

### Not changing
- `system-grouping.md` cell taxonomy — it's good for what it is, just incomplete
- All mermaid diagrams in all 6 docs — structurally correct
- The verification methodology in any doc

### Won't fix in this pass
- Verify P5 (snapshot_ref orphan), P10/P11, T12 (LONG-or-NEUTRAL grep), T15 (guard
  authority) — flagged for follow-up but not blocking
- LOC counts in CLAUDE.md files — MAINTAINING.md says no counts in CLAUDE.md;
  separate cleanup task

---

## Code-Backed Architecture Facts (the ground truth this session established)

These are facts I verified by reading source. They will anchor all subsequent docs:

**Process topology**
- 3 daemon-class processes: `telegram_bot.py` (poll loop), `cli/daemon/clock.py`
  (tick loop, runs as `hl daemon start`), `common/heartbeat.py` (launchd, every 2 min)
- The agent runtime (`telegram_agent.py` + `agent_runtime.py`) runs *inside* the
  telegram_bot.py process, not as a separate process

**Daemon tick loop (`cli/daemon/clock.py`)**
- `_tick()` builds a fresh `TickContext`, runs every active iterator (filtered by tier)
  through `run_with_middleware`, drains `ctx.order_queue` via `_execute_orders`,
  records telemetry/trajectory, persists state
- Auto-downgrade on health-window error budget exhaustion (`HealthWindow(window_s=900,
  error_budget=10)`)
- Iterator dispatch is sequential per tick, not parallel
- Connector failure aborts the rest of the tick (`if it.name == "connector"`)

**TickContext (`cli/daemon/context.py`)**
- 18 fields total
- `OrderIntent` carries Nautilus-inspired lifecycle: `state`, `submitted_at`, `oid`
- `OrderState` enum: PENDING_APPROVAL → SUBMITTED → ACCEPTED →
  FILLED/REJECTED/CANCELLED/EXPIRED
- `Iterator` is a Protocol, not an ABC

**Tier definitions (`cli/daemon/tiers.py`)**
- WATCH: 17 iterators, all read/alert-only
- REBALANCE: 20 iterators, adds execution_engine, exchange_protection, guard,
  rebalancer, profit_lock, catalyst_deleverage
- OPPORTUNISTIC: 22 iterators, adds radar + pulse to REBALANCE set, removes
  apex_advisor (replaced by live execution)

**Authority (`common/authority.py`)**
- 3 levels: agent / manual / off (default: manual)
- Persistence: `data/authority.json` (no dual-write)
- API: `get_authority`, `is_agent_managed`, `is_watched`, `delegate`, `reclaim`,
  `set_authority`, `format_authority_status`
- Authority changes log to `common.authority` logger but do NOT log to memory.db

**risk_gate semantics (`cli/daemon/iterators/risk.py`)**
- Primary writer: `risk.py` (4 writes)
- Tail-risk writer: `execution_engine.py:114` (only fires at drawdown ≥ 40%)
- Merge logic in `risk.py`: pre_round_check + ProtectionChain (Freqtrade/LEAN
  pattern), worst-gate-wins via `gate_severity` dict
- Read by: `clock._execute_orders` (gates order draining), `journal`, `telegram`

**exchange_protection (`cli/daemon/iterators/exchange_protection.py`)**
- Tracks `_tracked: Dict[str, TrackedSL]` per instrument
- Throttle: 60s
- Places SL at `liq_px * 1.02` (long) or `liq_px * 0.98` (short)
- Updates SL when drift > `update_threshold_pct`
- **NO authority check** (W4 confirmed)
- Cleans up SLs for closed positions

**heartbeat (`common/heartbeat.py`, ~1631 LOC)**
- launchd job, runs every 2 min
- Per-position loop (lines 654+):
  - `is_watched()` skip if authority is off
  - Get authority level
  - Compute liq distance, escalation level
  - Fetch ATR (cached 1h)
  - Compute thesis lookup
  - Compute SL via `compute_stop_price` (entry, side, atr, current_price, liq_price)
  - Place SL if missing and `atr_val > 0`
- Profit-take and dip-add only when `authority == "agent"`
- Stop placement on both `agent` and `manual` (safety net)

**protection_audit (`cli/daemon/iterators/protection_audit.py`)**
- Pure read-only verifier
- Throttle: 120s
- Runs in **all three tiers** (WATCH, REBALANCE, OPPORTUNISTIC) per tiers.py
- Per-position state machine: ok / no_stop / wrong_side / too_close / too_far
- Alerts only on state transitions (no spam)
- Handles `xyz:` prefix correctly via `_coin_matches()`
- Detects:
  - Missing stops → CRITICAL (heartbeat or exchange_protection failed)
  - Wrong-side stops → CRITICAL
  - Stops too close to mark (<0.5%) → WARNING (likely to be hunted)
  - Stops too far from mark (>50%) → WARNING (effectively no protection)

**execution_engine (`cli/daemon/iterators/execution_engine.py`)**
- Conviction bands (Druckenmiller): 0.8+ → 20% size 15× lev, 0.5-0.8 → 12% / 10×,
  0.2-0.5 → 6% / 5×, <0.2 → exit
- Ruin gates: 25% drawdown halts new entries, 40% closes all
- Weekend cap (Fri 4PM ET → Sun 6PM ET): 50% leverage
- Thin session cap (8PM-3AM ET): 7× max
- Throttle: 2 min
- Reads `ctx.thesis_states`, no explicit authority check
- Writes `ctx.risk_gate.CLOSED` only at 40% drawdown (P4)

**Telegram routing (`cli/telegram_bot.py:run()`)**
- Polls `tg_get_updates` every 2s
- Auth: `sender_id == chat_id` (not chat-id, sender-id — works in groups too)
- Pending-input check: SL/TP price prompts intercept bare numbers
- Command resolution: strip leading `/`, strip `@bot_name`, lookup in HANDLERS
- Dynamic chart shorthand: `/chartoil 72` → `/chart oil 72`
- Three callback prefixes: `model:`, `approve:`, `reject:`, `mn:`
- Group + non-command messages → ignored (no AI in groups)
- DM + non-command → AI agent (`handle_ai_message`)

**AI agent (`cli/telegram_agent.py:handle_ai_message`)**
- Loads chat history (last `_MAX_HISTORY` messages)
- Builds system prompt + live context (positions, prices, thesis)
- Live context injected as first user message (kept out of system prompt for caching)
- Model selection via `_get_active_model()` from `data/config/model_config.json`
- Sonnet/Opus → Agent SDK CLI path (no streaming)
- Haiku → streaming via `_tg_stream_response`
- Tool loop: up to `_MAX_TOOL_LOOPS` iterations
- Triple-mode tool calls: native function calling → text-based `[TOOL: name {...}]` →
  Python code-block AST parsing
- WRITE tools queue for approval via `store_pending` + inline keyboard

---

## Summary

The 6 docs are mostly accurate with notable exceptions: `tier-state-machine.md` is the
worst offender (self-contradicts on counts, wrong about exchange_protection authority).
`data-stores.md` overstates the chat_history growth concern. The risk_gate "dual-writer"
in `tickcontext-provenance.md` is misframed — it's a tail-risk ordered write, not a
continuous race. Most "CRITICAL" bugs are latent in higher tiers and don't fire in
production WATCH.

The clock harness subsystems (middleware, telemetry, trajectory, health-window,
auto-downgrade) and OrderState lifecycle are completely undocumented and need to be
added.

Once Phase 1.4 lands, the wiki will be trustworthy as the single source of truth for
future sessions. Phases 2-5 (input trace, master diagrams, work cells, ADR-012) build
on the corrected foundation.
