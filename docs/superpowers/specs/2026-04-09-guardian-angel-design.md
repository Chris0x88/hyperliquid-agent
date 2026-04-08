# Guardian Angel — Design Spec

**Date:** 2026-04-09
**Status:** Draft — awaiting user review before implementation planning
**Owner:** Chris
**Scope:** Dev-side meta-system for the HyperLiquid_Bot repo. Not a trading feature.

---

## 1. Purpose

Guardian Angel is a dev-side meta-system that watches the HyperLiquid_Bot repository while Claude Code is working in it, prevents architectural drift, and surfaces recurring user pain without requiring Chris to remember commands or read reports.

It solves six observed failure modes:

1. **Parallel tracks.** New work (e.g., a new memory module) is built without integrating with existing work, leaving two half-functional systems. Example currently in flight: memory addons.
2. **UI-completeness gap.** A feature "ships" in code but never reaches Telegram, so Chris can't use it. CLAUDE.md already documents a Telegram command checklist; nothing enforces it.
3. **Recurring fights become invisible signals.** Chris cancels a system action (e.g., SL/TP auto-set) multiple times; nothing on the dev side notices the pattern and proposes a root-cause fix.
4. **Cannot see architectural connections.** The system is large. Chris wants a visual map of what connects to what, with room for human feedback on whether those connections are good.
5. **Orphaning during direction changes.** Scope creeps daily. Old good work gets left behind without being intentionally retired.
6. **Claude is reactive, not proactive.** Chris leads every insight; he wants Claude reading between the lines and surfacing suggestions.

Guardian addresses all six, but **only while a Claude Code session is active**. When Chris is not in a Claude Code session, Guardian sleeps.

## 2. Scope & Boundaries

### In scope

- Repository cartography (modules, data flow, Telegram commands, daemon iterators, plans, ADRs)
- Drift detection (orphans, parallel tracks, plan/code mismatch, wiki rot, Telegram completeness)
- Pre-tool-use review gate (blocks a small, high-value set of destructive or incomplete actions)
- Friction analysis over existing user logs (`data/feedback.jsonl`, `data/daemon/chat_history.jsonl`, telegram logs)
- Proactive synthesis into a natural-language report Claude reads silently at session start
- One human-readable guide documenting the system

### Explicitly out of scope (do not touch)

- Trading agent runtime (`cli/agent_runtime.py`)
- Agent prompts (`agent/AGENT.md`, `agent/SOUL.md`)
- Auth profiles (`~/.openclaw/agents/default/agent/auth-profiles.json`) and any `~/.openclaw/` config
- Daemon iterators (`cli/daemon/iterators/`) — Guardian never runs inside the trading loop
- Telegram bot — Guardian does not push to Telegram, does not read from Telegram, does not modify `cli/telegram_bot.py`
- Any runtime trading data paths (`data/thesis/`, `data/agent_memory/`, etc.) — read-only access only
- Scheduled tasks MCP / cron / external schedulers — Guardian runs only during active Claude Code sessions
- The existing `docs/wiki/`, `docs/plans/`, ADRs — only additive changes, nothing rewritten or deleted

### Audience

Guardian primarily serves **Claude-in-dev-sessions**. Chris is the secondary audience: he sees Guardian only through natural-language surfacing by Claude (one sentence at session start if a P0 finding exists, otherwise silent) and through an optional `/guide` slash command.

## 3. Architecture — Three Tiers

### Tier 1 — Silent Workers (pure Python, stdlib only, zero cost)

Deterministic, mechanical analysis. No tokens spent.

- `cartographer.py` — scans the repo, produces an inventory of files, imports, Telegram commands, daemon iterators, plan references, and ADR references
- `drift.py` — diffs two inventory snapshots, flags orphans, parallel tracks, plan/code mismatches, Telegram completeness gaps, wiki rot
- `friction.py` — reads `data/feedback.jsonl`, `data/daemon/chat_history.jsonl`, git log, and any telegram log files; surfaces repeated-action patterns and recurring error signatures
- `gate.py` — check logic consumed by the PreToolUse hook; fast, single-file, returns allow/block + reason

### Tier 2 — Background Sub-Agents (dispatched via the Agent tool during active sessions)

Intelligent synthesis. Runs in parallel with the main session so Chris is never blocked.

