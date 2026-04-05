# Daemon (Tick Engine)

Hummingbot-inspired tick engine that runs iterators in ordered sequence every ~120 seconds. Production status: **running in WATCH tier on mainnet via launchd**.

## How It Works

`cli/daemon/clock.py` defines the `Clock` class. Each tick:

1. Check control file for runtime commands
2. Rebuild active iterator set for the current tier
3. Call `iterator.tick(ctx)` for each active iterator in order
4. Execute queued `OrderIntent`s (if any)
5. Persist state via `StateStore`

The `TickContext` (defined in `context.py`) is the hub node passed to every iterator. It carries account state, thesis states, market snapshots, alerts, and queued orders.

## Tiers

Defined in `cli/daemon/tiers.py`. Each tier activates a different set of iterators:

| Tier | Purpose | Key additions over previous |
|------|---------|---------------------------|
| `watch` | Monitor-only. Alerts, no trades. | account_collector, thesis_engine, risk, telegram |
| `rebalance` | Active position management. | execution_engine, exchange_protection, guard, rebalancer, profit_lock, funding_tracker |
| `opportunistic` | Full autonomous trading. | radar, pulse (opportunity scanners) |

See `TIER_ITERATORS` in `tiers.py` for the exact iterator sets per tier.

## Iterators

All iterators live in `cli/daemon/iterators/`. Each implements `on_start(ctx)`, `tick(ctx)`, and `on_stop()`. See that directory for the full list.

Key iterators:
- **account_collector** -- always first; fetches live account state from both clearinghouses
- **connector** -- market data connection; failure aborts the daemon
- **market_structure** -- computes `MarketSnapshot` for all watchlist coins
- **thesis_engine** -- reads AI thesis files into `ctx.thesis_states`
- **execution_engine** -- conviction-based sizing (REBALANCE tier+)
- **risk** -- wires the `ProtectionChain` into the tick loop
- **telegram** -- severity-aware alert routing with dedup cooldowns

## Risk Gate Integration

The daemon checks `RiskGate` state every tick. See [risk-manager.md](risk-manager.md) for the OPEN/COOLDOWN/CLOSED state machine.

## Health Window

`HealthWindow` (from `common/telemetry.py`) tracks errors in a 15-minute sliding window. If errors exceed the budget (10/window), the daemon auto-downgrades tier. The `Clock` also circuit-breaks individual iterators after 5 consecutive failures.

## Process Management

- **Single instance:** PID file at `data/daemon/daemon.pid`, pacman kill pattern (SIGTERM, sleep, SIGKILL)
- **launchd plist:** `com.hyperliquid.daemon` with `KeepAlive=true`

## Start/Stop

```bash
# Production (launchd):
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.daemon.plist

# Testing:
hl daemon start --tier watch --mainnet --tick 120
hl daemon start --tier watch --mock --max-ticks 10
```
