---
kind: iterator
last_regenerated: 2026-04-09 14:08
iterator_name: pulse
class_name: PulseIterator
source_file: cli/daemon/iterators/pulse.py
tiers:
  - watch
  - opportunistic
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-opportunistic
---
# Iterator: pulse

**Class**: `PulseIterator` in [`cli/daemon/iterators/pulse.py`](../../cli/daemon/iterators/pulse.py)

**Registered in tiers**: `watch`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

PulseIterator — wraps modules/pulse_engine.py for momentum detection.

Persists signals to data/research/signals.jsonl for AI agent access and historical review.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
