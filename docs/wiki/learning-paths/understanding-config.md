# Learning Path: Configuration System

How config files work, where they live, how they're loaded, and how the Pydantic schema validates them. Read these files in order.

---

## 1. `data/config/` -- Directory listing

**Start here.** Scan the 25 config files to get the lay of the land before reading any code.

| File | Format | Purpose | Loaded by |
|------|--------|---------|-----------|
| `architect.json` | JSON | Mechanical self-improvement iterator config | `iterators/architect.py` |
| `bot_classifier.json` | JSON | Sub-system 4 kill switch + params | `iterators/bot_classifier.py` |
| `entry_critic.json` | JSON | Trade entry grading iterator config | `iterators/entry_critic.py` |
| `escalation_config.json` | JSON | Liquidation + drawdown tier thresholds | `common/config_schema.py` (Pydantic) |
| `heatmap.json` | JSON | Sub-system 3 liquidity heatmap kill switch | `iterators/heatmap.py` |
| `lab.json` | JSON | Strategy development pipeline kill switch | `iterators/lab.py` |
| `lesson_author.json` | JSON | Trade lesson detection iterator config | `iterators/lesson_author.py` |
| `market_config.json` | JSON | Legacy market params (mostly superseded by `markets.yaml`) | `cli/config.py` |
| `markets.yaml` | YAML | Per-instrument rules: direction bias, asset class, max leverage | `common/markets.py` (via Pydantic) |
| `memory_backup.json` | JSON | Backup interval + retention policy for memory.db | `iterators/memory_backup.py` |
| `model_config.json` | JSON | AI model routing: which model for which task | `cli/telegram_agent.py` |
| `news_feeds.yaml` | YAML | RSS/iCal feed URLs for sub-system 1 | `iterators/news_ingest.py` |
| `news_ingest.json` | JSON | Sub-system 1 kill switch + polling interval | `iterators/news_ingest.py` |
| `news_rules.yaml` | YAML | Catalyst classification rules for news | `iterators/news_ingest.py` |
| `oil_botpattern.json` | JSON | Sub-system 5 master config: sizing ladder, drawdown brakes, instruments | `iterators/oil_botpattern.py` (Pydantic) |
| `oil_botpattern_patternlib.json` | JSON | Sub-system 6 L3 pattern library growth config | `iterators/oil_botpattern_patternlib.py` |
| `oil_botpattern_reflect.json` | JSON | Sub-system 6 L2 structural reflection config | `iterators/oil_botpattern_reflect.py` |
| `oil_botpattern_shadow.json` | JSON | Sub-system 6 L4 counterfactual shadow eval config | `iterators/oil_botpattern_shadow.py` |
| `oil_botpattern_tune.json` | JSON | Sub-system 6 L1 bounded auto-tune config | `iterators/oil_botpattern_tune.py` |
| `profit_rules.json` | JSON | Profit lock / trailing stop rules | `iterators/profit_lock.py` |
| `risk_caps.json` | JSON | Per-instrument sizing multipliers and ATR floors | `common/config_schema.py` (Pydantic) |
| `supply_auto_extract.yaml` | YAML | Auto-extraction rules for supply disruption data | `iterators/supply_ledger.py` |
| `supply_ledger.json` | JSON | Sub-system 2 kill switch + aggregation params | `iterators/supply_ledger.py` |
| `thesis_updater.json` | JSON | Haiku-powered thesis conviction updater config | `iterators/thesis_updater.py` |
| `watchlist.json` | JSON | Tracked markets with display names, aliases, categories | `common/watchlist.py` (Pydantic) |

**What you'll learn:** The full inventory of runtime-tuneable config surfaces, the split between JSON and YAML, and which component owns each file.

---

## 2. `common/config_schema.py` -- Pydantic validation layer

**The typed gateway.** This module defines Pydantic v2 models for the five most critical config files:

- `OilBotPatternConfig` (line ~64) -- 40+ typed fields with nested `SizingRung`, `DrawdownBrakes`, `AdaptiveConfig`
- `MarketsConfig` (line ~132) -- per-instrument `MarketSpec` with direction bias, asset class, max leverage
- `WatchlistEntry` (line ~144) -- display name, coin, aliases, category (top-level is a list, uses `TypeAdapter`)
- `RiskCapsConfig` (line ~167) -- per-instrument sizing multipliers
- `EscalationConfig` (line ~185) -- liquidation and drawdown tier thresholds (L1/L2/L3)

