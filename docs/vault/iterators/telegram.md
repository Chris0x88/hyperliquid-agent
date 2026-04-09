---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: telegram
class_name: TelegramIterator
source_file: cli/daemon/iterators/telegram.py
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
# Iterator: telegram

**Class**: `TelegramIterator` in [`cli/daemon/iterators/telegram.py`](../../cli/daemon/iterators/telegram.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: _none_

**Registered in `daemon_start()`**: ✅ yes

## Description

Sends daemon alerts and trade summaries to Telegram.

Reads bot token and chat_id from environment or config file.
Env vars: HL_TELEGRAM_BOT_TOKEN, HL_TELEGRAM_CHAT_ID
Config:  data/daemon/telegram.json

## See also

- Tier registration: [[Tier-Ladder]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
