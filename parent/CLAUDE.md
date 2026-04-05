# parent/ — Exchange Layer + Risk Management

All HyperLiquid communication flows through `hl_proxy.py`. Risk management via composable protection chain in `risk_manager.py`.

## Key Files

| File | Purpose |
|------|---------|
| `hl_proxy.py` | HyperLiquid SDK wrapper — market data, orders, account state |
| `risk_manager.py` | Composable protection chain + risk gate machine |
| `position_tracker.py` | Track open positions across ticks |
| `store.py` | Persistent state for trades and fills |
| `house_risk.py` | Portfolio-level risk aggregation |

**Deep dive:** [docs/wiki/components/risk-manager.md](../docs/wiki/components/risk-manager.md)

## Gotchas

- Risk gate states: OPEN → COOLDOWN → CLOSED (worst gate wins)
- `DirectHLProxy` in `cli/hl_adapter.py` is the adapter used by bot commands
- xyz perps need `dex='xyz'` in ALL API calls
