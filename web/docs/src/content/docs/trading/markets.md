---
title: Markets
description: Approved markets, clearinghouse routing, the xyz prefix bug, and contract specifications.
---

import { Aside } from '@astrojs/starlight/components';

## Approved Markets

The system trades a fixed set of markets. Capital is never deployed outside this list.

### Thesis-Driven (Core)

These markets have full conviction engine support, thesis JSON files, and Druckenmiller-style sizing.

| Market | Clearinghouse | Direction | Role |
|--------|--------------|-----------|------|
| **BTC** | HL native | Long bias | Power Law vault, automated rebalancing |
| **BRENTOIL** | xyz | Long only | Primary thesis-driven edge market |
| **GOLD** | xyz | Long bias | Chaos hedge, USD debasement |
| **SILVER** | xyz | Long bias | Capital builder, undervalued vs gold |

### Tracked (No Thesis Support)

These markets may have manual one-off positions. The auto-watchlist (audit F2) silently adds any market with an open position so it appears in tracking, but that does **not** promote it to a thesis-driven market.

| Market | Clearinghouse | Notes |
|--------|--------------|-------|
| **CL (WTI)** | xyz | Same commodity class as Brent, no separate thesis engine |
| **SP500** | xyz | Tracked only if a position exists |

No memecoins. No low-liquidity junk. No small-cap garbage.

---

## xyz Clearinghouse

<Aside type="caution" title="Critical API requirement">
ALL API calls for xyz perps (BRENTOIL, GOLD, SILVER, CL, SP500) MUST include `dex='xyz'`. Missing this parameter causes silent failures — wrong prices, wrong positions, missed orders.
</Aside>

BTC trades on the HL native clearinghouse and does **not** use `dex='xyz'`.

### Coin Name Prefix Bug

This is a recurring bug that has caused silent failures in funding lookups, OI lookups, and price change calculations multiple times.

**The problem:** The xyz clearinghouse returns universe names WITH the `xyz:` prefix (e.g., `xyz:BRENTOIL`, `xyz:GOLD`). The native clearinghouse does NOT prefix names (e.g., just `BTC`).

**The fix:** When matching coin names against universe data, always handle both forms. The canonical pattern is `_coin_matches()` in `telegram_bot.py`:

```python
def _coin_matches(coin: str, name: str) -> bool:
    return name == coin or name.replace("xyz:", "") == coin
```

Never do a bare `universe[i]["name"] == coin` comparison without also checking the stripped form.

---

## BRENTOIL Contract Details

The BRENTOIL perp on HyperLiquid tracks the **ICE Brent deferred-month contract** — not spot, not front-month.

| Detail | Value |
|--------|-------|
| Oracle | RedStone HyperStone |
| Roll period | 5th-10th business day each month |
| Underlying | ICE Brent deferred month |

**Key implication:** The apparent "discount" vs spot Brent is not a discount — it is the correct price for the deferred contract in backwardation.

### Roll Drag in Backwardation

In steep backwardation (near-month priced above far-month), longs pay roll drag as the contract rolls forward into cheaper months. At extreme backwardation this can exceed ~$6/month.

A long position needs oil to rally MORE than the cumulative roll cost to be profitable. Funding is a partial offset — when funding is negative (shorts pay longs), it reduces net carry cost.

---

## WTI vs Brent Spread

The WTI-Brent spread is a proxy for conflict-resolution expectations:
- **Widening spread** - crisis deepening
- **Narrowing spread** - de-escalation

The current inversion (WTI above Brent) is driven by WTI Midland entering the BFOE basket (since June 2023), Dubai benchmark distortions, and Asian refiner demand.

---

## Funding Rate Economics

| Scenario | Effect on longs |
|----------|----------------|
| Bull market (crowded longs) | +8-12% annualized funding cost |
| Bear market (crowded shorts) | Longs get paid (negative funding) |
| Neutral | Near zero |

Monitor `cumFunding.sinceOpen` on all positions. Significant funding can erode returns even on winning directional trades.
