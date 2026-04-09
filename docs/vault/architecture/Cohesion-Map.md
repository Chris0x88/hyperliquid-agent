---
kind: architecture
title: Cohesion Map — Parallel Writers and Cross-Process Contracts
last_manual_update: 2026-04-09
source_phases:
  - SYSTEM_REVIEW_HARDENING_PLAN Phase C
  - SYSTEM_REVIEW_HARDENING_PLAN Phase D
tags:
  - architecture
  - cohesion
  - parallel-writers
  - drift-detection
---

# Cohesion Map — Parallel Writers and Cross-Process Contracts

> **Hand-written page.** The vault auto-generator does NOT touch
> this file. This is the layer above structural drift that captures
> **who writes what file, from which process, under what lock, and
> what happens when they collide.** It exists because the auto-gen
> vault shows you the iterators and the configs but does NOT show
> you the cross-process race conditions between them.

**Source audits:** `docs/plans/TIMER_LOOP_AUDIT.md` §5.2 +
`docs/plans/COHESION_HARDENING_LIST.md` P0 and P1 items M1–M5.

## The three processes

Three launchd-managed processes share one filesystem tree under
`agent-cli/data/` and one SQLite database at `data/memory/memory.db`:

| Process | PID (observed) | Entry point | Loop |
|---------|----------------|-------------|------|
| daemon   | 18320 | `cli.main daemon start --tier watch --mainnet --tick 120` | 120 s tick loop |
| telegram | 72197 | `cli.telegram_bot` | continuous polling, command handlers fire on user input |
| heartbeat | — (one-shot) | `scripts/run_heartbeat.py` | launchd `StartInterval=120` respawn |

Plus two **out-of-process writers** that can mutate the same state:

- **AI slash commands** (`/lessonauthorai`, `/brutalreviewai`,
  `/briefai`) — run inside the telegram process's agent_runtime but
  issue tool calls that write to the shared filesystem.
- **Manual edits** — the user editing config files by hand from a
  text editor.

## Parallel-writer matrix

Each row is a file or table with more than one writer. The **Lock**
column is the invariant that must hold; **Status** reflects whether
the invariant is enforced today or relied on implicitly.

| File / table | Writer 1 | Writer 2 | Writer 3 | Lock invariant | Status |
|---|---|---|---|---|---|
| `data/config/oil_botpattern.json` | `oil_botpattern_tune` (daemon) | Telegram `/activate` / `/selftuneapprove` (telegram process) | Manual edit | atomic-rename OR fcntl.lockf | **VIOLATED** — atomic-rename alone is last-writer-wins. See COHESION_HARDENING_LIST P1-3. |
| `data/config/watchlist.json` | Auto-watchlist (F2, daemon) | Telegram `/addmarket` | Manual edit | atomic-rename | OK — small file, collision window tiny, tolerated |
| `data/authority.json` | `/delegate`, `/authority` (telegram) | Manual edit | — | atomic-rename | OK — single effective writer |
| `data/memory/memory.db` (SQLite) | `memory_consolidation` (daemon) | `lesson_author` (daemon) | AI commands via `memory_write` tool (telegram) | SQLite lock | OK — SQLite's own lock is correct |
| `data/memory/memory.db` backup | `memory_backup` iterator (daemon) | — | — | atomic cp + rename | OK — single writer |
| `data/strategy/oil_botpattern_proposals.jsonl` | `oil_botpattern_reflect` (daemon) | Telegram `/selftuneapprove` (telegram process) | — | atomic-rewrite | **VIOLATED** — daemon can rewrite while telegram is editing. See COHESION_HARDENING_LIST P2-1. |
| `data/daemon/chat_history.jsonl` | Telegram agent-turn writer | Market-correlation enrichment (daemon? telegram?) | — | append-only | OK if pure-append, UNSAFE if re-rewriting with market snapshots mid-append. **Verify.** |
| `data/feedback.jsonl` | `/feedback` (telegram) | `/feedback resolve` (telegram) | — | append-only event log | OK — same process, sequential |
| `data/news/catalysts.jsonl` | `news_ingest` iterator (daemon) | — | — | append-only | OK — single writer |
| `data/supply/state.json` | `supply_ledger` iterator (daemon) | `/disrupt` + `/disrupt-update` (telegram) | Manual edit | atomic-rename | **RACE** — daemon and telegram both rewrite the whole file |
| `data/thesis/*.json` | `thesis_engine` iterator (daemon — read-only?) | AI agent `update_thesis` tool (telegram) | Manual edit | atomic-rename | **DRIFT** — daemon reads; if reader and writer overlap mid-write, JSONDecodeError. See COHESION_HARDENING_LIST P0-5. |
| `data/daemon/state.json` | Daemon only | — | — | atomic-rename | OK — single writer |
| `data/strategy/oil_botpattern_state.json` (runtime) | `oil_botpattern` iterator | — | — | atomic-rename | OK — single writer |
| `data/strategy/oil_botpattern_tune_audit.jsonl` | `oil_botpattern_tune` iterator | — | — | append-only | OK — single writer |

