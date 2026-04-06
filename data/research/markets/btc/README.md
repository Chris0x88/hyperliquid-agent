# BTC — Power Law Rebalancer

## Thesis
Bitcoin follows a power-law corridor over long timeframes. The strategy rebalances
based on where price sits within this corridor:
- Near floor: increase allocation (accumulate)
- Near ceiling: decrease allocation (take profit)

## Current Status (2026-03-30)
- Running in vault: HWM Opportunistic MOE (`0x9da9a9aef5a968277b5ea66c6a0df7add49d98da`)
- Strategy: power_law_btc via `scripts/run_vault_rebalancer.py` (launchd daemon)
- **Leverage: 1x (NO LEVERAGE)** — allocation IS the exposure
- Position: 0.00344 BTC @ $67,503 (57% of $407 vault)
- Threshold: 10% deviation triggers rebalance
- Telegram: `/rebalancer start|stop|status`, `/rebalance` for force-immediate

## Model Signal (2026-03-30)
- BTC price: $67,512
- Power law floor: $58,647
- Power law ceiling: $135,610
- Model fair value: $88,978
- Position in band: 11.7% (deep value)
- Cycle: 5, 48% complete, late cycle peak zone
- Recommended allocation: 57% BTC

## Edge
The power law model has held since 2010. It's not a prediction — it's a framework
for systematic accumulation. The rebalancer automates what smart accumulators do manually.

## Risk
- Model breakdown (BTC deviates from power law permanently)
- Extended bear market below floor (strategy keeps buying, drawdown deepens)
- **Funding rate drag** (see Venue Economics below)

## Venue Economics — CRITICAL STRATEGIC QUESTION

### The Problem: Perp Carry Cost

The power law rebalancer was originally built for **SaucerSwap** (Hedera DEX):
- Trading fees: ~0.3% per swap (expensive)
- **Holding cost: ZERO** (you own spot BTC)
- Optimal threshold: 15% (minimizes swap fee impact)

On **HyperLiquid**, the economics are inverted:
- Trading fees: ~0.035% taker (cheap)
- **Holding cost: VARIABLE hourly funding** (expensive over time)
- Optimal threshold: 2-5% (capture more volatility, fees are negligible)

| Metric | SaucerSwap | HyperLiquid |
|--------|-----------|-------------|
| Trade cost | 0.3%/swap | 0.035%/swap |
| Hold cost | **FREE** | ±3-12%/yr (funding) |
| Rebalance threshold | 15% | 2-5% optimal |
| Best for | Low-frequency hold | Active trading |

### Funding Rate Dynamics

- **Bull market (crowded long):** Funding +0.01-0.03%/8h → longs pay 4-12%/yr
- **Bear/neutral (crowded short):** Funding negative → longs GET PAID
- **Current (2026-03-30):** Funding **-0.0004%/hr** (-3.71% annualized) → longs earning ~$0.71/mo on $232

Right now is the IDEAL scenario: power law says deep value AND the market pays you to be long. But this flips in bull markets.

### Strategic Implications

1. **If power law says fair value drops in 6 months:** Holding a long perp AND paying funding = worst case. The rebalancer would reduce allocation, but accumulated funding drag already ate into returns.

2. **SaucerSwap remains the better venue for the original strategy:** Low-frequency rebalancing with zero carry cost. The 15% threshold was correctly optimized for that venue.

3. **HyperLiquid's advantage is speed, not holding:** The power law signal is valuable on HL as a **directional bias**, not a static allocator. Future evolution:
   - Mean-reversion around a long bias (buy dips harder, trim rips)
   - Tighter rebalance bands (2-3%) since trading is nearly free
   - Maker orders for rebates instead of IOC takers
   - High-frequency volatility capture with power law as the directional north star

4. **The 6-month forward signal matters:** If the model forecasts lower fair value ahead, the HL strategy should be more aggressive about trimming on rallies rather than passively holding.

### Monitoring Plan
- Track `cumFunding.sinceOpen` on every hourly check
- Report weekly cumulative funding cost in Telegram
- Compare: funding drag vs rebalancing alpha vs just-hold-spot counterfactual
- If cumulative funding exceeds 2% of position value in a month → flag for review

## Architecture
- Daemon: `scripts/run_vault_rebalancer.py`
- launchd: `~/Library/LaunchAgents/com.hl-bot.vault-rebalancer.plist`
- Config: env vars (HL_VAULT_ADDRESS, POWER_LAW_MAX_LEVERAGE=1, etc.)
- Single instance enforced via PID file kill on startup
- HLProxy native vault_address support (orders go to vault, state reads from vault)