- **`guardian-sweep`** — dispatched from the SessionStart hook (or mid-session on demand) with `run_in_background=true`. Executes the Tier 1 pipeline, reads the outputs, and writes a natural-language synthesis to `guardian/state/current_report.md`. Completes asynchronously.
- **`guardian-focused`** — dispatched mid-session when the conversation suggests a specific signal needs deeper analysis (e.g., Chris says "I've been fighting SL/TPs"). The sub-agent focuses on one dimension (friction, drift, or a specific module) and writes a targeted report.

Sub-agents are spawned via the existing `Agent` tool (general-purpose or Explore subagent type). They never piggyback on the trading agent.

### Tier 3 — Surface Point (SessionStart hook + Claude's judgment + the gate hook)

This is how findings reach Chris without polluting his attention.

- **SessionStart hook** — a stdlib-only Python script. At session start it:
  1. Reads `guardian/state/current_report.md` if present and recent
  2. Checks staleness: if the report is older than 24h OR more than 20 files have changed since the last snapshot, dispatches a background `guardian-sweep` sub-agent
  3. Injects the current report (compact form, <200 lines) into Claude's context via hook output

- **Claude's judgment** — I read the report silently. If a P0 finding exists (parallel track just created, orphan from recent work, recurring fight, UI gap on a recent command) I mention it in one sentence at the start of my first response. Otherwise I say nothing and we start working normally. Chris can ask me naturally ("what's guardian saying?") and I read the file on demand.

- **PreToolUse hook** — runs `gate.py` on every Edit/Write/Bash tool call. Fast (milliseconds), stdlib only. Blocks the specific, high-value set of rules documented in §4.4. When it blocks, it returns a clear error message explaining what's missing.

### Trigger model

**Trigger: B (SessionStart + mid-session on demand).**

- Every Claude Code session start fires the state loader hook.
- Mid-session, I can dispatch `guardian-focused` when the conversation indicates it would help.
- No Stop/SessionEnd hook in Phase 1 — deferred unless it proves necessary.
- No cron, no MCP scheduled tasks, no external schedulers.

## 4. Components in Detail

### 4.1 Cartographer (`guardian/cartographer.py`)

**Inputs:** repo root (resolved from `agent-cli/`).

**Scans:**
- Python files: AST-parse imports to build a module dependency graph
- `cli/telegram_bot.py`: regex-scan for `def cmd_*` handlers, the HANDLERS dict, `_set_telegram_commands()` list, `cmd_help()` and `cmd_guide()` content
- `cli/daemon/iterators/`: list iterator modules and their registration points
- `docs/plans/*.md`: extract file and function references (grep-style)
- `docs/wiki/decisions/*.md`: extract ADR numbers, statuses, referenced files
- `docs/wiki/components/*.md`: extract referenced files and functions

**Outputs:**
- `guardian/state/inventory.json` — structured wiring inventory
- `guardian/state/map.mmd` — Mermaid diagram of major components and their edges
- `guardian/state/map.md` — markdown wrapper with summary stats (module count, orphan candidates, Telegram command count, iterator count)

**Run time target:** <5 seconds on the current repo. Pure Python, stdlib only (`ast`, `pathlib`, `re`, `json`).

**Kill switch:** env var `GUARDIAN_CARTOGRAPHER_ENABLED=0`.

### 4.2 Drift Detector (`guardian/drift.py`)

**Inputs:** `inventory.json` (current) and `inventory.prev.json` (previous snapshot).

**Detects:**
- **Orphans** — Python modules with zero inbound imports that are not an entrypoint (no `if __name__ == "__main__"`, not in a known entrypoint list)
- **Parallel tracks** — modules whose filename or module docstring exceeds a similarity threshold with an existing module (heuristic: shared name tokens ≥ 60% AND both files modified within the last 14 days)
- **Plan/code mismatch** — references in `docs/plans/*.md` to files or functions that no longer exist in the inventory
- **Telegram gap** — `cmd_*` functions defined in `telegram_bot.py` but missing from any of: HANDLERS dict, `_set_telegram_commands()` list, `cmd_help()`, `cmd_guide()`
- **Wiki/code rot** — wiki pages referencing files or functions that no longer exist

