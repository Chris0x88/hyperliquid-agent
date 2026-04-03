# cli/daemon/ — Daemon Architecture (The Real Workhorse)

Hummingbot-style tick engine with 19 iterators, 3 tiers, and ordered execution. This is the full system — the heartbeat in `common/heartbeat.py` is a simplified stopgap.

**Status: BUILT, NOT RUNNING. Phase 2 activates this.**

## Key Files

| File | Purpose |
|------|---------|
| `clock.py` | Main tick loop. Configurable interval (default 60s). Circuit breaker (5 failures → auto-downgrade). Mock mode. Max-ticks. Graceful shutdown. |
| `context.py` | `TickContext` — carries all data between iterators each tick. 21 importers. Hub node. |
| `config.py` | `DaemonConfig` — tier, tick_interval, mock, mainnet, max_ticks, circuit_breaker |
| `tiers.py` | Maps tiers → iterator sets. WATCH (10), REBALANCE (+7), OPPORTUNISTIC (+2) |
| `state.py` | `StateStore` — persistent daemon state across restarts |
| `roster.py` | `Roster` — manages strategy slots for rebalancer |

## Iterator Inventory (19 total)

### WATCH tier (observation only, safe):
| Iterator | File | Purpose | Tick Rate |
|----------|------|---------|-----------|
| Connector | `iterators/connector.py` | Fetch prices, positions, balances from HL | Every tick |
| AccountCollector | `iterators/account_collector.py` | Timestamped equity snapshots, HWM, drawdown | 5 min |
| MarketStructure | `iterators/market_structure_iter.py` | Pre-compute 1h/4h technicals | 5 min |
| ThesisEngine | `iterators/thesis_engine.py` | Load conviction from thesis files | Every tick |
| Liquidity | `iterators/liquidity.py` | Regime detection: NORMAL/LOW/WEEKEND/DANGEROUS | Every tick |
| Risk | `iterators/risk.py` | Risk gate: OPEN/COOLDOWN/CLOSED | Every tick |
| AutoResearch | `iterators/autoresearch.py` | 30-min learning loop evaluation | 30 min |
| MemoryConsolidation | `iterators/memory_consolidation.py` | Compress old events | 1 hour |
| Journal | `iterators/journal.py` | Log tick snapshot to ticks.jsonl | Every tick |
| Telegram | `iterators/telegram.py` | Send alerts, rate-limited | As needed |

### REBALANCE tier (adds position management):
| Iterator | File | Purpose |
|----------|------|---------|
| ExecutionEngine | `iterators/execution_engine.py` | Conviction → position sizing (Druckenmiller bands) |
| ExchangeProtection | `iterators/exchange_protection.py` | Place liq-buffer SL (ruin prevention only) |
| Guard | `iterators/guard.py` | Trailing stops, profit protection |
| Rebalancer | `iterators/rebalancer.py` | Run roster strategies |
| ProfitLock | `iterators/profit_lock.py` | Sweep 25% realized profits |
| FundingTracker | `iterators/funding_tracker.py` | Hourly funding cost accounting |
| CatalystDeleverage | `iterators/catalyst_deleverage.py` | Pre-event leverage reduction |

### OPPORTUNISTIC tier (adds scanning):
| Iterator | File | Purpose |
|----------|------|---------|
| Radar | `iterators/radar.py` | Opportunity scanner (5 min) |
| Pulse | `iterators/pulse.py` | Momentum detector (2 min) |

## Execution Order (per tick)
```
1. Connector → 2. AccountCollector → 3. MarketStructure →
4. ThesisEngine → 5. Liquidity → 6. Risk →
7. ExchangeProtection → 8. Guard → 9. ExecutionEngine →
10. Rebalancer → 11. ProfitLock → 12. FundingTracker →
13. CatalystDeleverage → 14. Radar → 15. Pulse →
16. AutoResearch → 17. Journal → 18. MemoryConsolidation →
19. Telegram
```

## Safety
- **Circuit breaker**: 5 consecutive tick failures → auto-downgrade tier
- **Mock mode**: `--mock` → no real orders
- **Max ticks**: `--max-ticks N` → auto-stop
- **Ruin prevention**: 25% drawdown halts entries, 40% closes all (unconditional)
- **Graceful shutdown**: SIGINT/SIGTERM handled

## Relationship to Current Running System

The heartbeat (`common/heartbeat.py`) is a simplified version that handles:
- Position monitoring + stop placement
- Escalation alerts
- Conviction engine integration
- Hourly status reports

The daemon adds 12 more capabilities: guard trailing stops, radar scanning, pulse detection, auto-research, journal, memory consolidation, profit locking, funding tracking, catalyst deleverage, and full execution engine.

**Phase 2 plan:** Start daemon in WATCH alongside heartbeat for 24h comparison. Then switch launchd to daemon, keep heartbeat as fallback.

## CLI Commands
```bash
hl daemon start --tier watch --mock --max-ticks 10   # Safest test
hl daemon start --tier watch --max-ticks 100          # Real data, no trading
hl daemon start --tier rebalance --mainnet            # Production (careful!)
hl daemon stop                                         # Graceful stop
hl daemon status                                       # Health check
```

## Testing
```bash
.venv/bin/python -m pytest tests/test_integration_phase3.py tests/test_integration_phase4.py tests/test_integration_safety.py -x -q
```