## The pattern the matrix reveals

**Every parallel-writer row falls into one of four buckets:**

1. **OK (single effective writer)** — one process actually touches
   the file despite the theoretical multi-writer surface.
2. **OK (append-only)** — multiple writers but only appends, no
   rewrites. Collisions are bounded to the granularity of the
   journaled filesystem.
3. **RACE tolerated** — parallel rewrites happen but the collision
   window is small and the failure mode is non-critical (e.g.
   watchlist bounce).
4. **RACE unacceptable** — parallel rewrites on a file whose stale
   state affects real-money decisions. These are the **P0/P1
   hardening targets**.

The RACE-unacceptable bucket today contains four rows:
`oil_botpattern.json`, `oil_botpattern_proposals.jsonl`,
`supply/state.json`, and `thesis/*.json`. Three of those are
currently bounded by kill switches being OFF on the writer side;
**the moment any of them flips ON, the race becomes hot** and the
hardening becomes blocking.

## The pattern fix (Meta-finding M2)

Every row in the RACE-unacceptable bucket needs one of:

- A single-writer reduction — move the write to one process only.
- File-lock coordination — `fcntl.lockf` on a sidecar `.lock` file
  acquired before every atomic-rename. This is the
  `common/file_lock.py` helper proposed in Phase D M2.
- Event-log reduction — convert "rewrite the whole file" into
  "append an event row." The telegram side then reads the whole
  event log at read-time and reconstructs current state.

Event-log reduction is the NORTH_STAR P9-aligned answer: it also
gets you historical oracles for free. It's the right fix for
`oil_botpattern_proposals.jsonl` and `supply/state.json`. The config
files (`oil_botpattern.json`) are different because the shape of the
file IS state, not events — they need file-lock coordination.

## What the vault auto-gen can't show you

The auto-generated `docs/vault/iterators/oil_botpattern_tune.md` tells
you the iterator writes `data/config/oil_botpattern.json`. It does
NOT tell you the telegram process ALSO writes that file. No amount of
AST parsing inside `cli/daemon/` finds the telegram side. The
parallel-writer matrix above is the **human-maintained index** of
cross-process contracts.

**Maintenance protocol:** when adding a new file writer anywhere in
`cli/telegram_commands/*.py` or any AI agent tool, add a row to this
table. A future `health/parallel_writers.md` auto-page (proposed in
`docs/plans/VAULT_AS_AUDITOR.md` §Extended) could eventually
cross-reference daemon writers against telegram writers programmatically,
but until then this map is the source of truth.

## Related

- `docs/vault/architecture/Time-Loop-Interweaving.md` — the companion
  page for *when* writes happen, not just *who* writes them.
- `docs/vault/runbooks/Drift-Detection.md` — how to spot changes to
  the files on this matrix.
- `docs/plans/TIMER_LOOP_AUDIT.md` — Phase C findings that populated
  this page.
- `docs/plans/COHESION_HARDENING_LIST.md` P1-3, P0-5, P2-1.
