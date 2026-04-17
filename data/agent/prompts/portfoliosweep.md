Full portfolio audit — all positions, cross-asset risk, recent catalysts, and overnight threats.
<!-- Usage: /portfoliosweep [optional focus, e.g. "oil heavy"] -->
<!-- Runs the full /evening checklist data + portfolio_risk_monitor + catalyst sweep. -->
<!-- {{args}} receives any text typed after /portfoliosweep -->

Full portfolio sweep requested. This is the Druckenmiller-style macro overlay check — zoom out, see the whole board, find the hidden correlation bomb.

Operator focus: {{args}}

**Step 1 — Position inventory**
For every open position: symbol, side, size, notional, unrealised PnL, leverage, distance to SL (%), distance to TP (%), and distance to liquidation (%). Flag any position where SL or TP is missing (that is a critical error — alert immediately).

**Step 2 — Cross-asset correlation check**
Assess whether the current open positions are correlated in a way that creates hidden concentration risk. Example: long BTC + long GOLD + long SILVER under a USD-weakness thesis is a single macro bet, not three independent positions. Spell out the common factor risk. What event would hit all positions simultaneously?

**Step 3 — Catalyst sweep**
Pull the last 10 catalysts from the news ingest system and the next 7 days of scheduled events (EIA, OPEC+, Fed speakers, CPI, NFP). For each open position, identify the next scheduled catalyst that could threaten it and estimate the expected range move.

**Step 4 — Overnight risk**
It is likely approaching the Asia/Japan open (per Brisbane AEST time awareness). What happens to oil during the Japan open session? Are there any weekend geopolitical risks that would gap the market at the Sunday open? What is the risk of a stop sweep between now and tomorrow's London open?

**Step 5 — Portfolio-level risk metrics**
Total portfolio delta (in USD), total notional, portfolio-level leverage, and maximum drawdown if all positions hit their SL simultaneously. Is this within the Druckenmiller-style sizing rules (never bet more than you can afford to be wrong about)?

**Step 6 — Three things to act on tonight**
Name the three most urgent actions the operator should consider before sleeping. Rank by urgency. Be specific: "tighten SL on SILVER to X", not "review positions".

No comfort. Surface threats.
