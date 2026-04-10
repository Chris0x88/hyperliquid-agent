---
title: Runbook
description: Day-to-day operations — starting, stopping, health checks, alerts, and incident response.
---

import { Aside } from '@astrojs/starlight/components';

## Starting the System

### Via launchd (production)

```bash
# Load all services (daemon + telegram + heartbeat)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.daemon.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.telegram.plist

# Check status
launchctl list | grep hyperliquid
```

### Manual start (testing/debugging)

```bash
cd agent-cli
source .venv/bin/activate

# Daemon (WATCH tier, 120s ticks)
python -m cli.main daemon start --tier watch --tick 120

# Telegram bot
python -m cli.telegram_bot

# Heartbeat (usually managed by launchd)
python -m common.heartbeat
```

---

## Stopping the System

<Aside type="caution" title="Use SIGTERM, not SIGKILL">
Always stop the daemon with SIGTERM (or launchctl stop). This allows clean state persistence and leaves exchange-side stops in place. `kill -9` skips state persistence.
</Aside>

```bash
# Stop via launchd
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.daemon.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.hyperliquid.telegram.plist

# Verify stopped
launchctl list | grep hyperliquid
```

---

## Health Checks

### Telegram quick checks

```
/health        → Account equity, margin, daemon status
/readiness     → Tier state, iterator status, thesis freshness
/diag          → Detailed diagnostics, last tick time, error counts
```

### Manual checks

```bash
# Check daemon PID
cat agent-cli/data/daemon/daemon.pid

# Check last heartbeat
ls -la agent-cli/data/memory/working_state.json

# Check memory DB health
python -m cli.main memory status
```

---

## Common Alerts and Actions

| Alert | Cause | Action |
|-------|-------|--------|
| `CRITICAL: Missing SL on <COIN>` | Heartbeat found position without stop | Heartbeat will auto-place. Verify with `/orders`. |
| `WARNING: Liquidation cushion <15%` | Position near liquidation | Check leverage, consider reducing size |
| `CRITICAL: Liquidation cushion <10%` | Position dangerously near liquidation | Immediately reduce position or add margin |
| `WARNING: Thesis stale (>72h)` | Thesis file not updated | Update or formally park the thesis |
| `WARNING: Daemon not running` | PID file missing or process dead | Restart daemon via launchd |
| `API rate limit (429)` | Too many API calls | Self-resolving (exponential backoff). If persistent, reduce tick frequency. |
| `Consecutive tick timeout` | Tick execution exceeded 30s 3x | Check HL API latency, consider increasing tick interval |

---

## Emergency Position Close

If the daemon is down and you need to close positions:

```bash
# Via Telegram bot (if running)
/close BRENTOIL

# Via CLI directly
python -m cli.main trade close BRENTOIL

# Last resort: use HyperLiquid web UI at app.hyperliquid.xyz
```

---

## Memory Database Restore

If memory.db is corrupted, restore from the hourly backups:

```bash
# List available backups
ls agent-cli/data/memory/backups/

# Restore a specific backup
python -m cli.main memory restore --backup data/memory/backups/memory_2026-04-10_12-00.db

# Verify restored state
python -m cli.main memory status
```

Backups are kept for: 24 hourly, 7 daily, 4 weekly.

---

## Updating Thesis Files

1. Open Claude Code in the `agent-cli` directory
2. Analyze current market situation
3. Write or update `data/thesis/BRENTOIL.json`
4. Verify conviction engine picks it up: `/thesis` in Telegram

Alternatively, ask the AI agent in Telegram:
```
Update the BRENTOIL thesis — here's my current view: [your analysis]
```

---

## Test Suite

Run after any code changes:

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
| `data/memory/working_state.json` | Current ATR, prices, escalation |
| `data/thesis/` | Thesis JSON files |
| `data/authority.json` | Per-asset delegation |
| `data/config/markets.yaml` | Market registry |
| `data/config/news_ingest.json` | News ingestion kill switch |
| `.env` | Secrets (never commit) |
