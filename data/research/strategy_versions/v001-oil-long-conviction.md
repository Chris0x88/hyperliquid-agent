# v001 — Oil Long Conviction

**Date:** 2026-03-30
**Status:** ACTIVE
**Markets:** xyz:BRENTOIL (long), BTC vault (long)

## Strategy
- BRENTOIL: LONG ONLY. Adjust leverage, never go flat while thesis holds.
- BTC: Power Law rebalancer in vault. Hold through drawdowns (floor at ~$55K).
- Natural hedge: oil up, BTC down. Portfolio balanced.

## Entry Logic
- Physical supply/demand thesis drives entries
- Scale in on confirmed dips, not FOMO
- Prefer high-liquidity periods

## Exit Logic
- Thesis breaks → close immediately
- Approaching liquidation → reduce leverage
- TP hit but momentum strong → let it ride
- Market clearly turning → close, wait, re-enter

## Risk Rules
- Chief goal: keep account alive
- 8% drawdown → alert
- 2% from liq → warning
- 1% from liq → auto-reduce leverage
- Rapid drop 3% in 5min → alert
- Size up when conviction highest (Druckenmiller)

## Edge
User's petroleum engineering expertise + macro thesis.
Physical supply destruction is permanent (Qatar 5-year repair).
Druckenmiller positioned same way. The power network is aligned.