**Outputs:**
- `guardian/state/drift_report.json` — structured findings
- `guardian/state/drift_report.md` — human-readable markdown, one section per category

**Severity tagging:** each finding is tagged `P0` (active problem requiring action), `P1` (suspected problem worth investigation), or `P2` (informational).

**Kill switch:** env var `GUARDIAN_DRIFT_ENABLED=0`.

### 4.3 Friction Surfacer (`guardian/friction.py`)

**Inputs (read-only):**
- `agent-cli/data/feedback.jsonl`
- `agent-cli/data/daemon/chat_history.jsonl`
- `agent-cli/data/telegram/*.jsonl` (if present)
- `git log --since="7 days ago" --stat`

**Detects patterns:**
- Same user correction repeated ≥ 3 times in 7 days
- Same error signature appearing ≥ 3 times in 7 days
- Command invocations that cluster tightly then stop (possible frustration → abandonment)
- Explicit frustration markers in feedback entries (simple keyword + tone heuristic, no AI required)

**Outputs:**
- `guardian/state/friction_report.json` — structured findings
- `guardian/state/friction_report.md` — human-readable markdown with example quotes

**Severity tagging:** same P0/P1/P2 scheme as drift.

**Kill switch:** env var `GUARDIAN_FRICTION_ENABLED=0`.

### 4.4 Review Gate (`guardian/gate.py` + `.claude/hooks/pre_tool_use.py`)

**PreToolUse hook** runs `gate.py` on Edit/Write/Bash tool calls.

**Rules (enabled one at a time during Phase 3, each with its own kill switch):**

| Rule | What it catches | Kill switch |
|---|---|---|
| `telegram-completeness` | Editing `telegram_bot.py` to add a `cmd_X` handler without corresponding entries in HANDLERS, `_set_telegram_commands()`, `cmd_help()`, `cmd_guide()` | `GUARDIAN_RULE_TELEGRAM_COMPLETENESS=0` |
| `parallel-track-warning` | Creating a new file whose name overlaps ≥ 60% with an existing recently-modified file | `GUARDIAN_RULE_PARALLEL_TRACK=0` |
| `recent-delete-guard` | Deleting (via Edit or Bash `rm`) a file created in the last 7 days | `GUARDIAN_RULE_RECENT_DELETE=0` |
| `stale-adr-guard` | Writing to `agent-cli/docs/wiki/decisions/` without having read `agent-cli/docs/plans/MASTER_PLAN.md` and `agent-cli/docs/plans/AUDIT_FIX_PLAN.md` in the current session (the 2026-04-07 postmortem rule) | `GUARDIAN_RULE_STALE_ADR=0` |

**Block behavior:** the hook returns an error to Claude with a clear message explaining what's missing and how to fix it. Claude then either fixes the gap and retries, or tells Chris and asks for a decision.

**Performance budget:** total gate check time < 100ms per tool call.

**Kill switch (global):** `GUARDIAN_GATE_ENABLED=0` disables all rules at once.

### 4.5 Advisor (spawned as a sub-agent, not a standalone Python module)

**Triggered:** by `guardian-sweep` after Tier 1 workers finish, only if new signals exist.

**Inputs:** `inventory.json`, `drift_report.md`, `friction_report.md`, plus the current MASTER_PLAN.md and the last 20 commits.

**Output:** `guardian/state/current_report.md` — a single markdown file containing:
1. One-paragraph summary of repo state
2. P0 findings (at most 3; if more, the top 3 by recency)
3. P1 findings (at most 5)
4. "Questions worth asking" — open items the sub-agent noticed that Chris might want to think about
5. Timestamp + what sources were read

**Budget:** sub-agent session targets ≤ 5000 tokens total. If the sub-agent exceeds this, the prompt truncates inputs and tries again.

### 4.6 Guide (`guardian/guide.md` + `.claude/commands/guide.md`)

**Purpose:** the contract between Chris and Guardian. If it's not in the guide, Guardian doesn't do it.

**Contents:**
- What Guardian is and is not
- When each component runs
- How to read `current_report.md` at a glance
- How to turn any component off (all kill switches in one table)
- How to extend Guardian (add a new drift rule, add a new friction pattern, add a new gate rule)
- Known limits and failure modes

**`/guide` slash command** reads `guardian/guide.md` and prints it to the terminal. This is the only slash command Guardian adds.

