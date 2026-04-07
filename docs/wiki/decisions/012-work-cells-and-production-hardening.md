# ADR-012: Work-Cell Architecture and Production Hardening Roadmap

**Date:** 2026-04-07
**Status:** Accepted
**Supersedes:** None
**Related:** ADR-011 (Two-App Architecture — research sibling), `verification-ledger.md`,
`work-cells.md`, `master-diagrams.md`, `telegram-input-trace.md`

## Context

The 2026-04-07 architecture-mapping session (commit `977bcc2`) produced six wiki
documents that, on subsequent verification, were found to contradict each other on
several load-bearing facts and to misframe latent issues as active production bugs.
The most damaging examples:

- `tier-state-machine.md` carried iterator counts that contradicted themselves three
  times within the same file (14, then 16, then 17 — actual is 17 per
  `cli/daemon/tiers.py`).
- `tier-state-machine.md` claimed `exchange_protection` respects per-asset authority;
  the code (`cli/daemon/iterators/exchange_protection.py:86-180`) makes no
  authority calls at all. `writers-and-authority.md` correctly identified this gap
  but the two docs contradicted each other and one was wrong.
- `data-stores.md` claimed `chat_history.jsonl` was "6 MB observed Apr 7" — the
  actual file size on the same day was 78 KB.
- The `risk_gate` "dual-writer" was framed as "no coordination, last writer wins"
  when in reality `risk.py` uses a structured worst-gate-wins merge and
  `execution_engine.py:114` only writes at the catastrophic end of the drawdown
  curve (≥40%).
- The clock harness subsystems (`run_with_middleware`, `HealthWindow`,
  `TelemetryRecorder`, `TrajectoryLogger`, auto-tier-downgrade on error budget
  exhaustion) — five production-grade safety features in `cli/daemon/clock.py` —
  were not mentioned in any of the six docs.

The user's instinct that "the assessment work is not high quality" was correct.
The Phase 1 verification ledger (`verification-ledger.md`) records every claim
checked against code with a verdict, and Phase 1.4 patched all six docs in place
to match what the code actually does.

Beyond doc accuracy, two structural problems remained:

**Problem 1 — Single-agent context exhaustion.** The production layer of `agent-cli/`
is ~21K LOC across many files. A single agent session cannot productively load all
of it. Without explicit cell boundaries, agents either run out of working memory
mid-task or drift outside the task scope ("while I'm here let me also clean up X")
and introduce regressions.

**Problem 2 — No clear path to production hardening.** The verification ledger
identified four latent authority gaps (in `exchange_protection`, `execution_engine`,
`clock._execute_orders`, and `guard`), three single-point-of-failure stores
(thesis, working_state, funding), and one active growth concern (`ticks.jsonl`).
These gaps are dormant in production WATCH tier, but they block any future tier
promotion to REBALANCE/OPPORTUNISTIC. There was no sequenced plan to close them.

## Decision

This ADR adopts four interlocking decisions:

### Decision 1 — Work-cell taxonomy as the unit of parallel agent dispatch

The repo is now organized into:

- **9 production cells** (`docs/wiki/architecture/work-cells.md`):
  P1 TELEGRAM_BOT, P2 AGENT_RUNTIME, P3 DAEMON_HARNESS, P4 DAEMON_GUARDS,
  P5 DAEMON_SIGNALS, P6 DAEMON_EXECUTION, P7 HEARTBEAT_PROCESS,
  P8 TRADING_PRIMITIVES, P9 MEMORY_AND_KNOWLEDGE.
- **7 research cells** (`docs/wiki/architecture/system-grouping.md`):
  GUARD_FRAMEWORK, SIGNAL_SOURCES, STRATEGIES_ADAPTATION, EXECUTION_MECHANICS,
  MARKET_DATA_INGESTION, APEX_STACKING, REPORTING_REFLECTION.

Each production cell carries: purpose, files included, LOC budget, external read /
write interfaces, freeze list (files the cell agent must not modify), test surface,
safe operations, risky operations needing confirmation, common task examples,
and dependencies on other cells.

**Cell boundaries are socially enforced**, not technically enforced. Agents must
respect freeze lists; pre-commit hooks and PR review are the safety net. Production
cells and research cells are complementary — production cells care about runtime
safety, research cells care about backtest accuracy and adapter portability.

### Decision 2 — Status-badge convention for issue urgency

All architecture docs (and all future ones) use these status badges to describe
issue urgency:

