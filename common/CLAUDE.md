# common/ — Shared Utilities

Foundational utilities used by every other package. 32 modules. The `models` module alone has 39 importers — the most-depended-on file in the project.

## Key Files

| File | Purpose | Importers |
|------|---------|-----------|
| `models.py` | Data structures (MarketSnapshot, StrategyContext, etc.) | 39 — everything uses this |
| `heartbeat.py` | Simplified 2-min monitoring loop (launchd). **Stopgap for daemon.** | 4 |
| `heartbeat_config.py` | Heartbeat config: markets, escalation thresholds, conviction bands | 3 |
| `heartbeat_state.py` | ATR computation, working state helpers | 2 |
| `thesis.py` | ThesisState dataclass — the shared contract between AI and execution | 5 |
| `conviction_engine.py` | Conviction bands → position sizing (Druckenmiller model) | 2 |
| `credentials.py` | Pluggable key backends: OWS → Keychain → Encrypted → Env → File | 8 |
| `account_resolver.py` | Wallet address resolution from `~/.hl-agent/wallets.json` (lazy) | 3 |
| `context_harness.py` | **v2/v3 core** — relevance-scored context assembly, 3000 token budget | Used by telegram_agent.py + agent_tools.py |
| `market_snapshot.py` | `build_snapshot()` + `render_snapshot()` — technicals, S/R, BBands, flags | Used by telegram_agent.py + agent_tools.py |
| `memory.py` | SQLite-based 6-table action/event log | 5 |
| `memory_consolidator.py` | Event compression for context injection | Used by context_harness |
| `memory_telegram.py` | Direct Telegram Bot API wrapper for alerts | 2 |
| `diagnostics.py` | Tool call logging, error tracking, chat logging | 3 |
| `calendar.py` | Economic calendar + catalyst tracking | 2 |
| `venue_adapter.py` | Abstract exchange interface (HL + mock implementations) | 3 |
| `market_structure.py` | OI/volume aggregation, term structure | 2 |
| `authority.py` | Per-asset delegation: agent vs manual vs off | Used by heartbeat |
| `funding_tracker.py` | Cumulative funding cost tracking | 2 |
| `watchlist.py` | **Centralized watchlist** — single source of truth for tracked markets, CRUD, HL search | Used by telegram_bot, telegram_agent, agent_tools, mcp_server, scheduled_check |

## v2/v3 Critical Path

The AI agent's context pipeline flows through `common/`:
```
telegram_agent.py → context_harness.py → market_snapshot.py → (candle_cache, thesis, memory_consolidator)
                                       → account_resolver.py → hl_proxy
```

When modifying `context_harness.py` or `market_snapshot.py`, be aware that changes affect every AI agent response.

## Upstream (what uses common/)
- `cli/` — all commands, telegram bot, AI agent, agent tools
- `cli/daemon/` — all iterators
- `modules/` — all engines
- `parent/` — exchange layer
- `scripts/` — heartbeat, scheduled check

## Downstream (what common/ uses)
- `parent/hl_proxy.py` — for exchange calls in heartbeat
- `modules/candle_cache.py` — for OHLCV data in market snapshots
- Standard library only for most modules

## Current Status (v3)
- **heartbeat.py**: Running via launchd, rate-limiting fix, lazy wallet resolution
- **thesis.py**: Works but thesis files go stale (no auto-write path yet — Phase 2)
- **conviction_engine.py**: Works, pure computation
- **context_harness.py**: Running, relevance-scored assembly for AI agent
- **market_snapshot.py**: Running, build_snapshot + render_snapshot with technicals
- **memory_consolidator.py**: Running, event compression for AI context
- **account_resolver.py**: Works after wallets.json was created
- **credentials.py**: Works, OWS + Keychain dual-write

## Testing
```bash
.venv/bin/python -m pytest tests/test_heartbeat.py tests/test_conviction_engine.py tests/test_credentials.py tests/test_heartbeat_config.py tests/test_heartbeat_state.py tests/test_context_harness.py -x -q
```
