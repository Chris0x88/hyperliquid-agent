Exit condition audit — for each open position, propose precise exit conditions per AGENT.md rules.
<!-- Usage: /exitcheck [optional symbol, e.g. "SILVER"] to narrow to one position -->
<!-- Proposes exit conditions per RSI/funding/cushion thresholds. Sparring-partner tone. -->
<!-- {{args}} receives any text typed after /exitcheck (use to scope to one market) -->

Exit condition review. Sparring-partner mode — the job here is to stress-test whether my current exit plan is coherent, not to validate it.

Scope: {{args}}

For each open position (or the scoped symbol if provided), work through the following:

**1. Current SL and TP — are they right?**
State the current SL and TP prices. Calculate: distance to SL in ATR multiples, distance to TP in ATR multiples, and the resulting risk-reward ratio. Per AGENT.md rules, SL must be ATR-based and TP must come from thesis `take_profit_price` or mechanical 5× ATR if no thesis. Is the current setup compliant? If not, what is the corrected placement?

**2. RSI exit trigger**
What is the current RSI(14) on the 4h timeframe? If the RSI has reached overbought territory (>70 for longs) or if there is a clear RSI divergence against price, is there a tactical case for trimming before the TP is hit? Explain the tradeoff.

**3. Funding flip threshold**
At what funding rate level does the carry cost erode the expected return to the point where exiting early makes mathematical sense? Given current funding, how many hours until the carry cost equals 25% of the expected profit? 50%?

**4. Cushion / liquidation proximity check**
What is the current margin cushion percentage? Per operational rules, if cushion falls below 10% that is critical — flag immediately. Is the position sized such that a normal 2-ATR adverse move would threaten the cushion threshold?

**5. Thesis-invalidation exit**
What specific price action, news event, or macro data point would definitively invalidate the thesis for this position? This is not the SL — it is the "I was wrong about the story" exit. Has any of that happened in the last 7 days?

**6. Proposed exit plan**
For each position, write a single sentence exit plan in the format: "Exit if [condition], otherwise hold to TP at [price] unless thesis invalidated by [event]."

Be precise. No "monitor carefully" — give me numbers.
