---
kind: component
component: memory-backup
status: shipped
tags:
  - component
  - memory-backup
  - spof-closed
  - hand-annotated-example
---

# Memory Backup Iterator — Deep Dive

> **This page is a HAND-WRITTEN example** of the "good" density for
> component deep-dives. The auto-gen stub for this iterator lives at
> [[iterators/memory_backup]] (updated on every vault regeneration).
> This page is the narrative companion — the story of the bug, the
> fix, and the lesson.

## What this iterator protects

`data/memory/memory.db` — a ~1.2 MB SQLite file holding:

- The entire trade lesson corpus (`lessons` table + `lessons_fts` FTS5 index)
- Consolidated events from the dream cycle
- Observations + learnings written by the agent via `memory_write`
- Action log + execution traces
- Chat history summaries

**Losing this file loses the entire learning system.** Per
[[architecture/Data-Discipline|P9]] ("historical oracles are forever"),
this is unacceptable. The iterator ensures it can't happen.

## The online-backup API (the right primitive)

Python's `sqlite3.Connection.backup()` API — not a file copy — pages
through the source file under SQLite's locks and writes a complete
snapshot to a destination connection. It's **safe to run against a
live database** while other writers (Telegram bot, daemon, dream
cycle, lesson_author) hold open connections.

```python
src = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
dst = sqlite3.connect(str(tmp_path))
with dst:
    src.backup(dst)  # pages through source respecting WAL + locks
# fsync + atomic rename → final snapshot path
```

Naïve file copy (`shutil.copy2`) would risk torn reads if the WAL was
mid-flush. The backup API handles this correctly at the SQLite page
level.

## Retention: 24 hourly + 7 daily + 4 weekly

Three rotation windows, managed by the same iterator:

- **Hourly** — one snapshot per hour, keep the most recent 24
- **Daily** — the first snapshot of each UTC day is also copied to
  `memory-YYYYMMDD-daily.db`, keep the most recent 7
- **Weekly** — the first snapshot of each ISO week is also copied
  to `memory-YYYYWW-weekly.db`, keep the most recent 4

At steady state, 35 snapshot files cover the last 24 hours at hourly
granularity, the last week at daily, and the last month at weekly.
~50 MB of disk for 30 days of recovery coverage.

Rotation is **safe**: daily and weekly slots are NEVER deleted by the
hourly rotation. If the newest hourly rolls off, the daily slot for
that day stays intact.

## Integrity check — loud failure, no silent loss

Every snapshot is immediately verified via
`PRAGMA integrity_check`. Failure does NOT delete the snapshot —
it's preserved for forensic recovery, the rotation is skipped, and a
loud warning is logged. The iterator will try again on the next tick
with a fresh snapshot.

Why this matters: a corrupted backup is worse than no backup because
you might try to restore from it. The iterator refuses to silently
rotate a bad snapshot out of existence.

## The registration gap bug — 2026-04-09

When this iterator first shipped in commit `996bf6f`, I:

1. ✅ Added it to `cli/daemon/tiers.py` in all 3 tiers
2. ✅ Wrote 16 unit tests in `tests/test_memory_backup_iterator.py`
3. ✅ Manually invoked `it.run_once()` twice from the command line to
   verify the backup directory + integrity check worked
4. ❌ **NEVER registered it in `cli/commands/daemon.py:daemon_start()`**
   via `clock.register(MemoryBackupIterator())`

**Consequence**: the daemon clock never instantiated the iterator. The
hourly backups were not actually running in production. The only
snapshots on disk were the two manual `run_once()` calls. From the
moment the iterator "shipped" until the gap was caught, the memory.db
SPOF I claimed to close was still open.

### How it was caught

**12 hours later**, a parallel agent (the [[iterators/action_queue]]
builder, dispatched for unrelated work) audited the registration
patterns of iterators it needed to register alongside its own.
From its final report:

> Pre-existing gap noticed but NOT fixed: MemoryBackupIterator appears
> in tiers.py but is NOT registered in cli/commands/daemon.py (no
> `clock.register(MemoryBackupIterator())` call). That's outside the
> scope of this task — flagging it for the next audit.

