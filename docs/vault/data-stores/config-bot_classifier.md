---
kind: config_file
last_regenerated: 2026-04-09 16:05
path: data/config/bot_classifier.json
is_kill_switch: true
tags:
  - config
  - kill-switch
---
# Config: `bot_classifier.json`

**Path**: [`data/config/bot_classifier.json`](../../data/config/bot_classifier.json)

**Is kill switch**: ✅ yes (has `enabled` field)

## Current contents

```json
{
  "enabled": true,
  "instruments": ["BRENTOIL"],
  "poll_interval_s": 300,
  "lookback_minutes": 60,
  "cascade_window_min": 30,
  "catalyst_floor": 4,
  "supply_freshness_hours": 72,
  "atr_mult_for_big_move": 1.5,
  "min_price_move_pct_for_classification": 0.5,
  "patterns_jsonl": "data/research/bot_patterns.jsonl"
}

```

## See also

- Likely consumer: [[bot_classifier]] iterator

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
