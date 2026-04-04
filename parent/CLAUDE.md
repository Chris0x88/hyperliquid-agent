# parent/ — Exchange Layer + Risk Management

All communication with HyperLiquid flows through this package. `hl_proxy.py` is the single gateway. `risk_manager.py` has the composable protection chain.

## Key Files

| File | Purpose |
|------|---------|
| `hl_proxy.py` | HyperLiquid SDK wrapper. Market data, order execution, account state. |
| `risk_manager.py` | **Composable protection chain** (Freqtrade + LEAN pattern) + risk gate machine |
| `position_tracker.py` | Track open positions across ticks |
| `store.py` | Persistent state for trades and fills |
| `house_risk.py` | House-level (portfolio) risk aggregation |

## Risk Manager (Hardened)

### Risk Gate Machine
| State | Behavior |
|-------|----------|
| `OPEN` | Normal trading |
| `COOLDOWN` | Exits allowed, new entries blocked, auto-expires after 30min |
| `CLOSED` | All trading halted, exchange SLs remain |

Methods: `can_trade()`, `can_open_position()`, `record_loss()`, `record_win()`, `check_auto_expiry()`, `daily_reset()`

### Composable Protection Chain

```python
chain = ProtectionChain([
    MaxDrawdownProtection(warn_pct=15, halt_pct=25),  # LEAN-style
    StoplossGuardProtection(max_consecutive=3),         # Freqtrade-style
    DailyLossProtection(max_daily_loss_pct=5),
    RuinProtection(ruin_pct=40),                        # Hummingbot kill switch
])
gate, triggered = chain.check_all(equity=450, hwm=500, ...)
```

Each protection is independent. Chain runs ALL, worst gate wins, all reasons collected. Adding a new protection = one class + append to chain list.

Wired into daemon via `cli/daemon/iterators/risk.py`. Also: `to_dict()`/`from_dict()` for state persistence, `check_wallet_daily_loss()` for per-wallet limits, `configure_gate()` for runtime config.

## DirectHLProxy (cli/hl_adapter.py)

| Method | Purpose |
|--------|---------|
| `market_order(coin, is_buy, sz)` | IOC market order with slippage |
| `place_order(coin, is_buy, sz, price, tif)` | Limit/ALO with retry |
| `place_trigger_order(instrument, side, size, trigger_price)` | Stop-loss (tpsl="sl") |
| `place_tp_trigger_order(instrument, side, size, trigger_price)` | Take-profit (tpsl="tp") |
| `cancel_order(instrument, oid)` | Cancel by order ID |
| `get_account_state()` | Positions + equity |
| `get_xyz_state()` | xyz clearinghouse state |

## Current Status (v3.2)
- Protection chain live in daemon (4 protections active)
- Risk gate machine: OPEN/COOLDOWN/CLOSED with auto-expiry
- All RiskManager methods implemented (was 8 gaps, now 0)
- Per-wallet loss tracking for multi-wallet support
- 1694 tests passing
