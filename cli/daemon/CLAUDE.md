# cli/daemon/ — Daemon Architecture (Running in Production)

Hummingbot-style tick engine with tiered iterator execution. Running on mainnet in WATCH tier via launchd.

## Key Files

| File | Purpose |
|------|---------|
| `clock.py` | Main tick loop, HealthWindow error budget, circuit breaker |
| `context.py` | `TickContext` hub node, `OrderState` lifecycle tracking |
| `config.py` | `DaemonConfig` — tier, tick_interval, mock, mainnet |
| `tiers.py` | Maps tiers → iterator sets (WATCH / REBALANCE / OPPORTUNISTIC) |
| `state.py` | `StateStore` — PID management, persistent state |
| `iterators/` | All daemon iterators — one file per iterator |

**Deep dive:** [docs/wiki/components/daemon.md](../../docs/wiki/components/daemon.md) | [docs/wiki/components/risk-manager.md](../../docs/wiki/components/risk-manager.md)

## Launch

```bash
# Via launchd (production):
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.daemon.plist

# Direct (testing):
hl daemon start --tier watch --mainnet --tick 120
hl daemon start --tier watch --mock --max-ticks 10  # safest test
```

## Gotchas

- Single-instance: pacman kill pattern (SIGTERM → sleep → SIGKILL)
- Risk gate states: OPEN / COOLDOWN / CLOSED — see risk-manager.md
- HWM auto-resets when flat (no positions) to prevent phantom drawdowns
- total_equity = perps (native + xyz) + spot USDC
