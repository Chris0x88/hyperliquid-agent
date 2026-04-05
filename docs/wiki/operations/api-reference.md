# API Reference

Three access paths for pulling data from a running agent:

| Path | Protocol | Best For |
|------|----------|----------|
| HTTP REST | HTTP/JSON | Dashboards, monitoring, external integrations |
| SSE Feed | Server-Sent Events | Live streaming to frontends |
| MCP Server | Model Context Protocol | AI agent orchestration (Claude, OpenClaw) |

All endpoints are unauthenticated. Plan network security accordingly.

## HTTP REST Endpoints

| Method | Path | Response | Latency |
|--------|------|----------|---------|
| `GET` | `/health` | JSON health check | <10ms |
| `GET` | `/api/status` | Full state, positions, PnL | <100ms |
| `GET` | `/api/strategies` | Strategy catalog + YEX markets | <100ms |
| `GET` | `/api/feed` | SSE stream (persistent) | -- |
| `GET` | `/status` | Plain-text status (human-readable) | <1s |
| `POST` | `/api/skill/install` | Verify CLI installed | <2s |
| `POST` | `/api/pause` | Send SIGSTOP to trading process | <10ms |
| `POST` | `/api/resume` | Send SIGCONT to resume | <10ms |

### Key Endpoints

**`GET /api/status`** returns: `status`, `engine`, `tick_count`, `daily_pnl`, `total_pnl`, `active_slots[]`, `positions[]`. Data source: `$DATA_DIR/apex/state.json` or `$DATA_DIR/cli/state.db`.

**`GET /api/feed`** (SSE) pushes status JSON every time `tick_count` advances. De-duplicated, emits immediately on connect. APEX ticks default to 60s intervals.

**`POST /api/pause`** -- Warning: pausing stops trailing stop updates. Positions are unprotected during pause.

### CORS

All `/api/*` endpoints return CORS headers. Set `CORS_ORIGIN` env var to restrict origins in production.

## MCP Server

Start with `hl mcp serve` (stdio) or `hl mcp serve --transport sse` (remote).

### Claude Code Configuration

```json
{
  "mcpServers": {
    "hyperliquid-agent": {
      "command": "hl",
      "args": ["mcp", "serve"]
    }
  }
}
```

### MCP Tools

**Fast tools (sub-second, no subprocess):**
- `strategies()` -- Strategy catalog
- `builder_status()` -- Builder fee config
- `wallet_list()` -- Saved keystores
- `wallet_auto()` -- Create wallet non-interactively
- `setup_check()` -- Validate environment
- `agent_memory()` -- Read agent learnings, parameter changes
- `trade_journal()` -- Structured position records
- `judge_report()` -- Signal quality evaluation

**Action tools (subprocess, seconds to minutes):**
- `account(mainnet)` -- Balances, margins, positions
- `status()` -- Current positions and risk state
- `trade(instrument, side, size)` -- Place IOC order
- `run_strategy(strategy, instrument, ...)` -- Start strategy loop (long-running)
- `radar_run(mock)` -- Screen all perps for setups
- `apex_status()` -- APEX orchestrator state
- `apex_run(mock, max_ticks, preset, mainnet)` -- Start APEX (long-running)
- `reflect_run(since)` -- Performance review and recommendations

## Direct State File Access

When you have filesystem access:

```bash
cat $DATA_DIR/apex/state.json       # APEX state
tail -10 $DATA_DIR/apex/trades.jsonl # Recent trades (JSONL, string-encoded financials)
sqlite3 $DATA_DIR/cli/state.db "SELECT key, value FROM kv"  # StateDB
cat $DATA_DIR/radar/scan-history.json
cat $DATA_DIR/reflect/report-latest.md
tail -5 $DATA_DIR/journal/entries.jsonl
```

## Deployment Modes

Set `RUN_MODE` env var:

- **`apex`** -- Multi-slot orchestrator (default)
- **`strategy`** -- Single named strategy
- **`mcp`** -- MCP server for AI agent control

Base URL is `http://localhost:$PORT` (default 8080) locally or your Railway/deployment URL remotely.
