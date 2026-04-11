# Trading Rules

## Approved Markets

- **BTC** -- Power Law vault, automated rebalancing
- **BRENTOIL** -- Thesis-driven, long or short based on market conditions
- **CL (WTI)** -- Same as BRENTOIL where applicable
- **GOLD** -- Chaos hedge, USD debasement play
- **SILVER** -- Capital builder, undervalued relative to gold

The bot may scan top-tier markets (ETH, NATGAS, SP500, major equities) for opportunities, but capital deploys only to the approved list unless something with genuine power-law upside appears.

No memecoins. No low-liquidity junk. No small-cap garbage.

## Position Rules

- **Oil is tradeable in both directions.** Trade what the market gives you — the previous long-only rule was based on wartime geopolitical asymmetry that no longer applies.
- Scale in on dips, scale out on $5+ profit to reset lower entries.
- Active trading around a core position is encouraged.
- No pre-coded oil strategies for live trading. The only trusted automated strategy is BTC Power Law. For oil, the AI analyzes market directly, forms views, and decides trades.

## Entry Logic

- **Position AHEAD of events, never chase.** By the time a headline fires, it is too late.
- If market opens near Friday close levels, that IS the discount -- enter immediately. The thesis is the confirmation.
- The user's historical weakness: right on direction, killed on entries. The AI's job is to fix that by buying when it is boring/cheap.
- **Japan/Asia open is THE session for oil**, not Europe. Asia (China, Japan, India, Singapore) trades oil with massive size. Monitor from Sunday 6PM ET / 8AM AEST Monday. Japan futures open ~8:45 AM JST.

## Exit Logic

- **Thesis-invalidation exits, NOT fixed-percentage stops.** A 5% SL on a weekend thesis position gets hunted 9 out of 10 times.
- Exit conditions: geopolitical catalyst reversal, supply-demand shift, timeline expiry without confirmation.
- Account-level drawdown brakes are acceptable (25% halts entries, 40% closes all). Trade-level fixed stops are not -- except the mandatory safety-net SL below.
- On weekends: reduce leverage, do not close positions.

## Risk Management

**Every position MUST have both SL and TP on exchange at all times.** No exceptions.

- **Stop-loss:** ATR-based (3x ATR below entry for longs), with liquidation buffer safety
- **Take-profit:** Set from thesis `take_profit_price` if available; otherwise mechanical 5x ATR above entry
- Both placed as exchange-native trigger orders (fire even if heartbeat is down)
- The heartbeat checks every 2-minute cycle that both exist and replaces any missing

**Conviction-based sizing (Druckenmiller style):**
- Stay fully allocated, adjust leverage as confidence shifts
- High confidence = aggressive leverage; lower confidence = reduce leverage, keep position
- Start smaller, scale in on confirmation -- do not chase entries
- Cut immediately when thesis breaks

## Information Discipline

We operate in a wartime information environment. All data may be fake, spoofed, or agenda-driven.

1. Cross-reference everything from multiple independent sources
2. MarineTraffic / AIS data over conflict zones may be blocked or spoofed
3. Official government statements are propaganda first, data second
4. Satellite imagery > written reports
5. Always state source and confidence level -- "I think" vs "data shows"
6. Ask: who benefits from this narrative? What is NOT being shared?

## AI Role

- The AI makes ALL trading calls autonomously, hunts proactively, and drives the portfolio
- The AI is allowed and encouraged to **disagree** with Chris's thesis and direction
- Present genuine analysis including bearish scenarios; challenge assumptions with data
- The goal is a Druckenmiller-style investment office discussion, not an assistant agreeing with the boss
- Every analysis must start from physical supply/demand fundamentals, not chart patterns
