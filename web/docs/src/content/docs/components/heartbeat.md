---
title: Protection & Monitoring
description: Daemon iterators that guard every position — read-only audits, mandatory SL/TP placement, liquidation alerts, and rollover monitoring.
---

## Overview

There is no separate heartbeat process or configuration file. All protection and monitoring runs as daemon iterators inside the tick engine. Each tick, these iterators verify positions, place missing orders, and alert on dangerous conditions.

---

## protection_audit (Read-Only Verifier)

**Source:** `cli/daemon/iterators/protection_audit.py`
**Tier:** WATCH and above (runs at every tier)

The protection audit is strictly read-only. It does NOT place orders. Each tick it:

1. Scans every open position across both clearinghouses (native + xyz)
2. Checks that each position has both a stop-loss and take-profit order on the exchange
3. If any SL or TP is missing, sends a **Critical** alert to Telegram
4. Logs the audit result to state

This iterator exists so that even in WATCH tier (where no orders are placed), you get immediate notification if protection is missing.

---

## exchange_protection (SL/TP Placement)

**Source:** `cli/daemon/iterators/exchange_protection.py`
**Tier:** REBALANCE and above only

This is the iterator that actually writes to the exchange. Each tick it:

1. Scans every open position for missing SL or TP orders
2. Computes stop-loss from ATR (ATR values come from the `market_structure` iterator)
3. Computes take-profit from thesis `take_profit_price`, falling back to mechanical 5x ATR if no thesis target
4. Places the missing orders on the exchange
5. Enforces the ruin floor (25% drawdown halts entries, 40% drawdown closes everything)

### Stop-Loss Calculation

- ATR period: 14 candles on the 1-hour timeframe
- Default multiplier: 2.0x ATR below entry for longs
- ATR values are stored in `data/memory/working_state.json`

### The protection_audit vs exchange_protection Distinction

| | protection_audit | exchange_protection |
|---|---|---|
| **Action** | Read-only, alerts only | Places orders on exchange |
| **Available tier** | WATCH+ (all tiers) | REBALANCE+ only |
| **Missing SL/TP** | Sends Telegram alert | Places the order |
| **Ruin floor** | Does not enforce | Enforces (halts/closes) |

Both run every tick when active. In REBALANCE+, protection_audit catches anything exchange_protection might miss in the same tick.

---

## liquidation_monitor (Cushion Alerts)

**Source:** `cli/daemon/iterators/liquidation_monitor.py`
**Tier:** WATCH and above

Monitors the margin cushion (distance to liquidation price) for each position and sends tiered alerts:

| Cushion Level | Severity | Action |
|--------------|----------|--------|
| Healthy (above threshold) | None | No alert |
| Below warning threshold | Warning | Telegram alert |
| Below critical threshold | Critical | Telegram alert with position details |

Note: A 6.5% cushion at 11x leverage is normal operating range for this system. The critical threshold is calibrated to avoid false alarms at expected leverage levels.

---

## brent_rollover_monitor

**Source:** `cli/daemon/iterators/brent_rollover_monitor.py`
**Tier:** WATCH and above

Monitors Brent crude oil contract expiry dates and alerts before rollover events. This prevents getting caught in expiry-related price dislocations or forced closes.

---

## Alert Routing

All protection iterators send alerts through the `telegram` iterator's severity-aware routing:

- **Info:** Logged, no notification
- **Warning:** Telegram message, dedup cooldown prevents spam
- **Critical:** Telegram message with high-priority formatting, shorter cooldown

Alerts are deduplicated — the same condition will not fire repeatedly within the cooldown window.
