# Portfolio Strategy

## BTC + Oil Natural Hedge

The portfolio is structured as a natural hedge across two accounts:

- **BTC in vault (long):** Managed by Power Law rebalancer. At Power Law floor, downside is asymmetric -- it drops slower than it rallied.
- **Oil in main account (long):** Thesis-driven, AI-managed. Massive upside due to physical supply destruction with no spare capacity.

When one leg loses, the other gains more. Oil profits can be locked to create a buffer covering BTC drawdown. The key insight: think portfolio-level, not per-trade.

## Conviction-Based Sizing

Modeled after Stanley Druckenmiller's approach:

- Stay fully allocated, adjust leverage as confidence shifts
- **High conviction = aggressive leverage** (the way to build returns is preservation of capital AND home runs)
- **Broken thesis = immediate exit** (the first loss is the best loss -- but only when the thesis breaks, not just price)
- Concentrate heavily when conviction is high; Druckenmiller is not a diversifier
- Study what powerful people are DOING, not what they are SAYING

### Two-Layer Architecture

- **Layer 1 (ThesisState):** AI judgment on macro/conviction -- never overridden by Layer 2
- **Layer 2 (ExecutionEngine):** Adaptive sizing, timing, leverage reads from Layer 1

This ensures conviction drives execution, not the other way around.

### Sizing Discipline

- Start smaller, scale in on dips to thesis entry zones
- Do not chase. Do not enter aggressively at market price when the thesis says wait for better levels.
- Scale out on $5+ profit to reset lower entries -- work the volatility
- Trust the user's sizing instincts over formula when starting fresh

## Druckenmiller Principles

The trading approach is modeled after Druckenmiller:

- Macro conviction trader who takes massive positions when thesis is right
- Concentrates capital rather than diversifying across mediocre opportunities
- Cuts losses fast when thesis breaks, lets winners run far
- Thinks in terms of risk/reward asymmetry -- it is not about being right, it is about how much you make when you are right
- Studies central bank policy, currency flows, debt cycles
- His network includes key figures in the current policy architecture

## Locking Oil Profits

When oil is running, lock partial profits early to create a buffer:

1. Scale out portions on $5+ moves
2. These locked profits cover BTC drawdown if needed
3. Re-enter oil on dips to thesis levels (Friday close = cheap)
4. Net effect: oil volatility generates cash that subsidizes BTC patience

## BTC Power Law Vault

- Automated rebalancer based on Power Law model
- Originally designed for SaucerSwap (zero holding cost)
- On HyperLiquid, watch cumulative funding drag in bull markets
- When funding is negative (bear sentiment), longs get paid -- favorable for the hold strategy
- The Power Law signal is valuable on HL as directional bias; active trading may capture more than static hold-and-rebalance
