# Risk Manager

Deterministic policy-based risk enforcement. No ML-driven decisions. Defined in `parent/risk_manager.py`.

## Design Pattern: Composable Protection Chain

Inspired by Freqtrade + LEAN. Each protection is an independent class. The `ProtectionChain` runs ALL protections, and the **worst gate wins** (most restrictive). All trigger reasons are collected. Adding a new protection means writing one class and appending it to the chain.

```python
chain = ProtectionChain([
    MaxDrawdownProtection(warn_pct=15, halt_pct=25),
    StoplossGuardProtection(max_consecutive=3),
    DailyLossProtection(max_daily_loss_pct=5),
    RuinProtection(ruin_pct=40),
])
gate, triggered = chain.check_all(equity, hwm, ...)
```

## Individual Protections

| Protection | Trigger | Gate Result |
|-----------|---------|-------------|
| `MaxDrawdownProtection` | 15% drawdown | COOLDOWN |
| | 25% drawdown | CLOSED |
| `StoplossGuardProtection` | 3 consecutive losses | COOLDOWN (30min auto-expiry) |
| `DailyLossProtection` | 5% daily loss | CLOSED |
| `RuinProtection` | 40% drawdown | CLOSED + close all positions (kill switch) |

Position-aware: if the account is flat (no positions), drawdown alerts do not fire.

## Risk Gate State Machine

```
OPEN  ---(consecutive losses or drawdown)--->  COOLDOWN  ---(loss during cooldown)--->  CLOSED
  ^                                                |
  |                                                |
  +---------(30min auto-expiry)--------------------+
```

| State | Behavior |
|-------|----------|
| `OPEN` | Normal trading. All operations permitted. |
| `COOLDOWN` | Exits allowed, new entries blocked. Auto-expires after 30min. |
| `CLOSED` | All trading halted. Exchange stop-losses remain active. |

Key methods: `record_loss()`, `record_win()`, `check_auto_expiry()`, `check_drawdown()`, `check_daily_loss()`, `daily_reset()`.

## RiskLimits

Policy limits configured via `RiskLimits` dataclass:

- `max_position_qty` -- per-instrument position cap
- `max_notional_usd` -- per-instrument notional cap
- `max_order_size` -- single order size cap
- `max_daily_drawdown_pct` -- daily drawdown trigger
- `max_leverage` -- portfolio leverage cap
- `reserve_factor_pct` -- insurance fund set-aside

Production defaults via `RiskLimits.mainnet_defaults()`.

## Additional Enforcement

- **Circuit breaker:** if any instrument moves >15% in a single tick, safe mode activates
- **Reduce-only mode:** auto-triggered when position or notional limits are reached
- **Per-wallet blocking:** `blocked_wallets` dict for multi-wallet loss isolation

## Integration with Daemon

The `RiskIterator` (`cli/daemon/iterators/risk.py`) wires the protection chain into the tick loop. Results merge with `pre_round_check()`. A single consolidated alert per tick prevents spam.
