---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: action_queue
class_name: ActionQueueIterator
source_file: cli/daemon/iterators/action_queue.py
tiers:
  - watch
  - rebalance
  - opportunistic
kill_switch: data/config/action_queue.json
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: action_queue

**Class**: `ActionQueueIterator` in [`cli/daemon/iterators/action_queue.py`](../../cli/daemon/iterators/action_queue.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: `data/config/action_queue.json`

**Registered in `daemon_start()`**: ✅ yes

## Description

Once-per-day nudge sweep.

## See also

- Tier registration: [[Tier-Ladder]]
- Kill switch: `data/config/action_queue.json` → [[config-action_queue]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
