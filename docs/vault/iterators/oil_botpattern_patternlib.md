---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: oil_botpattern_patternlib
class_name: OilBotPatternPatternLibIterator
source_file: cli/daemon/iterators/oil_botpattern_patternlib.py
tiers:
  - watch
  - rebalance
  - opportunistic
kill_switch: data/config/oil_botpattern_patternlib.json
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: oil_botpattern_patternlib

**Class**: `OilBotPatternPatternLibIterator` in [`cli/daemon/iterators/oil_botpattern_patternlib.py`](../../cli/daemon/iterators/oil_botpattern_patternlib.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: `data/config/oil_botpattern_patternlib.json`

**Registered in `daemon_start()`**: ✅ yes

## Description

OilBotPatternPatternLibIterator — sub-system 6 layer L3 pattern library.

Spec: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md

Watches data/research/bot_patterns.jsonl, detects novel signatures
(classification, direction, confidence_band, signals), tallies their
occurrences in a rolling window, and writes PatternCandidate records
to data/research/bot_pattern_candidates.jsonl once a signature crosses
min_occurrences.

Kill switch: data/config/oil_botpattern_patternlib.json → enabled: false.
Ships with enabled=false.

Registered in ALL THREE tiers (unlike L1/L2). Reason: this iterator is
read-only against bot_patterns.jsonl and write-only to its own files.
It doesn't mutate any config, doesn't affect sub-system 5 behavior, and
doesn't trade. Safe to run in WATCH where catalog growth still has
value even without live trading.

Does NOT modify sub-system 4's classifier behavior — L3 is purely
observational. A future wedge can teach sub-system 4 to gate on the
promoted catalog.

## See also

- Tier registration: [[Tier-Ladder]]
- Kill switch: `data/config/oil_botpattern_patternlib.json` → [[config-oil_botpattern_patternlib]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
