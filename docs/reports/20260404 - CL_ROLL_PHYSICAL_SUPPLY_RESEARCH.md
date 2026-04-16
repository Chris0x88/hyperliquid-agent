# Deep Research: WTI (CL) Contract Roll vs Physical Supply Repricing
## April 4, 2026 — Position-Critical Analysis

**Position:** 65.103 contracts LONG xyz:CL @ $111.038, 20x isolated, liq $107.99
**Roll Window:** April 8-14, CLK6 (May) → CLM6 (June)
**Backwardation:** $13.50/bbl (12.1%) — largest-ever WTI front-to-second spread

---

# PART 1: CONTRACT ROLL MECHANICS

## What xyz:CL Currently Tracks

xyz:CL tracks **CLK6 (NYMEX WTI May 2026)**, sourced via Pyth Network oracle. After the roll completes, it will track **CLM6 (June 2026)**.

The underlying CLK6 contract expires **April 21, 2026** on NYMEX (third business day prior to the 25th of the preceding month). The xyz platform rolls well before NYMEX expiry.

Source: trade[XYZ] Specification Index (docs.trade.xyz/consolidated-resources/specification-index)

## Roll Schedule

All xyz commodity perps (CL, BRENTOIL, COPPER, NATGAS) use the same mechanism: **5-day phased blend during the 5th-10th business day of the month**, transitioning at **5:30 PM ET** (daily maintenance window).

| Date | Time (ET) | CLK6 Weight | CLM6 Weight | Blended Oracle* |
|------|-----------|-------------|-------------|----------------|
| Pre-Apr 8 | -- | 100% | 0% | $111.54 |
| **Apr 8 (Tue)** | 5:30 PM | 80% | 20% | **$108.84** |
| **Apr 9 (Wed)** | 5:30 PM | 60% | 40% | **$106.14** |
| **Apr 10 (Thu)** | 5:30 PM | 40% | 60% | **$103.44** |
| **Apr 13 (Mon)** | 5:30 PM | 20% | 80% | **$100.74** |
| **Apr 14 (Tue)** | 5:30 PM | 0% | 100% | **$98.04** |

*Assumes CLK6 at $111.54 and CLM6 at $98.04 (current prices, no repricing).

Source: trade[XYZ] Roll Schedules (docs.trade.xyz/consolidated-resources/roll-schedules)

## Comparison: CL Roll vs BRENTOIL Roll

| Parameter | CL (WTI) | BRENTOIL |
|-----------|----------|----------|
| Current oracle contract | CLK6 (May 2026) | BZM6 (June 2026) |
| Rolling to | CLM6 (June 2026) | BZN6 (July 2026) |
| Roll dates | Apr 8-14 | Apr 8-14 (same) |
| Mechanism | 5-day 80/20→0/100 | 5-day 80/20→0/100 (identical) |
| Backwardation | **~$13.50/bbl (12.1%)** | ~$6-7/bbl (~6%) |
| Total roll drag | **~$13.50** | ~$6-7 |
| Physical delivery | Cushing, OK (landlocked) | Cash-settled (BFOET-linked) |
| Max leverage | 20x | 20x |
| OI cap | $750M | $750M |

**CL roll drag is roughly double Brent's** in absolute terms. This is because WTI backwardation is steeper — the May-June WTI spread ($13.50) is described as the **largest-ever recorded spread between front-month and second-month crude deliveries**.

Note: The project codebase `is_near_roll_window()` in `conviction_engine.py` only checks for BRENTOIL rolls. CL roll awareness is NOT implemented. No thesis file exists for CL.

---

# PART 2: THE PHYSICAL SUPPLY ARGUMENT

## Chris's Thesis (Petroleum Engineer Assessment)

The $13.50 backwardation between May and June is mispriced. It assumes supply normalizes by June. Physical reality says it can't:

- Hormuz closed since March 2. 17.8-20M bpd blocked. 94% transit collapse.
- SPR releases: 3.4M bpd bridge for ~4 months. Europe (UK 39 days), Asia, Australia burning through reserves.
- India hits the wall mid-April. SE Asia in May.
- Venezuela ramp: impossible at scale. US shale: +100-200K bpd in 5-6 months.
- Trump confirmed Wednesday April 2: war continues "at least 2-3 more weeks."
- The 10M bpd gap is unfillable in 2026.

