---
kind: config_file
last_regenerated: 2026-04-09 16:05
path: data/config/supply_ledger.json
is_kill_switch: true
tags:
  - config
  - kill-switch
---
# Config: `supply_ledger.json`

**Path**: [`data/config/supply_ledger.json`](../../data/config/supply_ledger.json)

**Is kill switch**: ✅ yes (has `enabled` field)

## Current contents

```json
{
  "enabled": true,
  "auto_extract": true,
  "recompute_interval_s": 300,
  "disruptions_jsonl": "data/supply/disruptions.jsonl",
  "state_json": "data/supply/state.json",
  "auto_extract_rules": "data/config/supply_auto_extract.yaml"
}

```

## See also

- Likely consumer: [[supply_ledger]] iterator

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
