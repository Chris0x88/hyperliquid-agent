# Markets & Contract Microstructure

## Approved Markets

| Market | Exchange | Direction | Notes |
|--------|----------|-----------|-------|
| BTC | HyperLiquid native | Long bias | Power Law vault, automated |
| BRENTOIL | HyperLiquid xyz | Long only | Thesis-driven, manual AI |
| CL (WTI) | HyperLiquid xyz | Long only | Same thesis framework |
| GOLD | HyperLiquid xyz | Long bias | Chaos hedge |
| SILVER | HyperLiquid xyz | Long bias | Capital builder |

## HyperLiquid Perp Structure

### BRENTOIL Contract

- **Tracks:** ICE Brent deferred-month contract (not spot, not front-month)
- **Oracle:** RedStone HyperStone
- **Roll mechanics:** Rolls to next month contract between 5th-10th business day each month
- **Key implication:** The apparent "discount" vs spot Brent is not a discount -- it is the correct price for the deferred contract in steep backwardation

### Roll Drag

In backwardation, longs pay roll drag as the contract rolls forward into cheaper months. At steep backwardation levels, this can exceed ~$6/month. A long position needs oil to rally MORE than the cumulative roll cost to profit.

Short positions (e.g., large basis traders) harvest positive roll yield structurally. Funding is a partial offset -- when funding is negative (shorts pay longs), it reduces the net carry cost for longs.

### Funding Rate Economics

- **HL perp funding:** Variable hourly rate, can accumulate significantly over weeks/months
- **In bull markets:** Crowded-long funding can run +8-12% annualized, eroding returns vs spot
- **In bear markets:** Longs get paid -- favorable for the hold strategy
- **BTC Power Law implication:** The rebalancer was designed for SaucerSwap (zero holding cost). On HL, monitor `cumFunding.sinceOpen` closely

## WTI vs Brent

Historically, WTI trades at a discount to Brent. The current inversion (WTI above Brent) is driven by:

1. **WTI Midland in BFOE basket** -- WTI now sets Dated Brent price 50-60% of the time (since June 2023)
2. **Dubai benchmark distortion** -- deliverable grades locked behind conflict zones; benchmark running on reduced grades
3. **SPR releases** -- specifically suppress Brent-linked European stocks
4. **Asian refiner buying** -- panic-buying US barrels, pulling WTI above Brent on physical demand
5. **Hormuz dynamics** -- blocking competitor exports while shadow fleet operates at crisis prices

**Trading implication:** The WTI-Brent spread is a proxy for conflict-resolution expectations. Widening = crisis deepens. Narrowing = de-escalation.

## xyz Clearinghouse

xyz perps (BRENTOIL, GOLD, SILVER) trade on the xyz clearinghouse, not the native HL clearinghouse.

**Critical API requirement:** ALL API calls for xyz perps must include `dex='xyz'`.

**Coin name prefix bug (recurring):** The xyz clearinghouse returns universe names WITH the `xyz:` prefix (e.g., `xyz:BRENTOIL`, `xyz:GOLD`). The native clearinghouse does NOT prefix names. When matching coin names against universe data, ALWAYS handle both forms -- compare both `name` and `name.replace("xyz:", "")`. This has caused silent failures in funding lookups, OI lookups, and price change calculations multiple times. See `_coin_matches()` in `telegram_bot.py` for the canonical pattern.
