# Learning Path: Web Dashboard & API

How the local web control plane works. Read these files in order.

---

## 1. `web/CLAUDE.md` -- Overview

**Start here.** The web layer has three packages:

| Package | Stack | Port | Purpose |
|---------|-------|------|---------|
| `web/api/` | FastAPI (Python) | 8420 | Backend -- reads same data files as daemon/bot |
| `web/dashboard/` | Next.js 15 + Bun | 3000 | Frontend -- monitoring cockpit + control panel |
| `web/docs/` | Astro Starlight | 4321 | Documentation site (public-deployable) |

All bound to `127.0.0.1` -- local only. No internet exposure.

Starting each component:
```bash
# Backend (from agent-cli/)
.venv/bin/uvicorn web.api.app:create_app --factory --host 127.0.0.1 --port 8420

# Frontend (from web/dashboard/)
bun run dev

# Docs (from web/docs/)
bun run serve    # NOT `bun run dev` -- Astro dev server is broken
```

**What you'll learn:** The three-package layout, port assignments, and how to start each piece.

---

## 2. `web/api/app.py` -- FastAPI factory

**The backend entry point.** `create_app()` (line ~37) builds a configured FastAPI instance:

- **CORS** (line ~46): allows `http://127.0.0.1:3000` and `http://localhost:3000` only (the Next.js frontend)
- **Auth token** (line ~19): auto-generated on first launch, persisted to `web/.auth_token` with `0o600` permissions. Bearer token auth.
- **Lifespan** (line ~30): stores the auth token and data dir in `app.state` on startup

### Router registration (lines ~58-69)

All 12 routers mounted under `/api/`:

| Prefix | Router | Purpose |
|--------|--------|---------|
| `/api/account` | `account.py` | Account status, positions, P&L, prices, orders, funding |
| `/api/health` | `health.py` | System health check |
| `/api/daemon` | `daemon.py` | Daemon state, tier, iterators, restart |
| `/api/thesis` | `thesis.py` | Thesis CRUD per market |
| `/api/config` | `config.py` | Config file listing, read, write |
| `/api/watchlist` | `watchlist.py` | Tracked markets list |
| `/api/authority` | `authority.py` | Per-asset delegation (agent/manual/off) |
| `/api/logs` | `logs.py` | Log history + SSE streaming |
| `/api/news` | `news.py` | Catalyst feed |
| `/api/strategies` | `strategies.py` | Oil bot pattern state + journals |
| `/api/charts` | `charts.py` | OHLCV candle data for charting |
| `/api/alerts` | `alerts.py` | Alert history/state |

**What you'll learn:** The full API surface, auth mechanism, and CORS policy.

---

## 3. `web/api/dependencies.py` -- Shared paths

**Three-line file, but critical.** Defines the canonical paths all routers use:

- `PROJECT_ROOT` = `agent-cli/` (resolved from file location)
- `DATA_DIR` = `agent-cli/data/`
- `STATE_DIR` = `agent-cli/state/`

Every router imports `DATA_DIR` to find its data files. This is the single point that would change if data moved.

**What you'll learn:** How routers find the same data files that the daemon writes to.

---

## 4. Key routers -- `account.py`, `daemon.py`, `charts.py`

**Read 2-3 routers to understand the API pattern.**

### `account.py` -- Account endpoints

- `GET /api/account/status` -- calls `common.account_state.fetch_registered_account_state()` to get live equity, positions, balances from HyperLiquid
- `GET /api/account/prices` -- calls `common.tools.live_price()` for current market prices
- `GET /api/account/orders` -- calls `common.tools.get_orders()` for open orders
- Uses `SqliteReader` for memory.db queries (account snapshots)
- Position mapping (line ~39): converts internal dict format to the shape the frontend TypeScript interface expects (HL API field names like `szi`, `entryPx`, `unrealizedPnl`)

### `daemon.py` -- Daemon control

- `GET /api/daemon/state` -- reads `data/daemon/state.json` + checks PID liveness
- `GET /api/daemon/iterators` -- lists all iterators with enabled/disabled state from `tiers.py`
- `PUT /api/daemon/iterators/{name}` -- toggle an iterator on/off
- `POST /api/daemon/restart` -- sends SIGHUP to the daemon PID

### `charts.py` -- Candle data

- `GET /api/charts/candles/{coin}?interval=1h&limit=500` -- returns OHLCV candles
- Uses `modules/candle_cache.CandleCache` as singleton DB connection
- Handles coin name aliases (both `BRENTOIL` and `xyz:BRENTOIL`)
- Auto-backfills from HyperLiquid API if cache has fewer than 50 candles
- Frontend polls this endpoint every 3 seconds for live chart updates

**What you'll learn:** The read-from-same-files pattern, how routers call `common/tools.py` functions, and the live backfill mechanism.

---

## 5. `web/api/readers/` -- Data access abstraction

**The layer between routers and raw files.** Abstract interfaces that can be swapped for database backends later.

| Reader | File | Purpose |
|--------|------|---------|
| `base.py` | ABC definitions | `ConfigReader`, `LogReader` base classes |
| `config_reader.py` | `FileConfigReader` | JSON/YAML config read/write with `.bak` backup |
| `jsonl_reader.py` | `JsonlReader` | Reads `.jsonl` files with limit/offset, tail mode |
| `log_reader.py` | `LogReader` | Log file tailing + SSE streaming generator |
| `sqlite_reader.py` | `SqliteReader` | Generic SQLite query helper (memory.db, candles.db) |
| `state_reader.py` | `StateReader` | Reads daemon state JSON files |

