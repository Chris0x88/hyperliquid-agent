# STRATEGIST.md — OpenClaw Strategy Generation Playbook

When the user asks you to create a new quantitative trading strategy (e.g. "Write me a Bollinger Band Reversion for DOGE-PERP"), you act as the Senior Quant Developer.

DO NOT tell the user to use a third-party paid API for data. We construct indicators locally using Hyperliquid's raw historical feeds.

## Step 1: Clone the Scaffolding
Read the file `strategies/templates/base_strategy_template.py`.
This contains the exact SDK wrapper you need. Your custom strategy will inherit from `BaseStrategy`.

## Step 2: Extract Historical Data (Indicators)
Inside your `on_tick` method, extract the exact data you need using the active Proxy.
```python
if context and context.meta:
    proxy = context.meta.get("proxy") or context.meta.get("hl_proxy")
    
    # 1. Fetch live 1-minute or 5-minute candles
    # intervals: "1m", "5m", "15m", "1h", "4h", "1d"
    lookback = 1000 * 60 * 60 * 2  # 2 hours
    candles = proxy.get_candles(snapshot.instrument, "1m", lookback)
    
    # 2. Re-construct Indicator
    import numpy as np
    closes = [float(c["c"]) for c in candles]
    sma = np.mean(closes[-20:])
```

## Step 3: Implement Trading Logic
Write the exact statistical threshold checks or volume verifications.
Output the decisions clearly:

```python
decisions.append(StrategyDecision(
    type=DecisionType.ENTER_LONG,
    instrument=snapshot.instrument,
    confidence=0.95,
    size_usd=200.0,
    reason=f"Price {snapshot.mid_price} crossed SMA {sma}"
))
```

## Step 4: Write and Register
1. Save your completed class file directly into the `strategies/` folder (e.g., `strategies/doge_reversion.py`).
2. Update `cli/strategy_registry.py`. Add your strategy mapping to `STRATEGY_REGISTRY` so the Daemon can find it.
3. Inform the user they can launch it using:  
   `python -m cli.main run doge_reversion -i DOGE-PERP --tick 60`
