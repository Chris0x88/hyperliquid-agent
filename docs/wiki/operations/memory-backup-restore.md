# Memory Backup — Restore Procedure

> Canonical restore procedure as of 2026-04-17.
> Uses `scripts/restore_memory_backup.py` — the verified, idempotent restore script.
> The older manual drill notes are in `memory-restore-drill.md`.

---

## When to use this

| Situation | What to do |
|-----------|------------|
| `memory.db` is corrupt (`PRAGMA integrity_check` returns anything other than `ok`) | Full restore — steps 1–7 below |
| Accidental `rm data/memory/memory.db` | Full restore — steps 1–7 below |
| Failed schema migration left DB half-old / half-new | Full restore — steps 1–7 below |
| You want to roll back to an earlier state (e.g., bad lesson ingested) | Full restore with `--from <older-snapshot>` |
| Quarterly drill (practice, nothing is broken) | Dry-run drill — jump to "Drill without touching production" |

---

## Backup inventory

Before restoring anything, see what you have:

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli

.venv/bin/python scripts/restore_memory_backup.py --list
```

Output (newest first):

```
FILENAME                                  SIZE        MODIFIED              SHA256 (first 16)
------------------------------------------------------------------------------------------------
memory-20260417-1144.db                 2.6 MB  2026-04-17 11:44:18   e7c388d2a07ae357
memory-20260417-1044.db                 2.6 MB  2026-04-17 10:44:06   46a016e7b26bde4c
...
memory-20260417-daily.db                2.5 MB  2026-04-17 00:34:46   722dd1a365a9f0b6
memory-2026W16-weekly.db                2.2 MB  2026-04-13 00:26:12   ...
```

Retention guarantee: **24 hourly + 7 daily + 4 weekly**. Nothing older than ~4 weeks lives in `data/memory/backups/` unless the rotation failed (check daemon logs if you see files older than 28 days).

**Pick the newest snapshot whose `integrity_check` you trust.** If you're
unsure, do a dry-run first (step 2 below).

---

## Dry-run first (always)

Before touching anything, check what would happen:

```bash
.venv/bin/python scripts/restore_memory_backup.py \
  --from memory-20260417-1144.db \
  --dry-run
```

This prints the backup's integrity status and row counts without writing
anything. If you are pointing at the live DB, it also tells you whether
`--force` would be required.

---

## Full restore — step by step

### 1. Stop writers

Stop everything that holds an open connection to `memory.db`:

```bash
# Stop daemon
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.daemon.plist

# Stop Telegram bot (single-instance via PID file)
pgrep -f "telegram_bot.py" | xargs -r kill
sleep 2
pgrep -f "telegram_bot.py" | xargs -r kill -9   # only if still alive

# Verify nothing holds the file
lsof data/memory/memory.db 2>/dev/null || echo "clean"
```

Do NOT proceed until `lsof` is clean.

### 2. Confirm which snapshot to restore

```bash
.venv/bin/python scripts/restore_memory_backup.py --list
```

Tip: `memory-<DATE>-daily.db` is a good default — one per day, well-tested
by the iterator's integrity check on write. Hourly slots are newer but were
only verified once (at write time). Weekly slots go back ~4 weeks.

### 3. Dry-run against the actual target

```bash
.venv/bin/python scripts/restore_memory_backup.py \
  --from memory-20260417-1144.db \
  --dry-run
```

Verify the row counts look sane (lessons > 0, events > 0, etc.).

### 4. Restore

The script backs up the existing `memory.db` to `memory.db.pre-restore-<ts>.db`
automatically when you pass `--force`. The original is preserved.

```bash
.venv/bin/python scripts/restore_memory_backup.py \
  --from memory-20260417-1144.db \
  --force
```

**Do not pass `--force` unless you want to overwrite the live DB.**
Without `--force`, the script refuses to overwrite a non-empty target.

Expected output:

```
Source backup : .../data/memory/backups/memory-20260417-1144.db
Target        : .../data/memory/memory.db
Force overwrite: yes

