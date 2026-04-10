---
title: Heartbeat
description: The launchd-managed heartbeat process that runs every 2 minutes, sending account state and alerts to Telegram.
---

## Overview

`common/heartbeat.py` is a lightweight process managed by launchd that runs every 2 minutes. It's separate from the main daemon clock and focused on account monitoring and alert delivery.

---

## What It Does Each Run

1. Fetches account state from both clearinghouses (native + xyz)
2. Checks all positions for missing SL/TP — places them if absent
3. Checks liquidation cushion for each position
4. Sends Telegram alerts for any issues found
5. Updates `data/memory/working_state.json` with current ATR and prices
6. Checks if the main daemon is healthy (via PID file)

---

## Alert Thresholds

| Condition | Default threshold | Alert severity |
|-----------|-----------------|----------------|
| Missing SL or TP | Any position | Critical |
| Liquidation cushion | < 15% (configurable) | Warning → Critical |
| Daemon not running | PID file missing | Warning |
| Account equity drop | > 10% in 1h | Warning |

Thresholds are configurable via `data/config/heartbeat_config.json`.

---

## launchd Configuration

The heartbeat plist (`com.hyperliquid.heartbeat.plist`) configures:

```xml
<key>StartInterval</key>
<integer>120</integer>
<key>KeepAlive</key>
<false/>
```

It runs once and exits — launchd re-runs it every 120 seconds. This is lighter than a long-lived process.

---

## ATR Calculation

The heartbeat computes ATR (Average True Range) for each thesis market:
- Period: 14 candles (configurable)
- Timeframe: 1-hour candles from candle cache
- Stored in `working_state.json` for use by the daemon's stop-placement logic

ATR-based stops: stop loss = entry price - (ATR multiplier × ATR). Default multiplier is 2.0x.