## 5. Placement

Everything lives inside `agent-cli/` so it is tracked by the git repo rooted there. Guardian is namespaced under `agent-cli/guardian/` to make clear it is a meta-tool sitting alongside the runtime code, not imported by it.

```
agent-cli/
  guardian/                            ← new Python package (stdlib only)
    __init__.py
    cartographer.py                    Component 4.1
    drift.py                           Component 4.2
    friction.py                        Component 4.3
    gate.py                            Component 4.4 (check logic)
    sweep.py                           Orchestrator — runs Tier 1 pipeline end-to-end
    guide.md                           Component 4.6 (the living contract)
    state/                             (gitignored)
      inventory.json
      inventory.prev.json
      drift_report.{json,md}
      friction_report.{json,md}
      current_report.md
      sweep.log
    tests/
      fixtures/                        tiny fake repos
      test_cartographer.py
      test_drift.py
      test_friction.py
      test_gate.py
      test_sweep.py

  .claude/
    commands/
      guide.md                         Component 4.6 (/guide slash command)
      guardian.md                      optional manual refresh (see Q3)
    hooks/
      session_start.py                 Tier 3 — loads state, dispatches sub-agent if stale
      pre_tool_use.py                  Tier 3 — runs gate.py checks
    settings.json                      wires the hooks (additive — does not replace existing)

  docs/
    plans/GUARDIAN_PLAN.md             phase status table (mirrors AUDIT_FIX_PLAN format)
    wiki/components/guardian.md        wiki page
    wiki/decisions/014-guardian-system.md  new ADR

  .gitignore                           add guardian/state/ entry
```

**Why inside `agent-cli/`?** The git repo is rooted there, so only paths under `agent-cli/` are committable. Guardian needs to live under version control so ADR-014 and GUARDIAN_PLAN.md can reference it. Placing the package at `agent-cli/guardian/` keeps it at the top of the git tree while remaining separate from the runtime code directories (`cli/`, `common/`, `modules/`, `parent/`, `agent/`).

## 6. Data Flow

```
Session start in Claude Code
   ↓
agent-cli/.claude/hooks/session_start.py runs (stdlib, <100ms)
   ├─ Reads agent-cli/guardian/state/current_report.md if present
   ├─ Checks staleness (mtime > 24h OR git diff shows >20 changed files since last snapshot)
   │    └─ if stale: dispatches `guardian-sweep` background sub-agent via the Agent tool
   │                 with subagent_type="general-purpose" and run_in_background=true
   └─ Outputs compact report summary into Claude's context

Claude reads the summary, surfaces P0 findings (if any) in one sentence, else silent
   ↓
Claude and Chris work normally
   ↓
On each Edit/Write/Bash call
   └─ agent-cli/.claude/hooks/pre_tool_use.py runs gate.py → allow or block
   ↓
Mid-session, if conversation suggests it
   └─ Claude dispatches `guardian-focused` background sub-agent for targeted analysis
      (subagent_type="general-purpose" or "Explore" depending on the focus)
   ↓
Background sub-agents finish asynchronously
   ├─ Each writes its report to agent-cli/guardian/state/
   └─ Claude picks up completion notifications and silently updates context
   ↓
Session ends — Guardian sleeps. Nothing runs until next session start.
```

## 7. Build Phases (Foundation-First)

Each phase is independently committable. If Chris stops liking Guardian at any point, he keeps what's already shipped and loses nothing.

