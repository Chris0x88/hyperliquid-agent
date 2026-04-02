# common/ — Shared Utilities

Foundational utilities used by every other package. 25 modules. The `models` module alone has 39 importers — it's the most-depended-on file in the project.

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
| `account_resolver.py` | Wallet address resolution from `~/.hl-agent/wallets.json` | 3 |
| `venue_adapter.py` | Abstract exchange interface (HL + mock implementations) | 3 |
| `market_snapshot.py` | Real-time market data model + rendering | 3 |
| `market_structure.py` | OI/volume aggregation, term structure | 2 |
| `memory.py` | SQLite-based action/event log | 5 |
| `memory_telegram.py` | Direct Telegram Bot API wrapper for alerts | 2 |
| `diagnostics.py` | Tool call logging, error tracking, chat logging | 3 |
| `calendar.py` | Economic calendar + catalyst tracking | 2 |
| `consolidation.py` | Price consolidation detection | 1 |
| `funding_tracker.py` | Cumulative funding cost tracking | 2 |
| `telemetry.py` | Execution metrics export | 2 |
| `trajectory.py` | Session trajectory JSONL logging | 2 |

## Upstream (what uses common/)
- `cli/` — all commands
- `cli/daemon/` — all iterators
- `modules/` — all engines
- `parent/` — exchange layer
- `scripts/` — heartbeat, scheduled check

## Downstream (what common/ uses)
- `parent/hl_proxy.py` — for exchange calls in heartbeat
- Standard library only for most modules

## Current Status
- **heartbeat.py**: Running via launchd, but simplified subset of daemon. Has rate-limiting fix and lazy wallet resolution from this session.
- **thesis.py**: Works but thesis files go stale because nothing writes them automatically.
- **conviction_engine.py**: Works, pure computation.
- **credentials.py**: Works, OWS + Keychain dual-write.
- **account_resolver.py**: Works after wallets.json was created this session.

## Future Direction (Phase 2)
- Heartbeat will be replaced by full daemon (`cli/daemon/`). Heartbeat code stays as fallback but launchd switches to daemon.
- `memory_telegram.py` alerts reduced to actions-only + hourly + failure alerts.

## Testing
```bash
.venv/bin/python -m pytest tests/test_heartbeat.py tests/test_conviction_engine.py tests/test_credentials.py tests/test_heartbeat_config.py tests/test_heartbeat_state.py -x -q
```