The key design: routers never open files directly. They go through readers. This means switching from file-based storage to a database (e.g., when NautilusTrader integration lands) only requires swapping the reader implementations.

**What you'll learn:** The pluggable data access pattern and why routers don't touch the filesystem directly.

---

## 6. `web/dashboard/src/app/page.tsx` -- Dashboard home

**The frontend entry point.** The home page assembles seven component panels:

```
Row 1: AccountSummary (2/3 width) + HealthPanel (1/3 width)
Row 2: EquityCurve (full width)
Row 3: PositionCards (1/2) + DaemonIteratorStatus (1/2)
Row 4: ThesisPanel (1/2) + NewsFeed (1/2)
```

Each component is a self-contained React component that:
1. Calls the typed API client on mount
2. Polls on an interval (typically 10-30s for dashboard, 3s for charts)
3. Renders with theme tokens from `theme.ts`

Other pages:
- `/control` -- control panel for iterators, config editing, authority management
- `/logs` -- log viewer with SSE streaming
- `/charts` -- interactive candlestick charts with live updates

**What you'll learn:** The component layout, polling pattern, and page structure.

---

## 7. `web/dashboard/src/lib/api.ts` -- Typed API client

**The frontend's interface to the backend.** Three base functions:

- `fetchJSON<T>(path)` -- GET with typed return
- `putJSON<T>(path, data)` -- PUT with JSON body
- `postJSON<T>(path, data)` -- POST with JSON body

All routes are relative to `/api` (proxied by Next.js to port 8420).

Exported functions map 1:1 to backend endpoints:
- `getAccountStatus()` -> `GET /api/account/status`
- `getDaemonState()` -> `GET /api/daemon/state`
- `getCandles(coin, interval, limit)` -> `GET /api/charts/candles/{coin}`
- `getAllTheses()` -> `GET /api/thesis/`
- `updateConfig(filename, data)` -> `PUT /api/config/{filename}`
- `toggleIterator(name, enabled)` -> `PUT /api/daemon/iterators/{name}`

TypeScript interfaces at the top of the file define the response shapes.

**What you'll learn:** The typed client pattern and how frontend calls map to backend routes.

---

## 8. `web/dashboard/src/lib/theme.ts` -- Design tokens

**The visual identity.** A single const object with:

- **Colors:** Primary #A26B32 (amber/copper), Secondary #8F7156, Tertiary #87CAE6 (sky blue), Neutral #7E756F
- **Semantic colors:** success (green), danger (red), warning (orange) with light/border variants
- **Surface colors:** dark theme -- bg #0d0e11, surface #1f2029, border #353849
- **Fonts:** Space Grotesk (headings), Inter (body), Geist Mono (data/numbers)
- **Radius:** 8px

All components import `theme` and use inline styles or CSS variables from these tokens.

**What you'll learn:** The design system and how to match the existing visual language when adding new UI.

---

## Architecture diagram

```
┌─────────────────────────────────────────────────┐
│                 Browser (localhost:3000)          │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │Dashboard │  │ Control  │  │  Charts  │  ...   │
│  │ page.tsx │  │ page.tsx │  │ page.tsx │        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       └──────────────┼──────────────┘             │
│                      v                            │
│               lib/api.ts                          │
│        (typed client, polling 3-60s)              │
└──────────────────────┬────────────────────────────┘
                       | HTTP (JSON)
                       v
┌──────────────────────────────────────────────────┐
│          FastAPI Backend (localhost:8420)          │
│                                                    │
│  app.py (factory + CORS + bearer auth)            │
│     |                                              │
│     ├── /api/account   (live HL API calls)        │
│     ├── /api/daemon    (state.json + PID)         │
│     ├── /api/charts    (candles.db + HL backfill) │
│     ├── /api/thesis    (thesis/*.json)            │
│     ├── /api/config    (config/*.json|yaml)       │
│     ├── /api/logs      (SSE streaming)            │
│     └── ...6 more routers                         │
│                                                    │
│  readers/  (data access abstraction layer)        │
│     ├── config_reader  (JSON/YAML + .bak)         │
│     ├── jsonl_reader   (JSONL with tail)          │
│     ├── log_reader     (file tail + SSE)          │
│     └── sqlite_reader  (memory.db, candles.db)    │
└──────────────────────┬────────────────────────────┘
                       | reads
                       v
┌──────────────────────────────────────────────────┐
│              data/ (shared filesystem)             │
│                                                    │
│  Same files the daemon and telegram bot write to. │
│  No database server. No message queue.            │
│  Just files on disk, read concurrently.           │
└──────────────────────────────────────────────────┘
```

### Key patterns

- **Polling, not WebSocket:** Frontend polls at 3-60s intervals depending on the page. Only logs use SSE for real-time streaming.
- **Read-only by default:** Most endpoints only read data. Config and authority endpoints are the only writers.
- **Same data, different view:** The web API reads the exact same files the daemon writes. No ETL, no sync, no duplication.
- **Auth:** Bearer token auto-generated on first launch, stored in `web/.auth_token`. Frontend proxies through Next.js (same-origin), so no token needed in browser.
