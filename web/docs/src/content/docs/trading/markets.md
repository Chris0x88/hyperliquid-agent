---
title: Markets
description: Approved markets, contract microstructure, and the xyz clearinghouse — what to trade and how it's structured.
---

import { Aside } from '@astrojs/starlight/components';

## Approved Markets

| Market | Clearinghouse | Direction | Role |
|--------|--------------|-----------|------|
| **BTC** | HL native | Long bias | Power Law vault, automated rebalancing |
| **BRENTOIL** | xyz | Long only | Primary thesis-driven edge market |
| **CL (WTI)** | xyz | Long only | Same thesis framework as Brent |
| **GOLD** | xyz | Long bias | Chaos hedge, USD debasement |
| **SILVER** | xyz | Long bias | Capital builder, undervalued vs gold |

No memecoins. No low-liquidity junk. No small-cap garbage. The bot may scan other markets for signals but only deploys capital to the approved list.

---

## BRENTOIL Contract Details

The BRENTOIL perp on HyperLiquid tracks the **ICE Brent deferred-month contract** — not spot, not front-month.

| Detail | Value |
|--------|-------|
| Oracle | RedStone HyperStone |
| Roll period | 5th–10th business day each month |
| Underlying | ICE Brent deferred month |

**Key implication:** The apparent "discount" vs spot Brent is not a discount — it is the correct price for the deferred contract in backwardation.

### Roll Drag in Backwardation

In steep backwardation (current market structure), longs pay roll drag as the contract rolls forward into cheaper months. At extreme backwardation, this can exceed ~$6/month.

A long position needs oil to rally MORE than the cumulative roll cost to be profitable. Funding is a partial offset — when funding is negative (shorts pay longs), it reduces net carry cost.

---

## WTI vs Brent Spread

The WTI–Brent spread is a proxy for conflict-resolution expectations:
- **Widening spread** → crisis deepening
- **Narrowing spread** → de-escalation

The current inversion (WTI above Brent) is driven by WTI Midland entering the BFOE basket (since June 2023), Dubai benchmark distortions, and Asian refiner demand.

---

## xyz Clearinghouse

<Aside type="caution" title="Critical API requirement">
ALL API calls for xyz perps (BRENTOIL, GOLD, SILVER) MUST include `dex='xyz'`. Missing this parameter causes silent failures — wrong prices, wrong positions, missed orders.
</Aside>

### Coin Name Prefix Bug

The xyz clearinghouse returns universe names WITH the `xyz:` prefix (e.g., `xyz:BRENTOIL`). The native clearinghouse does NOT prefix names.

When matching coin names against universe data, ALWAYS handle both forms. The canonical pattern is `_coin_matches()` in `telegram_bot.py`:

```python
def _coin_matches(coin: str, name: str) -> bool:
    return name == coin or name.replace("xyz:", "") == coin
```

This bug has caused silent failures in funding lookups, OI lookups, and price change calculations multiple times.

---

## Funding Rate Economics

| Scenario | Effect on longs |
|----------|----------------|
| Bull market (crowded longs) | +8–12% annualized funding cost |
| Bear market (crowded shorts) | Longs get paid (negative funding) |
| Neutral | Near zero |

Monitor `cumFunding.sinceOpen` on all positions. Significant funding can erode returns even on winning directional trades.
