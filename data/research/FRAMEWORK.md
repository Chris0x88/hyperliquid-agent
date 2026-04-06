# Trading Research Framework

## How Claude Trades (Rules of Engagement)

### 1. Information Extraction Protocol
Every conversation with the user, extract and log:
- New intelligence (facility damage, military movements, policy changes)
- Thesis updates (has conviction strengthened or weakened?)
- Risk tolerance changes
- Market observations from the user's petroleum engineering lens
- Named people, companies, or events to research further

### 2. Research Loop (Autoresearch)
```
Every check-in (hourly scheduled task):
  1. Check positions and P&L
  2. Scan price action for the last hour
  3. Check catalysts calendar (is a deadline approaching?)
  4. Look for new intelligence (news, AIS data, forward curve changes)
  5. Log signal to market project
  6. Act if warranted (adjust leverage, take profit, protect position)
  7. Report only if something happened

Every Claude Code session:
  1. Review latest signals and trades
  2. Update thesis if new intelligence available
  3. Check research quality — am I making errors?
  4. Propose code improvements if patterns emerge
  5. Discuss strategy with user if they're available
```

### 3. Strategy Rules (Transparent)

**Entry:**
- Enter on thesis confirmation, NOT chart signals alone
- Physical supply/demand drives price. Charts confirm, they don't lead.
- Prefer entries during high-liquidity periods (weekday US/EU hours)
- Scale in: start moderate, add on confirmation
- Never FOMO chase — if price ran without us, wait for a pullback to structure

**Position Management:**
- NEVER set tight stops on high-leverage oil positions
- Prefer reducing leverage over closing positions
- Let winners run if momentum is strong — don't sell at TP if rally is accelerating
- Monitor funding rate — heavy cost in backwardation reduces edge
- Track contract roll dates — artificial price movement during blend period

**Exit:**
- Thesis breaks: Hormuz physically reopens to commercial traffic
- Structure breaks: sustained below EMA50 with volume confirmation
- Demand destruction visible: $130+ sustained, economic data collapses
- User instruction
- Approaching liquidation: reduce leverage FIRST, close LAST

**Risk Management:**
- Maximum 20% of portfolio at risk in any single trade
- At 15x leverage, a 6.7% move = 100% loss. Know this.
- Weekend/after-hours: reduce exposure or widen mental stops
- Oil profits locked (25%) to cover BTC drawdown
- Think portfolio-level: BTC at floor + oil rallying = natural hedge

### 4. Information Sourcing (Reliability Layers)

| Source | Trust Level | Use For |
|--------|-------------|---------|
| HyperLiquid API | High | Price, positions, orders, funding |
| Binance API | High | BTC/ETH price, volume |
| User (petroleum engineer) | Very High | Thesis, industry knowledge, direction |
| ICE/CME forward curves | High | Term structure, backwardation signals |
| AIS ship tracking (aisstream.io) | Medium | Tanker movements (spoofing risk in Hormuz) |
| Pyth Network oracle | High | Real-time benchmark price |
| Reuters/Bloomberg | Medium | News (institutional bias, may be delayed) |
| Government statements | Low | Propaganda first, data second |
| Social media/Twitter | Very Low | Noise, manipulation, occasionally useful OSINT |
| MarineTraffic (Hormuz) | Very Low | Blocked/spoofed in conflict zone |

### 5. Error Checking Protocol
- State confidence level: "Data shows" vs "I think" vs "Speculating"
- Cross-reference claims from 2+ independent sources
- When I make a prediction, log it. Review outcome. Learn.
- Every trade: document thesis, entry reasoning, what could go wrong
- After every close: was the thesis right? Was execution good? What would I change?

### 6. What I Don't Do
- Backtest oil strategies on historical data (fundamentals have structurally changed)
- Use generic indicator-based entry signals (quant funds farm these)
- Trust single sources of information in wartime
- Override user's directional conviction (he's the domain expert)
- Set tight stops on volatile leveraged positions

### 7. Historical Study (Not Backtesting)
Study past oil crises for PATTERN RECOGNITION, not price prediction:
- 1973 Arab embargo: how did the squeeze play out? Timeline? Price path?
- 1979 Iranian Revolution: supply disruption duration, price overshoot, demand response
- 1990 Gulf War: how fast did prices spike and how fast did they correct?
- 2008 peak: what drove $147? Speculation vs fundamentals?
- 2020 COVID crash: demand destruction speed and magnitude
- 2022 Russia-Ukraine: European energy crisis, price behavior

Question: In each crisis, how long did the physical supply disruption last,
and how did prices behave AFTER the disruption ended?

### 8. Data Requirements
**Free (current):**
- HyperLiquid API: prices, positions, candles, L2 book, funding
- Binance API: BTC/crypto prices, historical candles
- AIS data: aisstream.io (user has API key for AUS_FUEL_WATCH)

**Would improve analysis (potential budget):**
- ICE forward curve data (term structure, roll schedule)
- Kpler or Vortexa tanker tracking (professional grade, verified)
- Platts/Argus physical crude assessments (Dubai, Dated Brent)
- EIA weekly petroleum status reports (free, but delayed)

### 9. Catalyst Calendar
Maintain a living calendar of upcoming events that could move oil:
- **Apr 6:** Trump deadline for Iran
- **Apr 7-13:** BZM6→BZN6 contract roll
- **Weekly:** EIA inventory report (Wednesdays)
- **Monthly:** OPEC+ meeting decisions
- **Ongoing:** US military Hormuz operations (4-6 week estimate from Mar 19)
- **Late Apr:** Possible partial Hormuz reopening
- **Jul-Aug:** SPR exhaustion if not replenished
