# Phase 2: Immediate Fixes + Daemon Switch

> **Status: NEXT**
> **Estimated: 1-2 sessions**

## 2a. Immediate Fixes (do first, small/high-impact)

### Add `update_thesis` MCP tool
**File:** `cli/mcp_server.py`
```
update_thesis(market, direction, conviction, summary, invalidation_note="")
```
- Read existing thesis from `data/thesis/{market}_state.json`
- Update conviction, direction, summary, timestamp
- Save back. Return old vs new conviction.
- This closes the feedback loop — agent can persist analysis.

### Add `live_price` MCP tool
**File:** `cli/mcp_server.py`
```
live_price(markets="all")
```
- Fetch current mids from HL API (default + xyz clearinghouse)
- Return compact: `BTC: $68,130 | BRENTOIL: $100.40`
- Lightweight alternative to full market_context.

### Add failure alerting
**File:** `common/heartbeat.py`
- At `heartbeat_consecutive_failures >= 10` → Telegram alert
- Repeat at 30, 90 failures
- Reset counter on first success after failure streak

### Clear stale thesis
**File:** `data/thesis/xyz_brentoil_state.json`
- Position closed → conviction=0.0, direction="neutral", clear evidence

### Update OpenClaw workspace
**Files:** `openclaw/TOOLS.md`, `openclaw/AGENT.md`, `openclaw/MEMORY.md`
- Document new MCP tools
- Add instruction for agent to update thesis after analysis
- Log the pipeline failure as a learning

## 2b. Daemon Activation (the big switch)

### Safety-first startup sequence:

```bash
# Step 1: Mock mode, 10 ticks — verify iterators load
hl daemon start --tier watch --mock --max-ticks 10

# Step 2: Real data, limited ticks — verify API connectivity
hl daemon start --tier watch --max-ticks 100

# Step 3: Extended run — verify stability over hours
hl daemon start --tier watch --max-ticks 1000

# Step 4: Create launchd plist, run alongside heartbeat 24h
# Step 5: Stop heartbeat, daemon takes over
```

### Safety checklist:
- [ ] WATCH tier does NOT touch positions (verified: true)
- [ ] Circuit breaker: 5 failures → auto-downgrade tier
- [ ] Mock mode: logs orders without executing
- [ ] Max-ticks: prevents runaway
- [ ] Existing stops preserved in WATCH tier
- [ ] Before REBALANCE tier: clear existing manual stops, let daemon manage fresh
- [ ] Test on testnet before mainnet

### Daemon launchd plist (create during this phase):
**File:** `plists/com.hyperliquid.daemon.plist`
- Program: `.venv/bin/python -m cli.main daemon start --tier watch --mainnet`
- Interval: continuous (daemon has its own tick loop)
- KeepAlive: true
- Stdout/stderr: `data/daemon/daemon_launchd.log`

### What the daemon's WATCH tier activates (vs heartbeat):
| Iterator | In Heartbeat? | In Daemon WATCH? | Benefit |
|----------|--------------|------------------|---------|
| Connector | Partial | Full | Proper market data pipeline |
| AccountCollector | No | Yes | Timestamped snapshots, HWM, drawdown |
| MarketStructure | No | Yes | Pre-computed technicals |
| ThesisEngine | Partial | Full | Proper conviction loading + staleness |
| Liquidity | No | Yes | Weekend/after-hours regime detection |
| Risk | Partial | Full | Risk gate: OPEN/COOLDOWN/CLOSED |
| AutoResearch | No | Yes | 30-min learning loop |
| MemoryConsolidation | No | Yes | Hourly context compression |
| Journal | No | Yes | Tick snapshots for audit |
| Telegram | Partial | Full | Rate-limited, structured alerts |

## Verification

```bash
# 1. Run tests
cd agent-cli && .venv/bin/python -m pytest tests/ -x -q

# 2. Test MCP tools
.venv/bin/python -c "from cli.mcp_server import create_mcp_server; m = create_mcp_server(); print(sorted(m._tool_manager._tools.keys()))"

# 3. Test daemon WATCH
hl daemon start --tier watch --mock --max-ticks 5

# 4. Test live_price
# (via OpenClaw agent DM or MCP test)

# 5. Test update_thesis
# (write test conviction, verify file updated)
```

## Done Criteria
- [ ] MCP server has 19 tools (17 existing + update_thesis + live_price)
- [ ] Heartbeat alerts on 10+ consecutive failures
- [ ] Daemon WATCH runs clean for 100+ ticks
- [ ] Daemon launchd plist created and tested
- [ ] OpenClaw agent can call live_price and update_thesis
- [ ] BRENTOIL thesis cleared (position closed)
