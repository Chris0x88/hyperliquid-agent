# web/ — Dashboard

Local web dashboard, control panel, and documentation site for the HyperLiquid Bot.

> Renamed from "Mission Control" to "Dashboard" 2026-04-17 — see
> [project_dashboard_rename memory](file:///Users/cdi/.claude/projects/-Users-cdi-Developer-HyperLiquid-Bot/memory/project_dashboard_rename.md).
> Don't reintroduce the old name in user-visible surfaces.

## Packages

| Directory | Purpose | Port |
|-----------|---------|------|
| `api/` | FastAPI backend — reads same data files as daemon/telegram bot | 8420 |
| `dashboard/` | Next.js 15 + Bun frontend — monitoring cockpit + control panel | 3000 |
| `docs/` | Astro Starlight documentation site (public-deployable) | 4321 |

## Running

```bash
# Backend (from agent-cli/)
.venv/bin/uvicorn web.api.app:create_app --factory --host 127.0.0.1 --port 8420

# Frontend (from web/dashboard/)
bun run dev

# Docs (from web/docs/) — DO NOT use `bun run dev`, astro dev server is broken
bun run serve
```

## Architecture

- Backend reads the same JSON/JSONL/YAML/SQLite files the daemon writes to
- Data access layer (`api/readers/`) has abstract interfaces — swap for NautilusTrader/DB later
- Frontend uses polling (3-60s depending on page) + SSE for real-time log streaming
- Charts page: 3s tick polling for live candle updates via `series.update()`
- All bound to 127.0.0.1 — local only
- Bearer token auth (auto-generated on first launch, stored in `web/.auth_token`)

## Design System

- **Colors**: Primary #A26B32, Secondary #8F7156, Tertiary #87CAE6, Neutral #7E756F
- **Fonts**: Space Grotesk (headings), Inter (body), Geist Mono (data)
- **Theme tokens**: `dashboard/src/lib/theme.ts`

## Key Files

| File | Purpose |
|------|---------|
| `api/app.py` | FastAPI factory with CORS + auth |
| `api/auth.py` | Bearer token authentication |
| `api/routers/*.py` | API endpoints (account, health, daemon, thesis, config, logs, etc.) |
| `api/readers/*.py` | Data access layer (file-based, DB-swappable) |
| `dashboard/src/app/page.tsx` | Dashboard home page |
| `dashboard/src/app/control/page.tsx` | Control panel (iterators, config, authority) |
| `dashboard/src/app/logs/page.tsx` | Log viewer with SSE streaming |
| `dashboard/src/lib/theme.ts` | Design tokens |
| `dashboard/src/lib/api.ts` | Typed API client |

## Learning Paths

- [Understanding the Web Dashboard](../docs/wiki/learning-paths/understanding-web-dashboard.md) — architecture, pages, API integration
- [Understanding Config](../docs/wiki/learning-paths/understanding-config.md) — how the control panel reads/writes config
- [Understanding Data Flow](../docs/wiki/learning-paths/understanding-data-flow.md) — how dashboard data connects to daemon output
