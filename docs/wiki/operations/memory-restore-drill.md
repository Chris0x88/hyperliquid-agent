# Memory.db Restore Drill

> "Untested backups are not backups." — NORTH_STAR.md
>
> Run this drill **quarterly**. 15 minutes. Dry-run mode exists — use it.

## What the backup system is

The `memory_backup` daemon iterator (`cli/daemon/iterators/memory_backup.py`)
takes hourly atomic snapshots of `data/memory/memory.db` using the
`sqlite3.Connection.backup()` online-backup API — safe against concurrent
writers (Telegram bot, dream cycle, `lesson_author`). Each snapshot is written
to `.tmp`, fsync'd, renamed, then integrity-checked via
`PRAGMA integrity_check`. The first snapshot of each day is promoted to a
`-daily` slot and the first of each ISO week to a `-weekly` slot. Retention
is 24 hourly + 7 daily + 4 weekly (rotating oldest-out). Kill switch:
`data/config/memory_backup.json` → `{"enabled": false}`.

Snapshot filenames are self-describing and sort chronologically:

```
data/memory/backups/
  memory-20260409-1004.db         ← hourly, 2026-04-09 10:04 local
  memory-20260409-1018.db         ← hourly
  memory-20260409-daily.db        ← daily slot for 2026-04-09
  memory-2026W15-weekly.db        ← weekly slot for ISO 2026 week 15
```

## What can go wrong (why we back up)

`memory.db` is the single-file home for the entire lessons corpus,
consolidated events, observations, and action_log. It's a SPOF. Failure modes
this backup covers:

- **Corruption** — power loss mid-write, disk bit-rot, SQLite WAL truncation bug
- **Accidental delete** — `rm data/memory/memory.db`, `git clean -fdx`, wrong `mv`
- **Schema migration fail** — a migration lands partially, DB is half-old half-new
- **Disk failure** — SSD dies, filesystem corruption, full disk preventing writes
- **Lock contention / runaway writer** — a stuck process trashes the page cache
- **Container/volume misconfig** — Railway volume remount to wrong path

## Prerequisites

- You are on the host that runs the daemon (Brisbane workstation)
- `cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli`
- `sqlite3` CLI installed (`which sqlite3`)
- Recent snapshot exists in `data/memory/backups/`

## The restore drill — real restore (production)

Run this **only** when the live `memory.db` is actually broken. For the
quarterly drill, skip to the Dry-run section below.

### 1. Stop the daemon and the Telegram bot

```bash
# Stop daemon (launchd-managed in production)
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.daemon.plist

# Stop Telegram bot (single-instance via PID file)
pgrep -f "telegram_bot.py" | xargs -r kill
sleep 2
pgrep -f "telegram_bot.py" | xargs -r kill -9   # only if still alive

# Verify nothing is holding memory.db
lsof data/memory/memory.db 2>/dev/null || echo "clean — no holders"
```

If `lsof` shows any process, stop it before proceeding. A writer on the file
during restore will corrupt the restore.

### 2. Preserve the broken DB as evidence

**Never delete the broken file.** Move it aside with a date-stamped suffix
so post-mortem is possible.

```bash
TS=$(date +%Y%m%d-%H%M)
mv data/memory/memory.db data/memory/memory.db.broken-${TS}
# If WAL/SHM sidecars exist, move them too
[ -f data/memory/memory.db-wal ] && mv data/memory/memory.db-wal data/memory/memory.db-wal.broken-${TS}
[ -f data/memory/memory.db-shm ] && mv data/memory/memory.db-shm data/memory/memory.db-shm.broken-${TS}
```

### 3. Pick a snapshot

Newest-first. Hourly is usually what you want. Daily/weekly only if recent
hourly snapshots are themselves corrupt.

```bash
ls -lt data/memory/backups/ | head -20
```

Pick one — e.g. `memory-20260409-1018.db`.

### 4. Verify the snapshot BEFORE copying it over

```bash
SNAP=data/memory/backups/memory-20260409-1018.db
sqlite3 "$SNAP" "PRAGMA integrity_check;"
# Expect: ok
sqlite3 "$SNAP" "SELECT COUNT(*) FROM lessons;"
# Expect: a sane number (non-zero unless the DB is genuinely empty)
```

If `integrity_check` does NOT return `ok`, STOP. That snapshot is dead —
see "Snapshot is itself corrupt" below.

### 5. Copy the snapshot into place

```bash
cp data/memory/backups/memory-20260409-1018.db data/memory/memory.db
# Match the permissions your daemon runs as (usually your own user)
chmod 644 data/memory/memory.db
```

### 6. Verify the restored DB

```bash
sqlite3 data/memory/memory.db "PRAGMA integrity_check;"
# Expect: ok

sqlite3 data/memory/memory.db "SELECT COUNT(*) FROM lessons;"
sqlite3 data/memory/memory.db "SELECT MAX(created_at) FROM lessons;"
# Confirm the most-recent lesson timestamp matches the snapshot's age.
```

