---
title: Web Dashboard
description: Mission Control — the local-only web platform for monitoring and managing the trading system.
---

The Web Dashboard is a three-package local platform that provides real-time visibility into account state, daemon health, thesis management, and strategy execution. Every component binds to `127.0.0.1` — nothing is exposed to the internet.

## Architecture

| Package | Stack | Port | Purpose |
|---------|-------|------|---------|
| **API** | FastAPI (Python) | 8420 | REST + SSE backend, reads daemon files directly |
| **Dashboard** | Next.js 15 + Bun | 3000 | Interactive frontend |
| **Docs** | Astro Starlight | 4321 | This documentation site |

All three packages live under `agent-cli/web/`. The API reads the same files the daemon writes — JSON, JSONL, YAML, and SQLite. There is no separate database; the file system is the source of truth. This design is intentional: it keeps the system simple and makes it straightforward to swap in a proper DB later without changing the daemon.

## Authentication

Bearer token auth protects every API endpoint and Dashboard route.

- On first launch, a token is auto-generated and written to `web/.auth_token`.
- The Dashboard reads this token automatically.
- For manual API calls, pass `Authorization: Bearer <token>` in the header.

No accounts, no passwords, no external auth providers.

## API Endpoints

The FastAPI backend groups endpoints by router:

| Router | Description |
|--------|-------------|
| `/health` | Liveness, readiness, daemon PID status |
| `/account` | Balance, positions, equity history, margin state |
| `/daemon` | Iterator status, uptime, restart triggers |
| `/thesis` | Read/update thesis files, conviction state |
| `/config` | Read/write daemon and strategy configuration |
| `/watchlist` | Managed watchlist, auto-added open positions |
| `/authority` | Per-asset delegation state (delegate/reclaim) |
| `/logs` | Log tail with SSE streaming for real-time output |
| `/news` | Headlines and catalysts from news_ingest |
| `/strategies` | Oil Bot-Pattern state, journal entries |
| `/charts` | OHLCV data, indicator overlays, live tick feed |
| `/alerts` | Unified alert and signal feed |

The `/logs` endpoint supports Server-Sent Events (SSE) for streaming log lines to the Dashboard without polling.

## Dashboard Pages

### Home

Account summary at a glance: total equity, unrealised PnL, margin usage, and open positions. An equity curve chart shows portfolio value over time. The positions table displays each market with entry, size, leverage, SL/TP levels, and current PnL.

### Control Panel

The operational hub:

- **Iterators** — start, stop, and monitor every daemon iterator with live status indicators.
- **Config Editor** — edit daemon and strategy JSON configs with validation.
- **Authority** — per-asset delegation table. Delegate or reclaim AI control for each coin.
- **Thesis Editor** — view and modify thesis files. See conviction scores, target prices, and invalidation levels.

### Logs

Real-time log viewer powered by SSE streaming. Logs flow in as they are written — no refresh needed. Filter by iterator name, log level, or free-text search.

### Strategies

Oil Bot-Pattern strategy state and execution journal. View gate chain status, conviction scores, drawdown brake levels, and the full trade journal with entry/exit reasoning.

### Alerts & Signals

Unified feed combining all alert sources: protection audit warnings, catalyst triggers, cascade detections, entry critic grades, and system health alerts. Sorted by time, filterable by source and severity.

### Charts

Lightweight-charts (TradingView) with configurable overlays:

- **Indicators**: Bollinger Bands, SMA, EMA
- **Live ticks**: 3-second refresh via the API tick feed
- **Timeframes**: 1m, 5m, 15m, 1h, 4h, 1d

Charts pull OHLCV data from the API, which reads cached market data from the daemon's data directory.

## Design System

| Element | Value |
|---------|-------|
| Primary | `#A26B32` (warm bronze) |
| Secondary | `#8F7156` (muted earth) |
| Tertiary | `#87CAE6` (sky blue) |
| Heading font | Space Grotesk |
| Body font | Inter |
| Data / mono font | Geist Mono |

## Running the Components

### API

```bash
cd agent-cli/web/api
../.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8420
```

### Dashboard

```bash
cd agent-cli/web/dashboard
bun install
bun run dev
```

### Docs

```bash
cd agent-cli/web/docs
bun install
bun run dev
```

## Data Access Pattern

The API layer is read-heavy. It reads files that the daemon writes:

- **JSON** — config files, thesis files, strategy state
- **JSONL** — journal entries, headlines, catalysts, bot patterns, heatmap zones
- **YAML** — some config and plan files
- **SQLite** — `memory.db` for lessons (with FTS5 search)

Write operations (config edits, thesis updates, authority changes) write back to the same files. The daemon picks up changes on its next iteration cycle. There is no message bus or IPC — the file system is the coordination layer.
