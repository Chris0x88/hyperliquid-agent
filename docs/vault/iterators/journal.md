---
kind: iterator
last_regenerated: 2026-04-09 14:08
iterator_name: journal
class_name: JournalIterator
source_file: cli/daemon/iterators/journal.py
tiers:
  - watch
  - rebalance
  - opportunistic
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: journal

**Class**: `JournalIterator` in [`cli/daemon/iterators/journal.py`](../../cli/daemon/iterators/journal.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

JournalIterator — logs state snapshots, detects position closes, writes trade journal.

Tracks positions across ticks. When a position disappears (closed) or flips direction,
creates a full JournalEntry with entry/exit/SL/TP/PnL and persists via JournalGuard.

Tick snapshot rotation (H5 hardening): tick snapshots are written to a
date-stamped file (``ticks-YYYYMMDD.jsonl``) under ``data/daemon/journal/``,
not to a single growing ``ticks.jsonl``. Files older than ``RETENTION_DAYS``
days are pruned automatically. This closes the active growth concern from
the 2026-04-07 verification ledger (~1.1 MB/day → 365 MB/year unrotated).
The legacy single-file ``ticks.jsonl``, if present from before this rollout,
is left in place — operators can rename or archive it manually.

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