Verifying source backup integrity...
  integrity_check: PASS
Saving pre-restore backup to: .../data/memory/memory.db.pre-restore-20260417-121344.db
  Pre-restore backup integrity_check: PASS (...)

Restoring memory-20260417-1144.db -> .../data/memory/memory.db...
Verifying restored database...
  integrity_check: PASS (ok)

Row counts in restored DB:
  lessons                        1
  events                         26
  learnings                      6
  action_log                     3045
  account_snapshots              9149
  observations                   0
  summaries                      0
  execution_traces               3054

PASS: .../data/memory/memory.db restored from memory-20260417-1144.db and verified clean.
```

Exit code 0 = success. Exit code 1 = integrity check failed. Exit code 2 = refused (non-empty target, no --force).

### 5. Verify after restore

```bash
# Quick integrity sanity-check directly
.venv/bin/python scripts/restore_memory_backup.py --list  # should still work

# Or via sqlite3 directly
sqlite3 data/memory/memory.db "PRAGMA integrity_check;"
# Expect: ok

# Check FTS index is intact
sqlite3 data/memory/memory.db "SELECT COUNT(*) FROM lessons_fts;"
```

If the FTS index appears stale (lessons exist but `/lessonsearch` finds nothing), rebuild it:

```bash
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('data/memory/memory.db')
conn.execute('INSERT INTO lessons_fts(lessons_fts) VALUES(\"rebuild\")')
conn.commit()
conn.close()
print('FTS rebuilt')
"
```

### 6. Restart services

```bash
# Daemon
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.daemon.plist
launchctl print gui/$(id -u)/com.hyperliquid.daemon | grep state
# Expect: state = running

# Telegram bot — however you normally start it
pgrep -f "telegram_bot.py" && echo "bot up"
```

### 7. Verify from Telegram

Send a command you know should work, e.g. `/status` or `/lessonsearch oil`.
Confirm the bot responds correctly.

### 8. Log the incident

Append to `docs/wiki/build-log.md`:

```
YYYY-MM-DD — memory.db restored from memory-<SNAPSHOT>.db
  Reason: <corruption / accidental delete / migration fail>
  Data loss: approximately <N> hours
  Pre-restore backup: data/memory/memory.db.pre-restore-<ts>.db
  Verified: integrity_check ok, FTS intact
```

---

## Rolling back a restore that went wrong

If you restore and then realise it was the wrong snapshot (e.g. you went too
far back and lost important lessons), the script saved your pre-restore DB
automatically:

```bash
# See the pre-restore backup
ls -la data/memory/memory.db.pre-restore-*.db

# Restore BACK from the pre-restore backup
# (it's a valid SQLite file — same process applies)
.venv/bin/python scripts/restore_memory_backup.py \
  --from data/memory/memory.db.pre-restore-20260417-121344.db \
  --to data/memory/memory.db \
  --force
```

The `--from` argument accepts an absolute path if the file is not in the
default backup directory.

---

## Drill without touching production

Run this quarterly. It takes 5–10 minutes and leaves production untouched.

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli

# 1. Pick the newest snapshot
.venv/bin/python scripts/restore_memory_backup.py --list | head -5

# 2. Restore to a temp target (no --force needed — target doesn't exist yet)
.venv/bin/python scripts/restore_memory_backup.py \
  --from memory-20260417-1144.db \
  --to /tmp/memory_drill_$(date +%Y%m%d_%H%M).db

# 3. Verify output ends with "PASS"
# 4. Clean up
rm /tmp/memory_drill_*.db
```

The drill output should look like:

```
...
  integrity_check: PASS (ok)

Row counts in restored DB:
  lessons                        1
  events                         26
  ...

PASS: /tmp/memory_drill_20260417_1213.db restored from memory-20260417-1144.db and verified clean.
```

Paste the PASS line into `build-log.md` dated today.

---

## What to verify after any restore

