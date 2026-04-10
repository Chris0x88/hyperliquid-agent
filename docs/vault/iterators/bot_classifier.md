---
kind: iterator
last_regenerated: 2026-04-09 16:36
iterator_name: bot_classifier
class_name: BotPatternIterator
source_file: cli/daemon/iterators/bot_classifier.py
tiers:
  - watch
  - rebalance
  - opportunistic
kill_switch: data/config/bot_classifier.json
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: bot_classifier

**Class**: `BotPatternIterator` in [`cli/daemon/iterators/bot_classifier.py`](../../cli/daemon/iterators/bot_classifier.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: `data/config/bot_classifier.json`

**Registered in `daemon_start()`**: ✅ yes

## Description

BotPatternIterator — sub-system 4 of the Oil Bot-Pattern Strategy.

Periodically classifies recent moves on configured oil instruments as
bot-driven, informed, mixed, or unclear, by combining inputs from
sub-systems #1 (catalysts), #2 (supply state), and #3 (cascades) plus
candle data and basic ATR.

Read-only: never places trades. Heuristic-only — no ML, no LLM.
Kill switch: data/config/bot_classifier.json → enabled: false

## See also

- Tier registration: [[Tier-Ladder]]
- Kill switch: `data/config/bot_classifier.json` → [[config-bot_classifier]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