| Badge | Meaning |
|---|---|
| 🔴 **ACTIVE** | Fires in current production tier (WATCH); behavior is what production sees today |
| 🟡 **LATENT-REBALANCE** | Only fires after WATCH→REBALANCE promotion; gap is dormant in production |
| 🟢 **LATENT-OPPORTUNISTIC** | Only fires at the highest tier; further away from production |
| ✅ **MITIGATED** | Already addressed by another iterator (e.g. `protection_audit` covers exchange_protection failures via verification) |

This eliminates the framing problem where a doc labels something "CRITICAL" without
saying "this only matters if you promote tiers". A reader should be able to scan a
doc's headers and immediately know what's on fire (red), what's a tier-promotion
gate (yellow), and what's safely contained (green/check).

### Decision 3 — Verification ledger pattern as the standard for architectural assessment

Future architecture work follows the verification-ledger pattern:

1. Read the prior wiki claim
2. Locate the cited code
3. Verify the claim against the code
4. Assign a verdict (CONFIRMED / WRONG / PARTIAL / OVERSTATED / STALE / OMISSION)
5. Record the verdict in a ledger
6. Apply minimal-diff fixes to the wiki in place
7. Commit the ledger and the fixes together

This pattern is now canonical for any agent doing architecture review. The 2026-04-07
verification ledger is the reference example.

### Decision 4 — Sequenced production hardening roadmap

The four latent authority gaps and the SPOF/growth issues from the verification
ledger are sequenced into priority tiers:

#### P0 — Required before WATCH→REBALANCE tier promotion

| # | Fix | Cell | Risk if not done |
|---|---|---|---|
| H1 | Add `is_agent_managed()` check in `exchange_protection._protect_position` | P4 DAEMON_GUARDS | `manual` and `off` assets get ruin SLs placed in REBALANCE |
| H2 | Add explicit `is_agent_managed()` check in `execution_engine._process_market` | P6 DAEMON_EXECUTION | A leaked thesis file for a non-delegated asset could cause an autonomous trade |
| H3 | Add per-asset authority check in `clock._execute_orders` (defense-in-depth) | P3 DAEMON_HARNESS | Backstop if H1/H2 leak through |
| H4 | Add `is_agent_managed()` check in `guard.tick` | P4 DAEMON_GUARDS | Trailing stops applied to manual positions |

#### P1 — High-value hardening (do alongside P0)

| # | Fix | Cell | Why |
|---|---|---|---|
| H5 | Add rotation logic for `data/daemon/journal/ticks.jsonl` | P6 DAEMON_EXECUTION | Active growth concern (~365MB/year unrotated, observed 1.1MB/day) |
| H6 | Add dual-write backup for `data/thesis/*.json` | P9 MEMORY_AND_KNOWLEDGE | Currently SPOF; thesis loss = AI/execution contract loss |
| H7 | Add dual-write backup for `data/memory/working_state.json` | P7 HEARTBEAT_PROCESS | Currently SPOF; loss = heartbeat escalation state lost |
| H8 | Add dual-write backup for `state/funding.json` | P5 DAEMON_SIGNALS | Currently SPOF; loss = funding history irrecoverable |

#### P2 — Documentation drift prevention

| # | Fix | Cell | Why |
|---|---|---|---|
| H9 | Document the OrderState lifecycle in tickcontext-provenance.md | P3 DAEMON_HARNESS | Already partially in `master-diagrams.md` View 4; tickcontext-provenance.md still needs the FSM section |
| H10 | Wire `protection_audit` REBALANCE/OPPORTUNISTIC verifier role into the writers-and-authority.md narrative more prominently | (no code change) | Doc-only |

#### P3 — Long-term decomposition (defer until forcing function)

| # | Item | Why deferred |
|---|---|---|
| H11 | Decompose `common/heartbeat.py` (1631 LOC god-file) into multiple modules | Touching every import in the repo. Defer until there's a clear win — e.g. heartbeat needs to share state with another iterator, or a refactor of the launchd integration |
| H12 | Migrate quoting_engine + strategies to research app (ADR-011 T3.x) | Per ADR-011 — only when Chris greenlights |

The H1-H10 list is the **production hardening roadmap**. It is not an audit fix
plan in the AUDIT_FIX_PLAN.md sense — those F1-F9 fixes are largely shipped. H1-H10
is a separate, smaller batch focused on the latent gaps the verification ledger
surfaced.

Each fix lands in its cell, with the cell agent following the cell's safe-ops /
risky-ops checklist. After all P0 fixes ship and pass smoke tests, the daemon is
eligible for promotion to REBALANCE (with the human transition-checklist gates
in `tier-state-machine.md`).

## Consequences

### Positive

1. **Wiki is trustworthy again.** After Phase 1.4 reconciliation, every claim in the
   six architecture docs has been verified against code. The verification ledger is
   the audit trail.
