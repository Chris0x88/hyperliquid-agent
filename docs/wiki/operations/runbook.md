# Operational Runbook

## Starting & Stopping

### Start (Railway)

```bash
railway up
```

The entrypoint starts a health server on `$PORT` (default 8080) then launches the configured `RUN_MODE`.

### Start (Local)

```bash
hl apex run --preset default --budget 1000 --data-dir data/apex
```

### Stop

Send `SIGTERM`. The runner will stop accepting new positions, leave exchange-level stop-losses in place, persist state to `data/apex/state.json`, and exit cleanly.

**Never use `kill -9`** -- this skips state persistence and can leave orphaned positions.

### Verify After Stop

```bash
hl apex status
hl apex reconcile
```

## Common Alerts

| Alert | Cause | Action |
|-------|-------|--------|
| `CRITICAL: API circuit breaker open` | 5+ consecutive API failures | Check HL API status and network. Resets automatically on next successful call. |
| `CRITICAL: N consecutive tick timeouts` | Tick execution exceeded 30s 3x | Check HL API latency. Reduce instruments scanned by Pulse. |
| `WARNING: Rate limited (429)` | Too many API calls | Usually self-resolving (exponential backoff). If persistent, reduce scan frequency. |
| `WARNING: Tick N took Xs` | Tick > 80% of interval | Check which phase is slow (Pulse candle fetch is common). Consider increasing `tick_interval`. |

## Safe Mode

When the engine enters safe mode (no new entries, existing guards still function):

1. Diagnose root cause via `/metrics` or `hl apex status`
2. If resolved, restart the runner (safe mode resets on restart)
3. Or use API: `POST /api/configure` with `{"params": {"safe_mode": false}}`

## Reconciliation

```bash
hl apex reconcile          # Check for discrepancies
hl apex reconcile --fix    # Auto-fix orphaned positions/slots
```

Run after crashes, network outages, or any unclean shutdown.

## Emergency Position Close

```bash
hl apex close <slot_id>    # Close specific slot
hl apex close --all        # Close all positions
```

If CLI is unavailable, use the HyperLiquid web UI directly.

## Key Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `RUN_MODE` | `apex` | `apex`, `strategy`, `mcp` |
| `APEX_PRESET` | `default` | `conservative`, `default`, `aggressive` |
| `APEX_BUDGET` | auto | Total trading capital |
| `APEX_SLOTS` | `3` | Max concurrent positions |
| `HL_TESTNET` | `true` | `false` for mainnet |
| `API_AUTH_TOKEN` | unset | Bearer token for control endpoints |
| `DATA_DIR` | `/data` | Persistent state directory |
| `TICK_INTERVAL` | varies | Seconds between ticks |

## Railway Deployment Checklist

- `HL_PRIVATE_KEY` or keystore credentials configured
- `HL_TESTNET=false` for mainnet
- `APEX_BUDGET` set to desired capital
- `API_AUTH_TOKEN` set for control endpoint security
- Persistent volume mounted at `/data`
- Health check endpoint `/health` responds with 200
- Run `hl apex reconcile` after first deploy
- Monitor `/metrics` for tick latency and error counts
