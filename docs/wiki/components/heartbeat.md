# Heartbeat

Lightweight position auditor that runs every 2 minutes via launchd. Pure Python, no AI dependency. Defined in `common/heartbeat.py` with config in `common/heartbeat_config.py`.

## Purpose

The heartbeat exists because the previous 5-minute AI check-in system failed due to context loss between sessions. Heartbeat is the safety net: it ensures stops exist, monitors liquidation proximity, and escalates when positions are in danger.

## What It Does Each Cycle

1. Fetch account state from both clearinghouses (native + xyz) and spot balances
2. Compute ATR-based stop prices for each position (`compute_stop_price()`)
3. Check existing orders via `frontendOpenOrders` -- detect if SL/TP are missing
4. Run escalation checks (liquidation proximity, drawdown levels)
5. Monitor spike/dip conditions for profit-taking or dip-buying
6. Send Telegram alerts at appropriate severity levels
7. Persist state to `data/memory/working_state.json`

## Multi-Wallet Monitoring

Heartbeat monitors both the main account (oil, gold, silver on xyz perps) and the vault account (BTC Power Law). Each wallet is checked against its own clearinghouse. xyz perps use `dex='xyz'` in all API calls.

## Stop-Loss Enforcement

`compute_stop_price()` calculates stops from ATR with constraints:
- Base: entry price +/- (ATR x multiplier)
- Min distance: at least N% from current price
- Liquidation buffer: at least N% away from liquidation price
- Returns the most conservative (safest) stop satisfying all constraints

## Alert Escalation

Three tiers of liquidation alerts (configured in `EscalationConfig`):

| Level | Trigger | Action |
|-------|---------|--------|
| L1 | Liq within 6% | Alert only |
| L2 | Liq within 4% | Deleverage (reduce position size) |
| L3 | Liq within 2% | Emergency -- target leverage reduction |

Drawdown escalation follows a similar pattern (L1: 5%, L2: 8% with 25% cut, L3: 12% with 50% cut). Cooldown timers prevent action spam.

## Spike/Dip Detection

`SpikeConfig` handles sudden moves:
- **Spike profit** (>3% in 10min): take 15% off the table
- **Dip add** (>2% drop): add 10% if liquidation is safe and drawdown is within limits

## Relationship to Daemon

The daemon replaced heartbeat as the primary monitoring system. Heartbeat continues running as an independent safety net via launchd. It is simpler and has no dependency on the daemon's iterator framework.

## launchd Config

- Plist: `~/Library/LaunchAgents/com.hyperliquid.heartbeat.plist`
- Interval: 120 seconds
- PID enforcement and log rotation at 1MB