**Therefore:** As stockpiles drain and June delivery approaches, there will be desperation to buy forward oil. CLM6 will reprice upward toward CLK6. The backwardation compresses — potentially to near-zero — as the market realizes June supply is just as tight as May.

## The Paper-Physical Disconnect (Current State)

The physical oil market and the futures market have broken apart:

| Benchmark | Price (Apr 2-3) | Source |
|-----------|----------------|--------|
| Dubai Physical (spot) | **$138-140/bbl** | EBC Financial, CNBC |
| Brent Spot | **$141.36/bbl** (highest since 2008) | Houston Today |
| WTI May Futures (CLK6) | $111.54/bbl | OilPrice.com |
| WTI June Futures (CLM6) | $98.04/bbl | OilPrice.com |
| WTI July Futures (CLN6) | $89.39/bbl | OilPrice.com |

**Gap:** Physical crude trades $37-40 ABOVE futures. This is unprecedented in scale.

The futures market is betting: short-lived disruption, SPR bridges the gap, ceasefire eventually. The physical market is pricing: stranded tankers, cancelled war risk insurance, rerouted shipping (+10-14 days), immediate shortages in Asia.

"Paper-physical disconnects of this magnitude do not last." — EBC Financial Group

Sources:
- [Brent Spot $141 (Houston Today)](https://nationaltoday.com/us/tx/houston/news/2026/04/02/brent-oil-spot-price-soars-to-141-highest-since-2008/)
- [EBC Financial — Paper vs Physical Gap](https://www.ebc.com/forex/paper-oil-vs-physical-oil-the-40-gap-traders-are-missing)
- [CNBC — Trump Iran War Speech](https://www.cnbc.com/2026/04/02/trumps-iran-war-speech-oil-price-strait-hormuz.html)

---

# PART 3: THE TIMING PROBLEM — PHYSICAL BUYING vs ROLL WINDOW

## US Physical Trade Month Calendar

This is the mechanism that governs WHEN refiners physically buy WTI crude for a given delivery month.

**Rule:** The physical trade month starts on the 26th of the month TWO months before delivery and ends on the 25th of the month BEFORE delivery. This gives pipeline operators time to schedule volumes before delivery starts on the 1st.

| Delivery Month | Physical Trade Month | Status |
|---------------|---------------------|--------|
| **May 2026** | **Mar 26 – Apr 25** | **ACTIVE NOW** |
| **June 2026** | **Apr 26 – May 25** | **Starts April 26** |

**Critical finding:** US physical buying for June delivery doesn't start until ~April 26. The xyz CL roll happens April 8-14. There is a **12-day gap** between the roll completing and June physical buying kicking in at scale.

Right now, CLM6 at $98 is priced by financial traders and the forward curve structure — NOT by refiners scrambling for June barrels. That scramble is 3 weeks away.

Source: [Argus Media — US Physical Trade Month](https://www.argusmedia.com/en/methodology/key-commodity-prices/us-physical-trade-month)

## Cushing Storage (WTI Delivery Point)

- Current: **20.9M bbl** out of 76M working capacity (27.5% full)
- Week of Mar 20: **+3.42M bbl build** (largest since Jan 2023)
- Week of Mar 27: **+520K bbl build**

Cushing is BUILDING, not drawing. SPR releases are flowing into the US domestic system. This means WTI at the delivery point is NOT physically tight right now. The crisis is international — Asia, Europe, Australia are in trouble, not Cushing.

This further weakens the case for CLM6 repricing before the roll. The physical tightness that would force June WTI higher is happening overseas, not at the delivery hub that sets the price.

Sources:
- [MacroMicro Cushing Inventory](https://en.macromicro.me/charts/1051/cushing-crude-oil-inventory)
- [CME Group — Why Cushing Matters](https://www.cmegroup.com/education/articles-and-reports/why-cushing-matters-a-look-at-the-wti-benchmark.html)

---

# PART 4: CATALYSTS THAT COULD COMPRESS THE SPREAD PRE-ROLL

Despite the timing headwind, several forces could push CLM6 higher before April 8-14:

## 4a. Financial Front-Running
Traders seeing the SPR depletion timeline and Trump's "2-3 more weeks" may buy CLM6 speculatively before physical buyers arrive. This is how financial markets price forward — they don't wait for the physical trade month. But this hasn't happened yet — CLM6 has been sitting at $98 while May trades at $111+ for days.

## 4b. International Physical Spillover
Asian refiners are in panic mode. "Refineries cannot wait six weeks for alternative barrels when storage is running dry." If Asian demand spills into WTI-linked cargoes via arbitrage, it lifts all months. But WTI at Cushing is partly insulated — it's landlocked, pipeline-fed from the Permian, not directly exposed to Hormuz.

## 4c. The "Oil Cliff" — Mid-April Repricing Signal
- **JPMorgan** warns of "sharp repricing" if Hormuz stays closed past mid-April
- **Goldman Sachs** estimates $20-50 repricing "within weeks"
- The SPR bridge is a 4-month supply. By mid-April (6 weeks in), markets should start pricing the end of that bridge

But "mid-April" = April 14-18, which is the END of the roll window, not the beginning. The repricing signal may arrive just as the roll completes — too late to save a high-leverage position through the roll.

## 4d. Trump's War Extension (Already Priced?)
Wednesday night's "2-3 more weeks" should logically lift June. If the war lasts through April, June delivery is also disrupted. But has the market priced this yet? CLM6 hasn't moved significantly.

## 4e. Term Contract Pressure
Refiners with term contracts settle on trade month averages. As May trade month (Mar 26 – Apr 25) averages rise, refiners may start locking in June barrels early to avoid even higher prices. This is a secondary effect — smaller and slower than spot buying.

Sources:
- [CNBC — Oil Prices Hormuz](https://www.cnbc.com/2026/03/28/oil-gas-prices-iran-war-hormuz.html)
- [OilPrice.com — Iran War Oil Curve](https://oilprice.com/Energy/Crude-Oil/Iran-War-Sends-Oil-Curve-Into-Crisis-Mode.html)

---

# PART 5: FORCES KEEPING CLM6 LOW THROUGH THE ROLL

## 5a. Physical Trade Month Timing
The single biggest structural reason. June buying at scale starts April 26. The roll is April 8-14.

## 5b. Cushing Builds
SPR flowing into Cushing. Domestic WTI not physically tight at the delivery point. The crisis is international.

## 5c. Paper-Physical Gap Persistence
The $40 gap between Dubai physical ($140) and futures ($100-113) has persisted since early March — over 4 weeks. Paper markets CAN stay disconnected from physical for extended periods. Convergence is inevitable but not on a guaranteed timeline.

## 5d. Institutional Short Positioning
Abraxas Capital: **$101M SHORT** on BRENTOIL, harvesting positive roll yield (liq at $141-146). Institutional money is positioned to profit from longs bleeding through the roll. They have structural incentive to keep deferred months suppressed.

## 5e. Forward Curve Inertia
Markets price disruptions as temporary by default. The extreme backwardation ($25 front-to-12-month) already reflects "4-6 month disruption" pricing. June at $98 = "things normalize somewhat by June." This is the consensus bet, even if it's wrong.

---

# PART 6: HISTORICAL PRECEDENT

## How Fast Do Deferred Months Reprice in Supply Crises?

| Crisis | Front Month Move | Deferred Response | Compression Timeline |
|--------|-----------------|-------------------|---------------------|
| 1990 Gulf War (Aug) | +$14 in 2 months | Back months lagged 2-3 weeks | Spread compressed over 3-4 weeks as war duration became clear |
| 2008 Supply Squeeze | Backwardation to $2-3 | Gradual, demand-driven | Months (financial crisis intervened) |
| 2022 Russia-Ukraine | Brent +$30 in weeks | Deferred rose, backwardation compressed | Weeks — once markets accepted prolonged disruption |
| **2026 Iran-Hormuz** | **WTI +$20 in days** | **Deferred NOT yet repricing ($13.50 spread)** | **Unknown — unprecedented scale** |

The pattern: deferred months reprice when the market ACCEPTS that disruption is prolonged. Trump's Wednesday speech should have been that catalyst. The fact that CLM6 hasn't moved suggests the financial market still doesn't believe the physical reality.

"If the conflict threatens prolonged production losses or structural export constraints, deferred contracts can also move higher, flattening or even shifting the entire curve upward." — OilPrice.com analysis

---

# PART 7: SYNTHESIS — THE HONEST ASSESSMENT

## What's Right About Chris's Thesis
1. CLM6 at $98 IS mispriced if war continues (which Trump confirmed it will)
2. SPR depletion IS accelerating — Europe, Asia, Australia exhausting reserves
3. The 10M bpd gap IS unfillable — no supply response at this scale exists
4. Physical Dubai at $140 vs futures at $98-112 IS unsustainable
5. The deferred months WILL reprice. This is near-certain on a 2-6 week horizon.

## What's Dangerous About the Position
1. The physical buying cycle for June starts April 26 — **12 days after the roll completes**
2. Cushing is building, not drawing — domestic WTI delivery point is not tight
3. Financial front-running of the thesis hasn't materialized yet (CLM6 still at $98)
4. Institutional shorts are positioned to harvest the roll drag
5. At 20x leverage, the position is liquidated by Day 2 of the roll if CLM6 doesn't reprice
6. Even at 10x, the position dies on Day 5 if CLM6 stays at $98

## The Core Tension
**The thesis is right on direction and almost certainly right on magnitude. The question is purely whether the repricing arrives in the specific 4-day window between now (April 4) and the first roll step (April 8) — or whether it arrives 2-3 weeks later, after the position has been mechanically liquidated.**

Being right about oil and being liquidated by contract mechanics before the thesis plays out is the worst possible outcome. It's also the most likely outcome at 20x leverage with current CLM6 pricing.

## What Would Change This Assessment
- CLM6 repricing above $105 before April 8 (would compress roll drag enough to survive at reduced leverage)
- A headline catalyst (Kharg Island strike, new SPR exhaustion data, Asian refinery shutdowns) that forces immediate financial repricing of June
- Cushing draws replacing builds (physical tightness reaching the delivery point)

---

# APPENDIX: Sources

- [trade[XYZ] Specification Index](https://docs.trade.xyz/consolidated-resources/specification-index)
- [trade[XYZ] Roll Schedules](https://docs.trade.xyz/consolidated-resources/roll-schedules)
- [trade[XYZ] Commodities](https://docs.trade.xyz/asset-directory/commodities)
- [Argus Media — US Physical Trade Month](https://www.argusmedia.com/en/methodology/key-commodity-prices/us-physical-trade-month)
- [OilPrice.com — Iran War Oil Curve Crisis](https://oilprice.com/Energy/Crude-Oil/Iran-War-Sends-Oil-Curve-Into-Crisis-Mode.html)
- [OilPrice.com — Futures Market Misreads Hormuz](https://oilprice.com/Energy/Crude-Oil/Futures-Market-Misreads-the-Hormuz-Oil-Shock.html)
- [Berkshire Edge — Futures vs Physical](https://theberkshireedge.com/future-vs-physical-how-the-oil-market-broke-in-two/)
- [EBC Financial — Paper vs Physical $40 Gap](https://www.ebc.com/forex/paper-oil-vs-physical-oil-the-40-gap-traders-are-missing)
- [CNBC — Trump Iran War Speech](https://www.cnbc.com/2026/04/02/trumps-iran-war-speech-oil-price-strait-hormuz.html)
- [CNBC — Oil Prices Hormuz](https://www.cnbc.com/2026/03/28/oil-gas-prices-iran-war-hormuz.html)
- [Houston Today — Brent Spot $141](https://nationaltoday.com/us/tx/houston/news/2026/04/02/brent-oil-spot-price-soars-to-141-highest-since-2008/)
- [Discovery Alert — Backwardation Analysis](https://discoveryalert.com.au/market-backwardation-2026-iran-oil-prices/)
- [MacroMicro — Cushing Inventory](https://en.macromicro.me/charts/1051/cushing-crude-oil-inventory)
- [CME Group — Why Cushing Matters](https://www.cmegroup.com/education/articles-and-reports/why-cushing-matters-a-look-at-the-wti-benchmark.html)
- [Digital Refining — Crude Oil Sourcing](https://www.digitalrefining.com/article/1001346/crude-oil-sourcing-price-and-opportunity)
