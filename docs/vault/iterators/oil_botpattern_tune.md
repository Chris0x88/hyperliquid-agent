---
kind: iterator
last_regenerated: 2026-04-09 16:36
iterator_name: oil_botpattern_tune
class_name: OilBotPatternTuneIterator
source_file: cli/daemon/iterators/oil_botpattern_tune.py
tiers:
  - watch
  - rebalance
  - opportunistic
kill_switch: data/config/oil_botpattern_tune.json
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: oil_botpattern_tune

**Class**: `OilBotPatternTuneIterator` in [`cli/daemon/iterators/oil_botpattern_tune.py`](../../cli/daemon/iterators/oil_botpattern_tune.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: `data/config/oil_botpattern_tune.json`

**Registered in `daemon_start()`**: ✅ yes

## Description

OilBotPatternTuneIterator — sub-system 6 layer L1 bounded auto-tune.

Spec: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md

Watches closed oil_botpattern trades (from data/research/journal.jsonl)
plus the decision journal (data/strategy/oil_botpattern_journal.jsonl).
Each eligible tick:

  1. Reads the last N closed oil_botpattern trades (window_size).
  2. Reads the last N decisions from the decision journal.
  3. Reads the audit log to build a per-param rate-limit index.
  4. Calls modules.oil_botpattern_tune.compute_proposals().
  5. If any proposals are returned, applies them atomically to
     data/config/oil_botpattern.json and appends audit records to
     data/strategy/oil_botpattern_tune_audit.jsonl.

Kill switch: data/config/oil_botpattern_tune.json → enabled: false.
Ships with enabled=false — zero production impact on first deploy.

Registered in REBALANCE + OPPORTUNISTIC tiers only. NOT in WATCH.
Rationale: L1 mutates oil_botpattern.json. oil_botpattern is only
active in those tiers, so running L1 in WATCH has no value and only
expands blast radius.

This iterator does NOT place trades, emit OrderIntents, or call any
external APIs. It only reads the two journals and atomically rewrites
a single config file.

## See also

- Tier registration: [[Tier-Ladder]]
- Kill switch: `data/config/oil_botpattern_tune.json` → [[config-oil_botpattern_tune]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
