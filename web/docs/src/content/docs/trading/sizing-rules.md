---
title: Sizing Rules
description: Conviction-based position sizing, ATR stops, mandatory SL/TP, leverage caps, and liquidation cushion thresholds.
---

import { Aside } from '@astrojs/starlight/components';

## Core Philosophy

Druckenmiller-style sizing: stay fully allocated, adjust leverage as confidence shifts. High conviction means aggressive leverage. Lower conviction means reduce leverage, keep position.

The conviction engine operationalizes this through `ThesisState.conviction` scores (0.0 to 1.0) that directly drive position size.

---

## Mandatory SL/TP Rule

<Aside type="danger" title="No exceptions">
Every position MUST have both a stop-loss AND a take-profit on the exchange at all times. The daemon enforces this on every tick. If either is missing, it places them automatically.
</Aside>

### Stop Loss

- **Method:** ATR-based, computed by the `market_structure` iterator
- **Default:** 3x ATR below entry for longs
- **Minimum:** Must maintain liquidation buffer safety
- **Type:** Exchange-native trigger order (fires even if daemon is down)
- **Never:** Fixed-percentage stops on thesis-driven positions — they get hunted

### Take Profit

- **Primary:** `take_profit_price` from the thesis JSON file
- **Fallback:** Mechanical 5x ATR above entry if no thesis TP is set
- **Type:** Exchange-native trigger order

---

## Conviction Bands

| Conviction | Target Size (% equity) | Max Leverage |
|-----------|----------------------|-------------|
| 0.8-1.0 | 20% equity | 15x |
| 0.5-0.8 | 12% equity | 10x |
| 0.2-0.5 | 6% equity | 5x |
| 0.0-0.2 | 0% (exit signal) | 0x |

Conviction values are set in thesis files (`data/thesis/<COIN>.json`). Thesis files are valid for months or years — the system does not clamp conviction aggressively on age alone. Reality wins: update conviction actively based on market conditions, not calendar.

---

## Time-Aware Leverage Caps

The `weekend_leverage_cap` and session-specific rules reduce exposure during dangerous periods.

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
- The thesis is the confirmation, not the price action

---

## Exit Rules

| Exit trigger | Action |
|-------------|--------|
| Thesis invalidation | Exit immediately |
| Take-profit hit | Full or partial exit per thesis |
| Geopolitical reversal | Exit on confirmation |
| Account 25% drawdown | Halt all new entries |
| Account 40% drawdown | Close ALL positions |

Do not exit solely on fixed-percentage drawdowns — thesis-invalidation exits are the primary mechanism for planned positions.

On weekends: reduce leverage if needed, but do not close positions unless the thesis is invalidated.

---

## Liquidation Cushion

The daemon monitors liquidation distance for every open position:

- **Default alert threshold:** 15% cushion
- **Critical threshold:** 10% cushion (urgent Telegram alert)
- **6.5% cushion at 11x leverage is normal** — do not over-react to the default thresholds at higher leverage

Adjust thresholds in `data/config/risk_caps.json` to match your actual leverage levels.