| Phase | Ships | Components |
|---|---|---|
| **1 — Foundation** | Repo map + current-state awareness on session start. Chris can ask "what does guardian see?" and get a real answer. | `agent-cli/guardian/` scaffolding, `cartographer.py` (AST imports + Telegram scan + iterator scan), `sweep.py` orchestrator stub, SessionStart hook (read-only at first, no sub-agent dispatch yet), initial `guide.md` |
| **2 — Drift** | Orphan and parallel-track detection, Telegram completeness check. Surface-only — no blocking. | `drift.py`, drift section added to `current_report.md`, SessionStart hook starts including drift summary |
| **3 — Gate** | Hard enforcement of the four gate rules, one at a time. Each gets its own kill switch. | `gate.py`, PreToolUse hook, rules enabled incrementally (telegram-completeness first, then parallel-track-warning, then recent-delete-guard, then stale-adr-guard) |
| **4 — Friction** | "What Chris fought with this week" surfaced silently at session start. | `friction.py`, friction section added to `current_report.md` |
| **5 — Advisor + Background Sub-Agents** | Proactive synthesis. Sub-agents dispatched from SessionStart and mid-session. P0 surfacing via Claude's natural response. | `guardian-sweep` and `guardian-focused` sub-agent prompts, SessionStart hook dispatches sub-agent on staleness, mid-session dispatch logic |
| **6 — Guide lock-in + ADR + wiki page** | Documentation frozen, ADR-014 written, wiki page published, MASTER_PLAN link added. | `guide.md` finalized, `/guide` command polished, `014-guardian-system.md` ADR, `components/guardian.md` wiki page, MASTER_PLAN.md additive edit, `GUARDIAN_PLAN.md` status table |

**Phase sequencing rationale:** every phase either consumes outputs from an earlier phase (drift needs cartographer's inventory, gate needs drift's parallel-track detection, advisor needs all of them) or can be disabled independently (gate rules, friction). Nothing is irreversible.

## 8. Constraints & Kill Switches

### Hard constraints (from CLAUDE.md and user statements)

- **Zero external deps.** Python stdlib only. Mermaid renders natively in Claude Code, VSCode, GitHub — no graphviz install required.
- **Read-only on runtime data.** Guardian never writes to `data/thesis/`, `data/agent_memory/`, `data/feedback.jsonl`, or any path the daemon uses.
- **No `~/.openclaw/` touches.** Ever.
- **No trading agent modifications.** `cli/agent_runtime.py`, `agent/AGENT.md`, `agent/SOUL.md` are untouchable.
- **Never `git add -A`.** All Guardian commits add specific files by name.
- **Additive-only to existing docs.** MASTER_PLAN.md gets one new line. AUDIT_FIX_PLAN.md is untouched. Existing wiki pages are untouched except for cross-links.
- **Every component has a kill switch.** Documented in §8.2 below.

### 8.2 Kill switches table

| Scope | Env var | Effect |
|---|---|---|
| Global | `GUARDIAN_ENABLED=0` | Disables every hook, sub-agent, and slash command. Guardian becomes invisible. |
| Cartographer | `GUARDIAN_CARTOGRAPHER_ENABLED=0` | Skips cartography; downstream components use stale inventory. |
| Drift | `GUARDIAN_DRIFT_ENABLED=0` | Skips drift detection. |
| Friction | `GUARDIAN_FRICTION_ENABLED=0` | Skips friction analysis. |
| Gate (all rules) | `GUARDIAN_GATE_ENABLED=0` | PreToolUse hook becomes a no-op. |
| Gate rule — Telegram completeness | `GUARDIAN_RULE_TELEGRAM_COMPLETENESS=0` | — |
| Gate rule — Parallel track warning | `GUARDIAN_RULE_PARALLEL_TRACK=0` | — |
| Gate rule — Recent delete guard | `GUARDIAN_RULE_RECENT_DELETE=0` | — |
| Gate rule — Stale ADR guard | `GUARDIAN_RULE_STALE_ADR=0` | — |
| Background sub-agents | `GUARDIAN_SUBAGENTS_ENABLED=0` | SessionStart hook still runs Tier 1 (if enabled) but never dispatches sub-agents. |
| Hooks (at Claude Code level) | Remove entries from `.claude/settings.json` hooks section | Disables Guardian's integration with Claude Code without touching code. |

### 8.3 Failure modes

- **Cartographer crashes on a malformed Python file.** Caught by a single try/except in `sweep.py`; Guardian logs the failure to `state/sweep.log` and continues with a partial inventory.
- **Sub-agent times out or errors.** SessionStart hook proceeds with the stale report; Claude sees a "report is stale due to sub-agent failure" marker and either retries mid-session or tells Chris.
- **Hook raises an exception.** Wrapped in a top-level handler; the hook writes a one-line diagnostic to stderr and exits 0 so it never blocks Claude Code itself.
- **State directory gets corrupted.** `rm -rf guardian/state/` resets Guardian entirely. Next sweep rebuilds from scratch.
- **False positive in gate.py.** Every rule has a kill switch. Chris or Claude disables the offending rule in one env var and Guardian stops blocking.

