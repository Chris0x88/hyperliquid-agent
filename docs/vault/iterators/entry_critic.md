---
kind: iterator
last_regenerated: 2026-04-09 14:08
iterator_name: entry_critic
class_name: EntryCriticIterator
source_file: cli/daemon/iterators/entry_critic.py
tiers:
  - watch
  - rebalance
  - opportunistic
kill_switch: data/config/entry_critic.json
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: entry_critic

**Class**: `EntryCriticIterator` in [`cli/daemon/iterators/entry_critic.py`](../../cli/daemon/iterators/entry_critic.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: `data/config/entry_critic.json`

**Registered in `daemon_start()`**: ✅ yes

## Description

Fires a one-shot critique the first time a new entry appears.

## See also

- Tier registration: [[Tier-Ladder]]
- Kill switch: `data/config/entry_critic.json` → [[config-entry_critic]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
