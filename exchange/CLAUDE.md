# exchange/ — Exchange Layer + Risk Management

All HyperLiquid communication flows through `hl_proxy.py`. Risk management via composable protection chain in `risk_manager.py`.

## Key Files

| File | Purpose |
|------|---------|
| `hl_proxy.py` | HyperLiquid SDK wrapper — market data, orders, account state |
| `hl_adapter.py` | `DirectHLProxy` / `DirectMockProxy` — exchange adapter used by bot commands and the agent |
| `helpers.py` | Generic exchange data helpers — funding, OI, price change, coin normalization |
| `risk_manager.py` | Composable protection chain + risk gate machine |
| `position_tracker.py` | Track open positions across ticks |
| `store.py` | Persistent state for trades and fills |
| `house_risk.py` | Portfolio-level risk aggregation |
| `sdk_patches.py` | Monkey-patches for HyperLiquid SDK quirks |
| `order_book.py` | Order book tracking |
| `order_types.py` | Order type definitions |
| `parent_order.py` | Parent order lifecycle |
| `portfolio_risk.py` | Portfolio-level risk calculations |
| `routing.py` | Order routing logic |
| `twap.py` | TWAP execution engine |

> Merged from `parent/` + `execution/` in Phase 1 domain refactor.

**Deep dive:** [docs/wiki/components/risk-manager.md](../docs/wiki/components/risk-manager.md)

## Learning Paths

- [Thesis to Order](../docs/wiki/learning-paths/thesis-to-order.md) — how thesis conviction becomes a live order through the exchange layer
- [Understanding Data Flow](../docs/wiki/learning-paths/understanding-data-flow.md) — exchange data flow and position lifecycle

## Gotchas

- Risk gate states: OPEN -> COOLDOWN -> CLOSED (worst gate wins)
- `DirectHLProxy` in `exchange/hl_adapter.py` is the adapter used by bot commands
- xyz perps need `dex='xyz'` in ALL API calls
