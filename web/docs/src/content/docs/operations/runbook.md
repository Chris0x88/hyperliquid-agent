---
title: Runbook
description: Day-to-day operations — starting, stopping, health checks, alerts, emergency close, and key file locations.
---

import { Aside } from '@astrojs/starlight/components';

## Starting the System

### Telegram Bot

```bash
cd agent-cli
.venv/bin/python -m cli.telegram_bot
```

### Daemon

```bash
cd agent-cli

# WATCH tier (production default), 120-second ticks
.venv/bin/python -m cli.main daemon start --tier watch --tick 120

# Or with the hl alias if configured
hl daemon start --tier watch --tick 120
```

The daemon enforces single-instance via PID kill — starting a second instance terminates the first.

### Web API

```bash
cd agent-cli
.venv/bin/uvicorn web.api.app:create_app --factory --host 127.0.0.1 --port 8420
```

### Web Dashboard

```bash
cd agent-cli/web/dashboard
bun run dev
```

Runs on port 3000 by default. Bound to 127.0.0.1 (local only).

### Docs Site

```bash
cd agent-cli/web/docs
bun run dev
```

Runs on port 4321 by default.

---

## Stopping the System

<Aside type="caution" title="Use SIGTERM, not SIGKILL">
Always stop the daemon with SIGTERM. This allows clean state persistence and leaves exchange-side stops in place. `kill -9` skips state persistence.
</Aside>

```bash
# Stop daemon gracefully
kill $(cat agent-cli/data/daemon/daemon.pid)

# Stop telegram bot
# Use Ctrl+C or kill the process
```

---

## Health Checks

### Telegram Commands

```
/health        Account equity, margin, daemon status
/readiness     Tier state, iterator status, thesis freshness
/diag          Detailed diagnostics, last tick time, error counts
```

### Manual Checks

```bash
# Check daemon PID
cat agent-cli/data/daemon/daemon.pid

# Check working state (ATR, prices, escalation)
cat agent-cli/data/memory/working_state.json

# Run test suite
cd agent-cli && .venv/bin/python -m pytest tests/ -x -q
```

---

## Common Alerts and Actions

| Alert | Cause | Action |
|-------|-------|--------|
| `CRITICAL: Missing SL on <COIN>` | Position found without stop-loss | Daemon will auto-place. Verify with `/orders`. |
| `WARNING: Liquidation cushion <15%` | Position approaching liquidation | Check leverage, consider reducing size |
| `CRITICAL: Liquidation cushion <10%` | Position dangerously close | Immediately reduce position or add margin |
| `WARNING: Thesis stale (>72h)` | Thesis file not updated | Update thesis or formally park it |
| `WARNING: Daemon not running` | PID file missing or process dead | Restart daemon |
| `API rate limit (429)` | Too many API calls | Self-resolving (exponential backoff). If persistent, reduce tick frequency. |

---

## Emergency Position Close

<Aside type="danger" title="Button confirmation required">
The `/close` command requires explicit button confirmation before executing. This prevents accidental closes.
</Aside>

```bash
# Via Telegram bot (preferred if running)
/close BRENTOIL

# Via CLI directly
cd agent-cli && .venv/bin/python -m cli.main trade close BRENTOIL

# Last resort: use HyperLiquid web UI at app.hyperliquid.xyz
```

---

## Updating Thesis Files

1. Edit `data/thesis/<COIN>.json` (e.g., `BRENTOIL.json`, `GOLD.json`)
2. Set the `conviction` field (0.0 to 1.0)
3. Set `take_profit_price` for the TP target
4. Verify the conviction engine picks it up: `/thesis` in Telegram

Thesis files are valid for months or years. Do not clamp aggressively on age.

---

## Running Tests

```bash
cd agent-cli
.venv/bin/python -m pytest tests/ -x -q
```

All tests should pass. Never modify test expectations to make tests pass — fix the source code.

---

## Key File Locations

| File | Purpose |
|------|---------|
| `data/daemon/daemon.pid` | Daemon process ID |
| `data/memory/memory.db` | Main SQLite database |
| `data/memory/working_state.json` | Current ATR, prices, escalation state |
| `data/thesis/` | Thesis JSON files (BRENTOIL.json, GOLD.json, etc.) |
| `data/config/markets.yaml` | Market registry |
| `data/config/market_config.json` | Market-specific configuration |
| `data/config/risk_caps.json` | Risk cap thresholds |
| `data/config/watchlist.json` | Active watchlist |
| `data/config/news_ingest.json` | News ingestion kill switch |
| `data/config/oil_botpattern.json` | Oil Bot-Pattern kill switch |
| `data/config/escalation_config.json` | Alert escalation settings |
| `.env` | Secrets (never commit) |
| `web/.auth_token` | Web API bearer token (auto-generated) |

---

## Tier System

The daemon operates in one of three tiers. Production default is WATCH.

| Tier | Capabilities |
|------|-------------|
| **WATCH** | Read-only monitoring, alerts, thesis tracking |
| **REBALANCE** | Adds execution_engine, exchange_protection, guard, rebalancer, profit_lock, catalyst_deleverage |
| **OPPORTUNISTIC** | Everything enabled |

Promote via `/activate` command. Per-asset delegation via `/delegate`. See the [Tiers](/operations/tiers/) page for promotion checklists.
