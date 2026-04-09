---
kind: iterator
last_regenerated: 2026-04-09 14:08
iterator_name: memory_backup
class_name: MemoryBackupIterator
source_file: cli/daemon/iterators/memory_backup.py
tiers:
  - watch
  - rebalance
  - opportunistic
kill_switch: data/config/memory_backup.json
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: memory_backup

**Class**: `MemoryBackupIterator` in [`cli/daemon/iterators/memory_backup.py`](../../cli/daemon/iterators/memory_backup.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: `data/config/memory_backup.json`

**Registered in `daemon_start()`**: ✅ yes

## Description

Hourly atomic backup of memory.db with rotation + integrity check.

## See also

- Tier registration: [[Tier-Ladder]]
- Kill switch: `data/config/memory_backup.json` → [[config-memory_backup]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
