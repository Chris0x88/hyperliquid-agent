# modules/ — Engine Modules

Core engines plus utilities. Pure computation (zero I/O) — `_guard` classes handle persistence separately.

## Core Engines

| Engine | Key File | Purpose | Status |
|--------|----------|---------|--------|
| APEX | `apex_engine.py` | Multi-slot autonomous trading | Wired via `cli/daemon/iterators/apex_advisor.py` (dry-run, WATCH tier only). Standalone runner at `skills/apex/scripts/standalone_runner.py`. |
| GUARD | `guard_bridge.py` | Trailing stops + profit protection | Wired to daemon |
| RADAR | `radar_engine.py` | Market scanner — find setups | Wired to daemon |
| PULSE | `pulse_engine.py` | Capital inflow detector | Wired to daemon |
| REFLECT | `reflect_engine.py` | Trade outcome analysis, convergence | CLI only (Phase 3) |
| JOURNAL | `journal_engine.py` | Structured trade journal | CLI only (Phase 3) |
| MEMORY | `memory_engine.py` | Playbook per instrument/signal | CLI only (Phase 3) |
| LESSON | `lesson_engine.py` | Verbatim trade post-mortems: `Lesson` dataclass, sentinel-wrapped prompt builder, strict response parser. Persistence lives in `common/memory.py` (lessons table + FTS5). | Fully wired end-to-end (2026-04-09 wedges 5-6). `lesson_author` iterator consumes closed positions from `data/research/journal.jsonl`. Agent tools: `search_lessons` (BM25), `get_lesson`. Top-5 lesson injection runs per agent decision. `/lessonauthorai` for AI-authored candidates. First real closed trade pending. |

## Key Utilities

| Module | Purpose |
|--------|---------|
| `candle_cache.py` | OHLCV SQLite cache — **v3 critical path** (AI agent depends on this) |
| `radar_technicals.py` | EMA, RSI, ADX, ATR calculations |
| `trailing_stop.py` | Trailing stop price computation |
| `reconciliation.py` | Position reconciliation |

**Deep dive:** [docs/wiki/components/conviction-engine.md](../docs/wiki/components/conviction-engine.md)

## Gotchas

- `candle_cache.py` changes affect AI agent tool responses
- Engines are pure computation — daemon iterators call them, never the reverse