## 9. Testing

- `agent-cli/guardian/tests/` with one test file per component.
- `agent-cli/guardian/tests/fixtures/` contains tiny fake repos used as golden inputs.
- No filesystem mocks — tests use real tmp directories.
- Golden-file tests for cartographer output (known repo → known inventory JSON).
- Unit tests for each drift rule, each friction pattern, each gate rule.
- Integration test for `sweep.py` end-to-end on a fixture repo.
- Follows the project rule: never modify test expectations to make tests pass — fix the source code.
- Runs as part of the existing test suite: `cd agent-cli && .venv/bin/python -m pytest tests/ guardian/tests/ -x -q`.

## 10. Integration with the Existing System

- **MASTER_PLAN.md** gets one additive line under "What's Next" pointing at `GUARDIAN_PLAN.md`.
- **AUDIT_FIX_PLAN.md** is untouched.
- **New** `docs/plans/GUARDIAN_PLAN.md` mirrors the `AUDIT_FIX_PLAN.md` status table format: phase, status, notes, commit hash.
- **New** `docs/wiki/decisions/014-guardian-system.md` — ADR covering the three-tier architecture, the in-session-only constraint, the sub-agent dispatch model, and why it is separate from the trading agent.
- **New** `docs/wiki/components/guardian.md` — wiki page following the same template as existing component pages.
- **`/alignment` command** — when Chris runs `/alignment`, the alignment skill reads `guardian/state/current_report.md` as one of its inputs so that alignment output reflects Guardian findings.
- **CLAUDE.md (root)** — gets one new bullet under "Workflow" pointing at Guardian and saying "Guardian runs automatically. Read `agent-cli/guardian/guide.md` for the contract."

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Guardian itself becomes a parallel track (meta-irony) | Phase 6 explicitly adds ADR-014, wiki page, MASTER_PLAN link. Guardian is legible to future Claudes. |
| Gate rules generate false positives and block legitimate work | Every rule has an individual kill switch. Phase 3 rolls out rules one at a time, with a week of observation between each. |
| Sub-agent dispatch costs more tokens than expected | Sub-agents are dispatched only when state is stale (mtime + file count heuristic). Budget cap of 5000 tokens per sub-agent run. Chris can disable with `GUARDIAN_SUBAGENTS_ENABLED=0`. |
| Friction analysis surfaces noise | Severity tagging + P0-only surfacing by Claude. Chris never sees P2 unless he asks. |
| Cartographer performance degrades as repo grows | Pure Python AST parsing; tested <5s on current repo. If repo doubles, still well under the 100ms hook budget (sub-agent does the heavy lifting, not the hook). |
| Guardian's state files get committed accidentally | `guardian/state/` added to `.gitignore` as part of Phase 1. |
| A change to the trading agent's agent runtime breaks Guardian | Guardian is read-only on runtime paths and has no imports from `cli/agent_runtime.py`. Zero coupling. |

## 12. Open Questions (resolve before writing the implementation plan)

- **Q1:** Does Chris want the SessionStart hook to surface findings in a structured output section, or should Claude surface them naturally in its first response? **Default: Claude surfaces naturally.**
- **Q2:** Should `guardian-sweep` read `git log --since="7 days ago"` for change context, or only compare inventory snapshots? **Default: both.**
- **Q3:** Should the `/guide` command be the only slash command, or should we add `/guardian` as a manual "run a sweep now" trigger for cases where Chris wants to force a refresh? **Default: add `/guardian` as a tiny escape hatch — costs nothing, documented in the guide, kill-switchable.**

---

## Appendix A — Visual references

Two diagrams produced during brainstorming are preserved in `.superpowers/brainstorm/` (gitignored):
- `inventory.html` — baseline inventory of existing scaffolding before Guardian
- `architecture-v2.html` — three-tier architecture visual

These are reference only; the canonical description is this spec.

## Appendix B — Relationship to `graphify`

Chris referenced `safishamsi/graphify` as a repo visualization tool. Guardian does not depend on it. The Mermaid output from `cartographer.py` is the canonical visual. If Chris later wants richer rendering, `graphify` can be added as a dev-only optional tool without Guardian depending on it.
