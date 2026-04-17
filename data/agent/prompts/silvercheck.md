Silver position audit — technicals + funding + sweep risk + thesis alignment.
<!-- Usage: /silvercheck [optional context, e.g. "ahead of FOMC"] -->
<!-- Expands to a sparring-partner challenge prompt for the live Silver position. -->
<!-- {{args}} receives any text typed after /silvercheck -->

I want you to act as my sparring partner, not my cheerleader. Audit the current Silver (SILVER/xyz:SILVER) position right now with the following lenses — and push back hard if anything looks weak.

Context from operator: {{args}}

**1. Technical posture**
Pull the live price, 4h and 1d candle structure, ATR, and distance to the nearest HTF support/resistance. Is price overextended? Is momentum rolling over or accelerating? What does the volume profile say about conviction behind the recent move?

**2. Funding & carry cost**
Fetch the current funding rate and 7-day average. At the current position size and leverage, what is the daily dollar cost of carry? Does the thesis payoff still justify holding through negative funding for another 48–72 hours?

**3. Sweep risk**
Identify the nearest stop-hunt liquidity cluster below entry (use heatmap data if available). What is the probability that price dips through the current SL before the thesis plays out? Is the SL placed below a real structural level or is it mechanical ATR only?

**4. Thesis alignment check**
Reference the Silver thesis file. Has anything in the macro picture (USD, real rates, industrial demand, safe-haven flows) shifted since the thesis was authored? Score current conviction 1–10 and explain why you'd hold, reduce, or exit right now.

**5. Your challenge**
End with one pointed question I should be able to answer before I sleep tonight. If I can't answer it, that's a red flag worth acting on.

Tone: direct, no flattery. I need edge, not comfort.