Key design patterns:

- `extra="forbid"` on all models -- unknown keys raise immediately, preventing typo-driven silent failures
- `_strip_comments` validator (line ~108) -- removes `_comment` keys before validation (JSON doesn't support comments natively)
- `CONFIG_REGISTRY` dict (line ~206) -- maps short names to model classes
- `_FILE_MAP` dict (line ~214) -- maps short names to filenames
- `load_config()` (line ~223) -- the single entry point: `load_config("oil_botpattern")` returns a validated `OilBotPatternConfig`

**What you'll learn:** How typed validation catches bad config before it reaches runtime, the registry pattern, and how YAML vs JSON is handled transparently.

---

## 3. `cli/daemon/iterators/oil_botpattern.py` lines ~684-700 -- Hot-reload pattern

**How iterators consume config at runtime.** The `_reload_config()` method (line ~684) shows the standard pattern used across iterators:

1. Read raw JSON from disk (`Path(self._config_path).read_text()`)
2. Validate through Pydantic (`OilBotPatternConfig.model_validate(raw)`)
3. Convert to plain dict (`validated.model_dump()`) for runtime use
4. If validation fails, fall back to raw dict with warning log
5. Separately load risk caps from the path specified in config

This method is called at the TOP of every `tick()` call (line ~142), so config changes on disk take effect within one tick interval (typically 60s) without daemon restart.

Other iterators (e.g. `oil_botpattern_reflect.py` line ~53) use a simpler pattern: direct `json.loads()` without Pydantic, relying on `.get()` defaults. The Pydantic path is only used for the five registered schemas.

**What you'll learn:** The hot-reload mechanism, the graceful fallback on validation failure, and why config changes are near-instant.

---

## 4. `cli/config.py` -- Legacy TradingConfig pattern

**The older approach, still in use.** `TradingConfig` (line ~12) is a `@dataclass` loaded from YAML via `from_yaml()` (line ~52):

- Reads YAML, filters to known dataclass fields, constructs instance
- Contains strategy params, risk limits (max position, max notional, max leverage), execution flags
- `to_risk_limits()` (line ~60) converts to the `RiskLimits` struct used by the parent risk manager
- `get_private_key()` (line ~83) delegates to `common.credentials.resolve_private_key()`

This predates the Pydantic schema layer. New config should use `config_schema.py`; this file exists for the CLI entry point and legacy strategy configs.

**What you'll learn:** The evolution from bare dataclasses to Pydantic models, and how the older risk-limit plumbing works.

---

## 5. `web/api/routers/config.py` + `web/api/readers/config_reader.py` -- Dashboard config access

**How the web dashboard reads and writes config.**

The router (`config.py`) exposes three endpoints:

- `GET /api/config/` -- lists all config files with metadata (name, type, size, modified time)
- `GET /api/config/{filename}` -- reads and returns parsed JSON/YAML
- `PUT /api/config/{filename}` -- updates a config file with automatic `.bak` backup

The reader (`config_reader.py`) implements the data access:

- `list_configs()` -- iterates `data/config/`, returns metadata for `.json`/`.yaml`/`.yml` files
- `read_config()` -- parses JSON or YAML based on file extension
- `write_config()` -- creates `.bak` backup, writes to `.tmp`, then atomically renames

Safety: the router validates filenames (no `/`, `\`, `..`) and restricts to JSON/YAML extensions.

**What you'll learn:** How the web control plane provides a safe read/write interface to the same config files the daemon hot-reloads.

---

## Config loading flow

```
data/config/*.json|yaml         (files on disk)
        |
        v
  ┌──────────────���──┐
  │ load_config()    │  <-- common/config_schema.py
  │ Pydantic v2      │      5 registered schemas
  │ extra="forbid"   │      TypeAdapter for watchlist
  └────────┬────────┘
           |
    ┌──────┴──────┐
    |             |
    v             v
 Iterator        Web API
 _reload_config  GET /api/config/{file}
 (every tick)    PUT /api/config/{file}
                   |
                   v
              FileConfigReader
              atomic write + .bak backup
```

Iterators that don't use `load_config()` (most sub-system configs) read JSON directly and use `.get()` with defaults. The Pydantic layer is opt-in for the configs that benefit most from strict typing.