2. **Parallel agent dispatch has contracts.** The 9-cell production taxonomy plus
   the 7-cell research taxonomy gives agents a way to scope work without loading
   the whole repo. Cell freeze lists prevent drift.
3. **Production hardening is sequenced.** The H1-H10 priority list converts the
   latent-gap inventory into actionable, cell-scoped tasks. The order is explicit:
   P0 before tier promotion, P1 alongside P0, P2 anytime, P3 deferred.
4. **Status badges remove urgency confusion.** A reader can scan any architecture
   doc and immediately know which issues are dormant vs active. No more
   "CRITICAL!" headlines that turn out to be tier-promotion gates.
5. **Verification ledger pattern is reusable.** Any future architecture review can
   follow the same pattern: claim → code → verdict → minimal-diff fix.
6. **Clock harness is now visible.** The five wrapping subsystems
   (`run_with_middleware`, `_consecutive_failures`, `HealthWindow`,
   `TelemetryRecorder`, `TrajectoryLogger`, auto-tier-downgrade) are documented in
   `master-diagrams.md` View 5. New agents can rely on them without re-discovery.

### Negative / trade-offs

1. **Cell boundaries are social, not technical.** A misbehaved agent can still
   touch files outside its cell. The defense is review (PR or live), not the
   filesystem. Pre-commit hooks could enforce some of this in the future.
2. **The 9-cell taxonomy will need to evolve.** As the codebase grows, cells will
   need to be added, split, or merged. This ADR commits to **deprecating** cells
   rather than rewriting them — same pattern as iterators in `tiers.py`.
3. **The 4 P0 fixes block tier promotion.** Until H1-H4 land and pass smoke tests
   on testnet, the daemon stays in WATCH. This is the current production state, so
   the cost is "no autonomy gain" rather than "regression". Acceptable.
4. **Splitting `heartbeat.py` is deferred.** The 1631-LOC god-file remains a
   maintainability hazard. Decomposition is gated on a forcing function. Until
   then, agents working in P7 HEARTBEAT_PROCESS face higher cognitive load than
   agents in other cells.
5. **Research cells and production cells share files.** `apex_engine.py` lives in
   both APEX_STACKING (research) and DAEMON_SIGNALS (production). Two agents
   working on the same file from different cell perspectives could conflict.
   Mitigation: dispatch agents sequentially when they share files; check the
   git status before each.
6. **No automated test that validates cell boundaries.** Adding a `test_cell_freeze`
   that asserts cell-X agents only touched cell-X files would require commit-level
   instrumentation. Out of scope for this ADR.

### Neutral observations

- This ADR does not change any production code. It changes how future code changes
  are organized, scoped, and verified. The first concrete code changes will land
  via the H1-H10 fixes, each in its respective cell.
- ADR-011 (research-app split) is **not superseded** by this ADR. ADR-011 is the
  long-term decomposition target. ADR-012 is the medium-term organization that
  works *today* in the monolithic agent-cli/. When ADR-011 eventually ships, the
  9 production cells become the natural partition for what stays in agent-cli/ vs.
  moves to quant/.
- The 2026-04-07 hardening session (the C1' through C7 fixes plus F1-F9 audit
  fixes) is largely shipped per `MASTER_PLAN.md` and `AUDIT_FIX_PLAN.md`. ADR-012
  organizes the residual work, not the prior work.

## Compliance with MAINTAINING.md

This ADR contains:
- Zero hardcoded counts (LOC budgets in `work-cells.md` are approximations from
  `wc -l`, explicitly labeled as such, and the doc tells future agents not to
  update them — let alignment skill catch drift)
- No file-counting language ("X iterators", "Y commands")
- Cross-references to other docs by relative path

This ADR does **not** contain:
- Implementation details that belong in the wiki (those are in `work-cells.md`,
  `master-diagrams.md`, `verification-ledger.md`)
- Per-fix code patches (those land in commit history when the H1-H10 work happens)

## Next actions

The next agent session that picks up from this ADR should:

1. Read `verification-ledger.md` to understand what's true about the system.
2. Read `work-cells.md` to understand which cell their task fits in.
3. Read the relevant cell's section to load the right files and respect the freeze list.
4. Pick a P0 fix (H1-H4) and dispatch a cell-scoped agent to implement it.
5. Run the cell's test surface after each fix.
6. Smoke-test on testnet before committing.
7. Update the verification ledger if a fix changes the underlying code or
   surfaces new claims to verify.

The recommended starting point is **H1 (close exchange_protection authority gap in
P4 DAEMON_GUARDS)** because it's the highest-impact P0 fix and the cell is small
(~1.5K LOC writable plus ~700 LOC of risk_manager.py for context).
