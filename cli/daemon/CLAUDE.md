# cli/daemon/ — Daemon Architecture (Running in Production)

Hummingbot-style tick engine with 19 iterators, 3 tiers, and ordered execution. Running on mainnet in WATCH tier via launchd.

**Status: RUNNING (WATCH tier, ~120s ticks, mainnet)**

## Key Files

| File | Purpose |
|------|---------|
| `clock.py` | Main tick loop. HealthWindow error budget. Circuit breaker (5 failures → auto-downgrade). |
| `context.py` | `TickContext` — hub node. `OrderState` enum for order lifecycle tracking. |
| `config.py` | `DaemonConfig` — tier, tick_interval, mock, mainnet |
| `tiers.py` | Maps tiers → iterator sets. WATCH (10), REBALANCE (+7), OPPORTUNISTIC (+2) |
| `state.py` | `StateStore` — PID management, persistent state |
| `roster.py` | `Roster` — manages strategy slots |

## Risk Architecture (Hardened)

### Composable Protection Chain (Freqtrade + LEAN pattern)

`parent/risk_manager.py` — `ProtectionChain` runs independent protections, worst gate wins:

| Protection | Trigger | Gate |
|-----------|---------|------|
| `MaxDrawdownProtection` | 15% drawdown → COOLDOWN, 25% → CLOSED | Position-aware (flat = no alert) |
| `StoplossGuardProtection` | 3 consecutive losses → COOLDOWN (30min) | Auto-expires |
| `DailyLossProtection` | 5% daily loss → CLOSED | Resets daily |
| `RuinProtection` | 40% drawdown → CLOSED + close all | Kill switch |

Chain wired into `RiskIterator.tick()`. Results merged with existing pre_round_check. Single consolidated alert per tick (no spam).

### Health Window (Passivbot error budget)

`common/telemetry.py` → `HealthWindow` — 15min sliding window tracking: orders_placed, cancelled, fills, errors, timeouts. If errors ≥ 10/window → auto-downgrade tier.

Wired into `Clock._tick()`: records errors on iterator failures, records order events in `_execute_orders()`.

### Alert System

`iterators/telegram.py` — Severity-aware dedup cooldowns:
- critical: 15min (persistent conditions re-alert)
- warning: 1hr
- info: 4hr

Escalation: if same critical alert fires twice → "🚨 ACTION REQUIRED" prefix.

### HWM / Drawdown

`iterators/account_collector.py`:
- Auto-resets HWM when flat (no positions) — no phantom drawdowns
- total_equity = perps (native + xyz) + spot USDC
- Alerts only fire when has_positions == True

### Risk Gate States

| State | Behavior |
|-------|----------|
| `OPEN` | Normal trading |
| `COOLDOWN` | Exits allowed, new entries blocked |
| `CLOSED` | All trading halted, exchange SLs remain |

Gate transitions: `record_loss()` escalates OPEN→COOLDOWN→CLOSED. `check_auto_expiry()` de-escalates COOLDOWN→OPEN after 30min. `daily_reset()` clears everything.

## MarketStructure Iterator

Computes `MarketSnapshot` for ALL watchlist coins (not just position coins). Self-fetches prices from both clearinghouses for coins not in Connector's instrument list.

## Process Management

- Single-instance: pacman kill pattern (SIGTERM → sleep → SIGKILL)
- LaunchD: `com.hyperliquid.daemon` with KeepAlive=true
- PID file: `data/daemon/daemon.pid`

## Launch

```bash
# Via launchd (production):
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.daemon.plist

# Direct (testing):
hl daemon start --tier watch --mainnet --tick 120
hl daemon start --tier watch --mock --max-ticks 10  # safest test
```

## Testing
```bash
.venv/bin/python -m pytest tests/test_integration_phase3.py tests/test_integration_phase4.py tests/test_integration_safety.py -x -q
```
