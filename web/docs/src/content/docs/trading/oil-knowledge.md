---
title: Oil Knowledge
description: Petroleum engineering context for trading BRENTOIL — supply chains, disruption signals, information discipline, and entry timing.
---

## Edge Source

The system's primary edge in oil comes from petroleum engineering domain knowledge. The human operator is a petroleum engineer with first-principles understanding of supply chains, pipeline economics, and refinery dynamics. The AI agent is the risk manager and discipline enforcer — not the thesis generator.

Oil markets are dominated by bots reacting to current news. Petroleum engineering expertise lets you anticipate supply disruptions before they become headlines. By the time a headline fires, the move is priced in.

---

## Supply Chain Signals

Key disruption signals to monitor, in priority order:

1. **Shipping lane restrictions** — Strait of Hormuz, Bab-el-Mandeb, Black Sea corridors
2. **Pipeline outages** — TAL, BTC pipeline, Libya shutdowns, Nigeria infrastructure
3. **OPEC+ compliance** — actual output vs stated quotas (always lower than stated)
4. **Strategic Reserve releases** — specifically suppress Brent-linked European stocks
5. **Seasonal demand patterns** — Northern hemisphere winter demand pickup, summer driving season
6. **Refinery capacity** — global refinery margins, turnaround schedules

---

## Information Discipline

Operating in a wartime information environment means all data may be fake, spoofed, or agenda-driven.

Rules:
1. Cross-reference everything from multiple independent sources
2. MarineTraffic/AIS data over conflict zones may be blocked or spoofed
3. Official government statements are propaganda first, data second
4. Satellite imagery is more reliable than written reports
5. Always state source and confidence level — "I think" vs "data shows"
6. Ask: who benefits from this narrative? What is NOT being shared?

---

## Entry Timing

**Position AHEAD of events, never chase.** By the time a headline fires, it is too late.

Specific rules:
- **Asia open is the key session for oil**, not Europe. China, Japan, India, and Singapore trade oil with massive size. Monitor from Sunday 6 PM ET / 8 AM AEST Monday. Japan futures open around 8:45 AM JST.
- If the market opens near Friday close levels after a bullish weekend development, that IS the discount — enter immediately. The thesis is the confirmation.
- Historical weakness: right on direction, killed on entries. The AI's job is to fix that by buying when it is boring and cheap.

---

## Long-Only Rule

**NEVER short oil.** This is a hard rule, not a preference.

Rationale:
- The supply disruption edge is asymmetric and skewed long
- Short oil thesis requires predicting when supply comes back — unknowable in a disrupted market
- Risk/reward on shorts is structurally worse: limited downside vs unlimited upside for longs

**Exception:** The Oil Bot-Pattern strategy sub-system 5 (which fades bot overshoot on oil) is the ONLY place shorts are legal. It requires REBALANCE+ tier and is behind double kill switches — both `oil_botpattern.json` enabled flag and the tier gate must be active. This is off by default.

---

## Backwardation vs Contango

| Structure | What it means | Trading implication |
|-----------|--------------|---------------------|
| **Backwardation** (near > far) | Physical tightness, real demand | Longs pay roll drag; need oil to rally above drag |
| **Contango** (near < far) | Supply overhang or weak demand | Roll is profitable for longs (carry positive) |
| **Steep backwardation** | Crisis, supply disruption | Roll drag can exceed $6/month — size carefully |

---

## Calendar Catalysts

The AI agent checks the CalendarContext before any oil analysis. Key recurring events:

| Event | Frequency | Typical impact |
|-------|-----------|----------------|
| EIA Weekly Petroleum Status Report | Weekly (Wednesday 10:30 ET) | High — crude/product inventory |
| API Report | Weekly (Tuesday ~4:30 PM ET) | Medium — preview of EIA |
| OPEC+ meetings | Irregular | Very high — quota decisions |
| IEA Oil Market Report | Monthly | Medium — demand outlook |
| CFTC Commitment of Traders | Weekly (Friday) | Medium — speculative positioning |
