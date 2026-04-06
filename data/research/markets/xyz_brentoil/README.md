# BRENTOIL — Geopolitical Supply Squeeze

## Thesis
Biggest oil bull case in generations. The 10M+ bpd supply gap CANNOT be closed in 2026.
The market must either reopen Hormuz or destroy demand. Neither happens fast.

## The Physical Reality
- Hormuz closed since March 2. 17.8-20M bpd blocked.
- Bypass capacity: 3.5-5.5M bpd max (25% of what's lost)
- Saudi has wells but can't export — storage filling
- Qatar Ras Laffan LNG: 3-5 YEAR repair timeline
- Iraq 70% production down. Kuwait force majeure.
- Global spare capacity: ZERO deliverable barrels
- Physical Dubai crude at $126 vs Brent futures at $112 — paper is CHEAP

## Supply Response Timeline
- SPR release: 3.4M bpd for 4 months (bridge, not solution)
- Venezuela: +150K bpd in 3-6 months (needs years for real scale)
- US shale: +100-200K bpd in 5-6 months (no DUCs, cautious operators)
- The gap is unfillable. Period.

## The Geopolitical Play
US/Israel/Ukraine systematically destroying energy infrastructure.
Real target: energy dominance over China.
User (petroleum engineer) believes US will lose → prices skyrocket.

## Key Catalysts
- **April 6:** Trump deadline. Escalation (→$130-150) or deadline extension (→consolidation)
- **April 7-13:** Contract roll BZM6→BZN6. Extreme backwardation ($25+) makes this significant.
- **Late April:** US military "reopening" of Hormuz possible (partial). Full normalization: MONTHS.
- **July-August:** SPR exhaustion if not replenished. Supply gap reappears.

## Current Position
**IMPORTANT: Always query live HL API state — these numbers go stale fast.**
- As of 2026-03-30: 30 contracts LONG @ ~$107.65, 10x isolated, liq ~$99.38
- Direction: LONG ONLY. Adjust leverage, never go flat.
- Exchange-level SL/TP: MUST be set via ExchangeProtectionIterator or place_trigger_order()
- Guard trailing stop: Active via GuardIterator with exchange SL sync

## The Contract
- Tracks ICE Brent June 2026 (BZM6), rolling July 7-13
- Cash-settled USDC. Isolated margin only. Max 20x.
- OI cap $750M — can't add positions if hit
- Funding: hourly, longs pay shorts when perp > oracle
- Trading hours: Sun 6PM ET - Fri 5PM ET

## Risk Factors
1. Peace deal (LOW probability — positions far apart)
2. Military reopening partial (late April) — price dips but doesn't crash
3. Demand destruction starts at $120-130 sustained
4. Contract roll April 7-13 — tracking drift from backwardation
5. $750M OI cap — might not be able to add during vol spike
6. Funding cost — monitor hourly, heavy in backwardation
7. Weekend stop hunts on thin liquidity
8. Data manipulation (MarineTraffic spoofed, media propaganda)

## Edge
Petroleum engineering expertise + first-principles supply analysis.
NOT chart patterns. NOT generic quant signals.

## Research Notes (2026-03-31)
- `notes/2026-03-31-infrastructure-damage-inventory.md` — Cumulative damage: 12M bpd offline, Qatar LNG 3-5yr, Russian 40% down
- `notes/2026-03-31-leading-indicators-war-duration.md` — Real-money signals: BA Oct cancel, Lloyd's zone, P&I refused, DIA 1-6mo
- `notes/2026-03-31-airline-cancellation-analysis.md` — Dubai as key marker, 7mo+ airline horizon, permanent rerouting underway

## HL Perp Structure (CRITICAL for trading)
- BRENTOIL tracks ICE Brent JUNE 2026 (BZM6), NOT spot or front-month May
- Current backwardation: ~$6-7/month (May $112 vs June $106 vs July $99)
- Roll drag: ~$6/month for longs as oracle transitions to cheaper deferred months (5th-10th business day)
- Funding: currently NEGATIVE (shorts pay longs = free carry for longs)
- Abraxas Capital: $101M SHORT harvesting positive roll yield (liq at $141-146)
- Key thesis: backwardation is MISPRICED if infrastructure damage makes deferred-month resolution pricing wrong
Physical reality drives the price. Charts confirm, they don't lead.

## Brent-WTI Spread
$12.93-14.46/bbl — largest in a decade. IS the geopolitical risk premium.
If spread widens further: thesis strengthening.
If spread narrows: either Brent falling or WTI catching up. Investigate which.

## Forward Curve: EXTREME BACKWARDATION
- Front-12mo spread: -$25.49
- No incentive to store. Physical is king.
- Market prices disruption lasting 4-6 months
- But longer-dated (2027+) elevated too — no quick return to normal
