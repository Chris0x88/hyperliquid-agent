# Build Log

Chronological record of architecture changes, incidents, and milestones. Most recent first.

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
