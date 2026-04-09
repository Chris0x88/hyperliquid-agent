---
kind: config_file
last_regenerated: 2026-04-09 16:05
path: data/config/risk_caps.json
is_kill_switch: false
tags:
  - config
---
# Config: `risk_caps.json`

**Path**: [`data/config/risk_caps.json`](../../data/config/risk_caps.json)

**Is kill switch**: ❌ no

## Current contents

```json
{
  "_comment": "Per-instrument NORMS for sub-system 5. These are multipliers on the sizing ladder, not hard caps. See OIL_BOT_PATTERN_05_STRATEGY_ENGINE.md.",
  "oil_botpattern": {
    "BRENTOIL": {
      "sizing_multiplier": 1.0,
      "min_atr_buffer_pct": 1.0,
      "notes": "primary instrument — full sizing ladder"
    },
    "CL": {
      "sizing_multiplier": 0.6,
      "min_atr_buffer_pct": 1.5,
      "notes": "less liquid — 60% of BRENTOIL notional at same edge"
    }
  }
}

```

## See also

- Likely consumer: [[risk_caps]] iterator

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
