---
title: Sizing Rules
description: Conviction-based position sizing, mandatory stop rules, and account-level ruin prevention.
---

import { Aside } from '@astrojs/starlight/components';

## Core Philosophy

Druckenmiller-style sizing: stay fully allocated, adjust leverage as confidence shifts. High conviction = aggressive leverage. Lower conviction = reduce leverage, keep position.

The system operationalizes this through thesis conviction scores that directly drive position size.

---

## Mandatory SL/TP Rule

<Aside type="danger" title="No exceptions">
Every position MUST have both a stop-loss AND a take-profit on the exchange at all times. The heartbeat daemon enforces this every 2 minutes. If either is missing, it places them automatically.
</Aside>

### Stop Loss

- **Method:** ATR-based — 3x ATR below entry for longs
- **Minimum:** Must provide liquidation buffer safety (exchange checks)
- **Type:** Exchange-native trigger order (fires even if heartbeat is down)
- **Never:** Fixed-percentage stops on thesis-driven positions — they get hunted

### Take Profit

- **Primary:** `take_profit_price` from thesis file
- **Fallback:** Mechanical 5x ATR above entry if no thesis TP
- **Type:** Exchange-native trigger order

---

## Conviction Bands

| Conviction | Target Size (% equity) | Max Leverage |
|-----------|----------------------|-------------|
| 0.8–1.0 | 20% equity | 15x |
| 0.5–0.8 | 12% equity | 10x |
| 0.2–0.5 | 6% equity | 5x |
| 0.0–0.2 | 0% (exit signal) | 0x |

Conviction values are set in thesis files. Values auto-taper with age:
- After 7–14 days: linear taper toward 0.3
- After 14 days: hard floor at 0.3

---

## Time-Aware Leverage Caps

| Session | Leverage cap | Rationale |
|---------|-------------|-----------|
| Weekend | 50% of normal | Thin liquidity, stop hunts |
| Asia open on oil | 7x max | Higher volatility session |
| Normal hours | Full bands | Standard sizing |

---

## Entry Scaling

- Start smaller, scale in on confirmation
- Scale out on $5+ profit per barrel to reset lower entries
- Active trading around a core position is encouraged
- Never chase entries — position ahead of events

---

## Exit Rules

| Exit trigger | Action |
|-------------|--------|
| Thesis invalidation | Exit immediately |
| Take-profit hit | Full or partial exit per thesis |
| Geopolitical reversal | Exit on confirmation |
| Account 25% drawdown | Halt all new entries |
| Account 40% drawdown | Close ALL positions |

**Do not exit on fixed-percentage drawdowns** — thesis-invalidation exits only for planned positions.

**On weekends:** Reduce leverage if needed, but do not close positions unless thesis is invalidated.

---

## Liquidation Cushion

The heartbeat monitors liquidation distance for every open position:

- **Default alert threshold:** 15% cushion (configurable)
- **Critical threshold:** 10% cushion → urgent Telegram alert
- **6.5% cushion at 11x leverage is normal** — do not over-react to the default thresholds

Adjust thresholds in `data/config/heartbeat_config.json` to match your actual leverage levels.
