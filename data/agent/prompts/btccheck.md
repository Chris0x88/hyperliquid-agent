BTC position audit — technicals + vault context + thesis alignment + funding.
<!-- Usage: /btccheck [optional context, e.g. "post-halving drift"] -->
<!-- Expands to a sparring-partner challenge prompt for the live BTC position. -->
<!-- {{args}} receives any text typed after /btccheck -->

Sparring-partner mode: no cheerleading. Audit the current BTC position end-to-end.

Context from operator: {{args}}

**1. Position snapshot**
Retrieve the current BTC position (main account AND vault if delegated). Report: side, size, notional, entry price, current price, unrealised PnL, leverage, liquidation price, and distance to liquidation as a percentage. Flag if the vault position and main account position are misaligned.

**2. Technical structure**
Analyse the 4h and daily candle structure. Where is price relative to key EMAs (21, 55, 200)? What does the power law model say about current fair value? Is this an overextension or a base-building phase? Cite the ATR and whether volatility is expanding or contracting.

**3. Funding regime**
Current funding rate and 8-hour annualised cost. Is the market in a crowded long (bullish contrarian warning) or a crowded short (squeeze potential)? Compare to the 30-day average. What does the OI trend suggest about positioning?

**4. Macro overlay**
Cross-reference: USD index direction, real yield direction, and any scheduled Fed events in the next 5 business days. BTC tends to lead risk assets at the margin — is the current move consistent with the macro tape or diverging?

**5. Thesis alignment**
Score the BTC thesis 1–10 against current reality. What is the thesis-invalidation price? How far are we from it? Has the thesis been updated in the last 30 days — and if not, should it be?

**6. The hard question**
Name the single biggest risk to this position over the next 72 hours that I am probably underweighting. Make me defend why I'm still holding.

Direct, precise, no padding.