| Check | Expected |
|-------|----------|
| `PRAGMA integrity_check` | `ok` |
| `SELECT COUNT(*) FROM lessons` | > 0 (or 0 only if the DB was genuinely empty at that snapshot) |
| `SELECT COUNT(*) FROM events` | matches expectations |
| `SELECT COUNT(*) FROM action_log` | plausible — grows daily |
| Daemon starts cleanly | `state = running` in launchctl print |
| Telegram `/status` responds | no error message from bot |
| Telegram `/lessonsearch` returns results | at least one match for a known keyword |

---

## Snapshot is corrupt — escalation path

If every snapshot you try fails `integrity_check`:

1. **Do not delete any of them.** The iterator intentionally keeps corrupt
   snapshots as forensic evidence.
2. Walk backward: hourly → daily → weekly. Find the newest clean one.
3. Check daemon logs for `MemoryBackup: integrity_check FAILED` — this tells
   you exactly when the corruption started.
4. Check `data/config/memory_backup.json` — is `enabled: true`?
5. If the last clean snapshot is >24h old, file a post-mortem in
   `docs/wiki/build-log.md`. Something silently broke the backup loop.

---

## Kill switch (pause the backup iterator)

```bash
cat > data/config/memory_backup.json << 'EOF'
{ "enabled": false }
EOF
```

The iterator reads config on every tick — no restart needed. Re-enable:

```bash
cat > data/config/memory_backup.json << 'EOF'
{ "enabled": true }
EOF
```

Only pause if the iterator is actively causing a problem. It is read-only
against the source DB and has no performance impact during normal operation.

---

## Known artefacts — `.db-shm` / `.db-wal` sidecars in backups/

You may occasionally notice SQLite sidecar files next to snapshots:

```
memory-20260417-1144.db
memory-20260417-1144.db-shm      ← 32 KB
memory-20260417-1144.db-wal      ← 0 bytes
```

**Cause.** The backup iterator and the restore script both open snapshot files
with `file:...?mode=ro` URIs, which never create sidecars. These artefacts
appear when something else opens a snapshot in read-write mode — usually an
external tool (sqlite3 CLI without `-readonly`, DB Browser, a one-off Python
`sqlite3.connect(path)`). Because the snapshot inherits WAL journal mode from
`memory.db`, any rw open spawns `.db-shm` + `.db-wal`.

**Harmless.** A 0-byte `.db-wal` means SQLite has fully checkpointed — all
data is in the `.db` file. Restore works correctly either way (the restore
path uses `mode=ro`, which bypasses the sidecars entirely).

**Cleanup.** Safe to delete both sidecars whenever the `.db-wal` is 0 bytes
and no process holds the file:

```bash
# Confirm nothing is holding them
lsof data/memory/backups/*.db-wal 2>/dev/null || echo "clean"

# All .wal should be 0 bytes
ls -la data/memory/backups/*.db-wal

# Then remove
rm data/memory/backups/*.db-shm data/memory/backups/*.db-wal
```

If you find a **non-zero** `.db-wal`, something still had the file open as a
writer when it was last closed. Do NOT delete — investigate the caller first
(`lsof`, then check recent tooling). The data in the `.wal` is not yet merged
into the `.db` and deletion would lose it.

**Prevention.** Open backup snapshots read-only by default:

```bash
# sqlite3 CLI: pass -readonly
sqlite3 -readonly data/memory/backups/memory-YYYYMMDD-HHMM.db 'PRAGMA integrity_check;'

# Python: always use the mode=ro URI
sqlite3.connect(f"file:{path}?mode=ro", uri=True)
```

---

## Script reference

```
scripts/restore_memory_backup.py

  --list                  List backups (newest first, with size + sha256)
  --from FILENAME         Backup to restore from
  --to PATH               Target path (default: data/memory/memory.db)
  --force                 Allow overwriting non-empty target
  --dry-run               Show what would happen, write nothing
  --snapshot              Take a fresh backup snapshot right now
  --backup-dir DIR        Override backup directory
```

Exit codes: 0 = success, 1 = error (integrity failed, file not found),
2 = user abort (non-empty target, no --force).
