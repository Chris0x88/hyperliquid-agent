# parent/ — Exchange Layer

All communication with HyperLiquid flows through this package. `hl_proxy.py` is the single gateway with 17 importers — the second most-depended-on module after `common/models.py`.

## Key Files

| File | Purpose | Importers |
|------|---------|-----------|
| `hl_proxy.py` | HyperLiquid SDK wrapper. Market data, order execution, account state. Real + mock modes. | 17 |
| `risk_manager.py` | Risk limit enforcement: max position, max notional, max leverage, daily drawdown | 9 |
| `position_tracker.py` | Track open positions across ticks | 6 |
| `store.py` | Persistent state for trades and fills | 3 |
| `house_risk.py` | House-level (portfolio) risk aggregation | 2 |
| `sdk_patches.py` | Monkey-patches for the HL Python SDK (spot meta indexing) | 1 |

## HLProxy Key Methods

```python
# Market data
get_snapshot(instrument) → MarketSnapshot
get_candles(coin, interval, lookback_ms) → List[Dict]
get_all_markets() → list
get_all_mids() → Dict[str, str]

# Execution
place_order(instrument, side, size, price, tif="Ioc") → Optional[Fill]
place_trigger_order(coin, is_buy, size, trigger_px, order_type, tpsl) → Dict
cancel_order(instrument, oid) → bool

# Account
get_account_state() → Dict
set_leverage(leverage, coin, is_cross=True)
```

## Critical Notes

- **xyz clearinghouse**: Oil, gold, silver trades need `dex='xyz'` in API calls. The SDK handles this via `_exchange` object.
- **Coin name normalization**: xyz returns `xyz:BRENTOIL`, native returns `BTC`. Always handle both forms.
- **Vault trading**: Pass `vault_address` to HLProxy constructor for vault operations.
- **Fill model**: Venue-agnostic `Fill` dataclass with Decimal precision.
- **Rate limits**: HL API returns 429 at ~3+ requests/second. Add 300ms delays between sequential calls.

## v3 Context: Agent Tools Path

The AI agent's tools call through hl_proxy:
```
agent_tools.py → live_price → hl_proxy.get_all_mids()
agent_tools.py → check_funding → hl_proxy (metaAndAssetCtxs)
agent_tools.py → place_trade → hl_proxy.place_order()
agent_tools.py → account_summary → hl_proxy (clearinghouseState, both dex)
```

## Upstream
- `cli/agent_tools.py` — v3 agent tools (live_price, place_trade, check_funding)
- `cli/daemon/iterators/connector.py` — daemon data feed
- `cli/mcp_server.py` — MCP tool calls
- `common/heartbeat.py` — heartbeat position checks
- `common/market_snapshot.py` — snapshot building

## Downstream
- `hyperliquid-python-sdk` (external dependency)
- `common/models.py` — data structures

## Current Status (v3)
- Working. SDK patches applied. Both mainnet and testnet supported.
- Rate limiting fix applied in heartbeat (not in proxy itself — could be added as middleware).
- Used by both the running heartbeat AND the AI agent tools.

## Testing
```bash
.venv/bin/python -m pytest tests/test_hl_adapter.py tests/test_store.py tests/test_sdk_patches.py -x -q
```
