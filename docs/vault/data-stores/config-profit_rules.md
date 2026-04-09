---
kind: config_file
last_regenerated: 2026-04-09 14:08
path: data/config/profit_rules.json
is_kill_switch: false
tags:
  - config
---
# Config: `profit_rules.json`

**Path**: [`data/config/profit_rules.json`](../../data/config/profit_rules.json)

**Is kill switch**: ❌ no

## Current contents

```json
{
  "xyz:BRENTOIL": {
    "quick_profit_pct": 5.0,
    "quick_profit_window_min": 30,
    "quick_profit_take_pct": 25,
    "extended_profit_pct": 10.0,
    "extended_profit_window_min": 120,
    "extended_profit_take_pct": 25
  },
  "BTC-PERP": {
    "quick_profit_pct": 8.0,
    "quick_profit_window_min": 60,
    "quick_profit_take_pct": 20,
    "extended_profit_pct": 15.0,
    "extended_profit_window_min": 240,
    "extended_profit_take_pct": 25
  }
}

```

## See also

- Likely consumer: [[profit_rules]] iterator

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
