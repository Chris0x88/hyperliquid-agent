# Wiki -- HyperLiquid Trading System

This wiki is maintained by Claude Code. See MAINTAINING.md for the maintenance process.

## Reading Order (for new sessions)

1. `docs/plans/MASTER_PLAN.md` -- current architecture, phase status, session workflow
2. The relevant package `CLAUDE.md` for whatever you are working on
3. `docs/wiki/build-log.md` if you need historical context

## Pages

### Architecture Decisions

| ADR | Title | Summary |
|-----|-------|---------|
| [001](decisions/001-agentic-architecture.md) | Agentic Architecture | v1 daemon to v2 interface to v3 tool-calling evolution |
| [002](decisions/002-conviction-engine.md) | Conviction Engine | Two-layer thesis system with staleness clamping and kill switch |
| [003](decisions/003-openclaw-bypass.md) | OpenClaw Bypass | Direct OpenRouter calls instead of gateway routing |
| [004](decisions/004-menu-system.md) | Menu System | Interactive Telegram buttons with in-place editing |
| [005](decisions/005-interface-first.md) | Interface-First | Why visible interfaces beat invisible daemons |
| [006](decisions/006-protection-chain.md) | Protection Chain | Composable risk protections with worst-gate-wins |
| [007](decisions/007-renderer-abc.md) | Renderer ABC | UI portability layer for Telegram, web, and tests |
| [008](decisions/008-triple-mode-tools.md) | Triple-Mode Tools | Native + regex + AST fallback for free model tool calling |
| [009](decisions/009-embedded-agent-runtime.md) | Embedded Agent Runtime | Claude Code architecture ported to Python — parallel tools, streaming, compaction |
| [014](decisions/014-guardian-system.md) | Guardian Angel | Dev-side meta-system — in-session cartography, drift, gate, friction, sub-agent synthesis |

### Build History

| Page | Summary |
|------|---------|
| [build-log.md](build-log.md) | Chronological timeline of versions, incidents, and milestones |

### Docs Structure

| Directory | Contains |
|-----------|---------|
| `docs/plans/` | **Living docs only** — MASTER_PLAN, NORTH_STAR, CONSTITUTION, OIL_BOT_PATTERN specs, active expansion plans. These are always current. |
| `docs/plans/archive/` | Superseded versions of living docs (old MASTER_PLANs, etc.) |
| `docs/reports/` | **Historical records** — point-in-time reviews, assessments, completed phase plans. Named `YYYYMMDD - NAME.md` so they sort chronologically. Never superseded — just accumulate. |

### Reference (in package CLAUDE.md files)

| Package | Location | Covers |
|---------|----------|--------|
| Root | `CLAUDE.md` | Core rules, trading safety, OpenClaw boundary |
| cli/ | `cli/CLAUDE.md` | CLI entry point, commands, engine, exchange adapter |
| common/ | `common/CLAUDE.md` | Models, snapshots, renderer ABC, credentials, memory |
| exchange/ | `exchange/CLAUDE.md` | HyperLiquid proxy, risk manager, position tracking, order execution |
| daemon/ | `daemon/CLAUDE.md` | Clock, iterators, tiers, daemon lifecycle |
| engines/ | `engines/CLAUDE.md` | Analysis (radar, pulse, apex), protection (guard, trailing stop), learning (reflect, journal), data (candle cache, heatmap) |
| trading/ | `trading/CLAUDE.md` | Heartbeat, conviction engine, oil bot-pattern, thesis system |
| agent/ | `agent/CLAUDE.md` | AI runtime, tools, context pipeline, prompts |
| telegram/ | `telegram/CLAUDE.md` | Telegram bot UI, commands, menus, approval flow |