### 7. Restart daemon and bot

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.daemon.plist
launchctl print gui/$(id -u)/com.hyperliquid.daemon | grep state
# Expect: state = running

# Telegram bot — start via your usual entry point (e.g. systemd unit, tmux, or launchd)
# then verify it's up:
pgrep -f "telegram_bot.py" && echo "bot up"
```

### 8. Verify from Telegram

Send to the bot:

```
/lessonsearch <keyword-you-know-is-in-the-snapshot>
```

You should see results. If the bot responds with "no results" for a query
you know should match, something went wrong — the DB was restored but the
FTS5 index may be stale. Rebuild FTS from inside Python:

```bash
.venv/bin/python -c "from common.memory import rebuild_fts; rebuild_fts()"
```

(If `rebuild_fts` doesn't exist at the time you read this, fall back to
`.venv/bin/python -m cli.tools.memory_tools rebuild-fts` or check
`common/memory.py` for the current helper name.)

### 9. Log the incident

Append a line to `docs/wiki/build-log.md` with the date, which snapshot you
restored from, and what broke the original.

---

## Snapshot is itself corrupt

If `PRAGMA integrity_check` on a snapshot returns anything other than `ok`:

1. **Do not delete it.** Keep it in `backups/` — the iterator's retention
   rotation deliberately does NOT prune corrupt snapshots (they're forensic
   evidence of when corruption started).
2. **Fall back to the next most-recent snapshot.** Run `integrity_check`
   again. Walk backward — hourly → daily → weekly — until you find one
   that passes.
3. **Log loud.** Append to `docs/wiki/build-log.md` immediately: date,
   corrupt snapshot filenames, the last-good snapshot, and the time gap
   (data lost).
4. **Escalate.** If the most recent clean snapshot is >24h old, that's a
   real incident — the hourly iterator was either silently failing its
   integrity check or was disabled. Check:
   - `data/config/memory_backup.json` — is `enabled: true`?
   - Daemon logs for `MemoryBackup: integrity_check FAILED` lines
   - `launchctl print gui/$(id -u)/com.hyperliquid.daemon` — daemon was actually running?
5. **Do not re-enable live writes to `memory.db` until** you've restored
   from a verified-clean snapshot. A corrupt backup usually means the
   source was already corrupt when it was taken.

---

## Dry-run — how to practice the drill without touching production

This is the quarterly drill. It's a copy-restore-verify cycle in a temp
directory that never touches the real daemon.

```bash
# 1. Make a scratch dir
DRILL=/tmp/memory-restore-drill-$(date +%Y%m%d-%H%M)
mkdir -p "$DRILL"

# 2. Copy the LIVE db + a recent snapshot into it
cp data/memory/memory.db "$DRILL/memory.db.original"
SNAP=$(ls -t data/memory/backups/memory-*.db | head -1)
cp "$SNAP" "$DRILL/snapshot.db"
echo "Practicing restore from: $SNAP"

# 3. Pretend the live DB is broken — swap it out
mv "$DRILL/memory.db.original" "$DRILL/memory.db.broken-$(date +%Y%m%d)"

# 4. Restore the snapshot into "$DRILL/memory.db"
cp "$DRILL/snapshot.db" "$DRILL/memory.db"

# 5. Integrity check the restored DB
sqlite3 "$DRILL/memory.db" "PRAGMA integrity_check;"
# Expect: ok

# 6. Sanity-check contents
sqlite3 "$DRILL/memory.db" "SELECT COUNT(*) FROM lessons;"
sqlite3 "$DRILL/memory.db" "SELECT name FROM sqlite_master WHERE type='table';"

# 7. Throw it away
rm -rf "$DRILL"
echo "drill complete — production DB untouched"
```

Production `memory.db` was never modified. Daemon was never stopped. This
whole cycle should take 5 minutes. **Run it quarterly.**

---

## Verification checklist

Copy this block into `docs/wiki/build-log.md` after each drill (real or
dry-run).

```
Memory.db restore drill — YYYY-MM-DD
  Type:               [ ] dry-run   [ ] real restore
  Snapshot used:      memory-________.db
  Snapshot size:      ______ bytes
  Integrity check:    [ ] ok   [ ] FAILED
  Restored DB check:  [ ] ok   [ ] FAILED
  Lesson count:       ______  (expected ~______)
  /lessonsearch test: [ ] passed   [ ] failed   [ ] n/a (dry-run)
  Daemon restart:     [ ] clean    [ ] failed   [ ] n/a (dry-run)
  Bot restart:        [ ] clean    [ ] failed   [ ] n/a (dry-run)
  Elapsed time:       ______ minutes
  Notes:
```

## Kill switch (how to pause the backup iterator)

Edit `data/config/memory_backup.json`:

```json
{ "enabled": false }
```

The iterator picks up config changes on its next tick — no restart needed.
Re-enable by setting `true`. Only pause backups if they're actively causing
a problem (unlikely — the iterator is read-only against the source DB).