The action_queue agent wasn't looking for this bug. It found it as a
side effect of reading daemon.py to add its own registration. That's
the kind of value parallel structural audits deliver — bugs in code
you've already convinced yourself works.

### The fix

One `try:/from...import/clock.register()` block in
`cli/commands/daemon.py` matching the pattern of the other
recently-added iterators (`lesson_author`, `entry_critic`,
`action_queue`). 12 lines. Committed as `4a58095` with a 10-line
comment explaining the bug and the catch path so future sessions
don't rediscover it.

## The broader lesson

**Two steps are required to ship an iterator**: tier membership AND
daemon registration. Skipping either one is a silent bug.

Unit tests instantiate the class directly, so they don't catch the
daemon-registration gap. Integration tests against the live daemon
would, but we don't have those. The cheapest fix: make the gap
visible in the structural map, and add a drift check that fails on it.

**Both fixes are in place now**:

1. Every auto-generated iterator page in this vault cross-references
   `tiers.py` AND `daemon.py` and shows a `⚠️ REGISTRATION GAP`
   warning if an iterator is in tiers but missing from daemon_start.
   Browse [[iterators/_index]] to see the cross-ref applied to every
   iterator in the codebase.

2. A future Guardian wedge (filed in the commit message of
   `4a58095`) will enforce this as a drift rule: any iterator in
   `tiers.py` with no corresponding `clock.register()` call in
   `daemon.py` is a bug. That single rule would have caught the
   memory_backup gap on the commit that introduced it.

## The restore drill

See [`docs/wiki/operations/memory-restore-drill.md`](../../../docs/wiki/operations/memory-restore-drill.md)
— the full runbook with copy-pasteable shell commands.

Quick TL;DR:

```bash
# 1. Stop the daemon and Telegram bot
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.daemon.plist
pgrep -f cli.telegram_bot | xargs kill

# 2. Preserve the broken DB for forensic recovery
mv data/memory/memory.db data/memory/memory.db.broken-$(date +%Y%m%d)

# 3. Verify the snapshot you're about to restore
sqlite3 data/memory/backups/memory-20260409-daily.db "PRAGMA integrity_check"

# 4. Copy + chmod
cp data/memory/backups/memory-20260409-daily.db data/memory/memory.db
chmod 644 data/memory/memory.db

# 5. Verify restored DB
sqlite3 data/memory/memory.db "PRAGMA integrity_check"
sqlite3 data/memory/memory.db "SELECT COUNT(*) FROM lessons"

# 6. Restart
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.daemon.plist

# 7. Verify from Telegram
# Type in Telegram: /lessonsearch oil
# If results come back, restore succeeded.
```

The restore drill is on the [[iterators/action_queue]] nudge list with
**quarterly** cadence. Chris gets a Telegram nudge if the drill
hasn't been run in 90+ days. Untested backups aren't backups.

## What this iterator does NOT cover

- **`data/snapshots/*.json`** — account snapshots grow unbounded and
  have no backup strategy. Flagged in [[plans/MASTER_PLAN]] Open
  Questions and in ADR-011 §1 as a Tier 1 fix prerequisite for the
  quant sibling app build.
- **`data/research/journal.jsonl`** — append-only journal of closed
  trades. Protected by git (committed) but not by the backup iterator.
- **`data/daemon/chat_history.jsonl`** — the historical oracle. NOT
  backed up by this iterator. Protected by the static source-code
  scan test that forbids any write/rename/unlink pattern in the
  writer module.
- **`data/thesis/*.json`** — thesis files are dual-written to
  `data/thesis_backup/` by `common/thesis.py:save()`. Separate SPOF
  protection, not via this iterator.

Each of these has its own protection strategy or documented gap. The
memory_backup iterator is scoped tightly to the one SQLite file that
holds the lesson corpus.

## See also

- [[iterators/memory_backup]] — auto-generated structural page
- [[data-stores/config-memory_backup]] — kill switch + config
- [[architecture/Data-Discipline]] — P9 + P10 principles
- [[components/Trade-Lesson-Layer]] — the corpus this iterator protects
- [[runbooks/Regenerate-Vault]] — how the vault's registration gap check works
