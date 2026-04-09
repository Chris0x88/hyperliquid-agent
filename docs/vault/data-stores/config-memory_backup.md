---
kind: config_file
last_regenerated: 2026-04-09 14:08
path: data/config/memory_backup.json
is_kill_switch: true
tags:
  - config
  - kill-switch
---
# Config: `memory_backup.json`

**Path**: [`data/config/memory_backup.json`](../../data/config/memory_backup.json)

**Is kill switch**: ✅ yes (has `enabled` field)

## Current contents

```json
{
  "enabled": true,
  "interval_hours": 1,
  "source_path": "data/memory/memory.db",
  "backup_dir": "data/memory/backups",
  "keep_hourly": 24,
  "keep_daily": 7,
  "keep_weekly": 4,
  "verify_integrity": true
}

```

## See also

- Likely consumer: [[memory_backup]] iterator

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
