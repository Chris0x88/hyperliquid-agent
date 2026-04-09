---
kind: config_file
last_regenerated: 2026-04-09 14:08
path: data/config/news_ingest.json
is_kill_switch: true
tags:
  - config
  - kill-switch
---
# Config: `news_ingest.json`

**Path**: [`data/config/news_ingest.json`](../../data/config/news_ingest.json)

**Is kill switch**: ✅ yes (has `enabled` field)

## Current contents

```json
{
  "enabled": true,
  "severity_floor": 5,
  "alert_floor": 4,
  "default_poll_interval_s": 60,
  "max_headlines_per_tick": 50,
  "headlines_jsonl": "data/news/headlines.jsonl",
  "catalysts_jsonl": "data/news/catalysts.jsonl",
  "external_catalyst_events_json": "data/daemon/external_catalyst_events.json"
}

```

## See also

- Likely consumer: [[news_ingest]] iterator

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
