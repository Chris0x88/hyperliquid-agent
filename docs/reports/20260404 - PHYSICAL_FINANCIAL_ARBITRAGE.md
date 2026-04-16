# Trading Strategy: Physical-Financial Arbitrage on HyperLiquid
## April 4, 2026 — Strategy Design Discussion

---

# CONTEXT

Chris (petroleum engineer) identified several tradeable patterns from deep research into:
- WTI-Brent lead-lag and convergence to within $1
- Record $13.50 WTI May-June backwardation
- Physical trade month calendar (June buying starts April 26)
- Financial vs physical tethering mechanisms
- Roll mechanics on xyz perps (April 8-14)

Key instruments: xyz:CL (WTI), xyz:BRENTOIL — both on HyperLiquid xyz perps.

---

# CRITICAL CALENDAR: EASTER + ROLL

| Date | CME Status | HyperLiquid | Event |
|------|-----------|-------------|-------|
| **Apr 3 (Fri)** | **CLOSED (Good Friday)** | Open (oracle frozen) | Last CME session before Easter |
| Apr 4 (Sat) | Closed | Open (oracle frozen, ±5% bounds) | |
| Apr 5 (Sun) | Reopens 5 PM CT | Open | CME Globex reopens for Monday trade |
| **Apr 6 (Mon)** | **Normal trading** | Open (oracle live) | Trump's original deadline (weakened) |
| Apr 7 (Tue) | Normal | Open | Last day before roll starts |
| **Apr 8 (Wed)** | Normal | **ROLL DAY 1: 80/20** | Oracle starts blending CLK6/CLM6 |
| Apr 9 (Thu) | Normal | ROLL DAY 2: 60/40 | |
| Apr 10 (Fri) | Normal | ROLL DAY 3: 40/60 | |
| Apr 11-12 | Closed (weekend) | Open (oracle frozen) | |
| **Apr 13 (Mon)** | Normal | ROLL DAY 4: 20/80 | |
| **Apr 14 (Tue)** | Normal | ROLL DAY 5: 0/100 | Roll complete. CL now tracks CLM6 |

**Chris's observation is correct:** HL is open this Easter weekend but oracle is FROZEN at Thursday's close. Any HL price moves Fri-Sun are constrained to ±5% of frozen oracle and driven purely by HL internal order flow. "Total garbage" — these are not price discovery, they're HL-specific noise.

---

# CUSHING STORAGE: CORRECTION

I understated Cushing tightness. The data actually says:

- **Current: 20.9M bbl (27.5% of 76M working capacity)**
- **This is near historical lows** — comparable to 2014-2015 troughs (~20M bbl)
- July 2025: 21.2M bbl, already ~40% below year-ago levels
- The recent builds (+3.4M, +520K) are SPR releases, not organic supply growth

**Can exports drain Cushing?**
YES. Current US crude exports: **3.8M b/d** from:
- Corpus Christi: 2.2M b/d (pipeline from Permian at 99% utilization)
- Houston: 1.3M b/d (growing 71% since 2022)
- China + India: 40-45% of Corpus Christi exports

**Trump telling countries to "buy American oil"** + Hormuz closure + Asian desperation = export demand surge. If export demand absorbs SPR releases AND pulls Cushing storage down, WTI physical tightens at the delivery point. Then the NYMEX anchor (Link 1) starts reflecting the global crisis, not just domestic surplus.

**Key level to watch:** Cushing below 20M bbl = historically tight. Below 15M = operational minimum (pipelines need minimum nominations). We're close.

---

# MONTHLY ANCHORING CALENDAR

## When is HL Most/Least Connected to Physical Reality?

### MOST ANCHORED (Physical Dominates)

**Last 5-7 days before NYMEX expiry (for the front month)**
- Physical delivery obligation forces convergence
- Trading houses execute EFP and delivery arbitrage
- Futures MUST converge to Cushing physical price
- For CLK6: April 15-21 (expiry April 21)

**During the physical trade month window**
- For May delivery: March 26 – April 25 (active NOW)
- For June delivery: April 26 – May 25
- Refiners, producers, and trading houses actively buying/selling physical
- Physical flows directly influence futures via EFP and delivery

### LEAST ANCHORED (Financial Speculation Dominates)

**Early-to-mid contract month (weeks 1-3 after roll)**
- New contract has 6+ weeks to expiry
- No delivery pressure
- Financial flows (CTAs, macro, headlines) dominate
- Paper-physical gap can widen
- This is where WTI can trade $30-40 away from Dubai physical

**CME closures (weekends + holidays)**
- Oracle frozen on HL
- HL price discovery constrained to ±5% band
- No arbitrage possible between physical/NYMEX and HL
- Pure internal HL order flow — retail speculation
- Easter weekend (Apr 3-5) = MAXIMUM disconnect

**During roll window (5th-10th business day)**
- Oracle transitioning between contracts
- Mechanical blending creates artificial price moves
- Roll drag ≠ market signal
- Abraxas-style shorts harvest roll yield from longs

### MONTHLY CYCLE MAP

```
Day 1-4:   Post-roll. New contract. LEAST anchored. Max speculation.
Day 5-10:  ROLL WINDOW. Mechanical. Oracle blending. Not tradeable on fundamentals.
Day 11-20: Mid-month. Mixed. Financial flows + physical trade month overlap.
Day 20-25: Physical trade month active. Refiners buying. MORE anchored.
Day 25+:   Pre-expiry. Physical delivery convergence. MOST anchored.
```

---

# THREE STRATEGY IDEAS FROM CHRIS

## Strategy A: WTI-Brent Spread Compression

**Signal:** WTI blows out ahead of Brent (as happened April 2: WTI +14%, Brent +7%)
**Trade:** Short xyz:CL + Long xyz:BRENTOIL
**Target:** Spread compresses to ~$0-1 as Brent catches up (12-48 hour lag)
**Edge:** Structural — WTI Midland sets Dated Brent 50-60% of time. They MUST converge. Trading houses arbitrage this.

**NOTE: Requires update to "never short oil" rule — this is a spread trade, not directional short.**

## Strategy B: Front-Month / Back-Month Spread (Calendar Spread)

**Signal:** Record $13.50 May-June WTI backwardation
**Trade:** Effectively short May / long June (or wait for roll to put you on June at depressed price)
**Target:** Backwardation compresses as June procurement cycle starts (April 26+) and war continuation reprices CLM6
**Edge:** Physical trade month calendar + petroleum knowledge of SPR depletion timeline

**Implementation on HL:** Can't directly trade the spread (only one CL perp). Options:
1. Close CL long pre-roll, re-enter post-roll at ~$98 (captures the spread implicitly)
2. Short BRENTOIL pre-roll (Brent tracks June already), long CL post-roll on June

## Strategy C: Roll Cycle Protection (Mechanical)

**Signal:** Every month, 5th-10th business day
**Action:** Automatically reduce leverage, widen stops, or rotate exposure before roll
**Edge:** Zero — pure risk management. The roll is arithmetic, not a trade.
**Implementation:** Extend `is_near_roll_window()` to cover CL (currently BRENTOIL only). Alert + auto-adjust.

---

# OPEN QUESTIONS FOR CHRIS

1. Update "never short oil" rule for spread/relative-value trades?
2. Priority: which strategy to build first?
3. Appetite for roll rotation (Strategy B) given the roll starts April 8?
4. Should the monthly anchoring calendar be integrated into the conviction engine or just alerting?
