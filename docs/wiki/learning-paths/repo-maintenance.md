# Learning Path: Repository Maintenance

How to keep this codebase healthy as it grows. Written because things are
getting complex — 68K lines of production code, 42 iterators, 65+ commands,
25 config files, 5 knowledge systems. This guide tells you what to check,
where to look, and what to update when things change.

---

## The Knowledge Hierarchy

Everything flows from this principle (approved 2026-04-11):

```
Code          → Always correct. When code and docs disagree, code wins.
Wiki          → Developer reference. Updated when code changes.
Docs Site     → User-facing. Allowed to lag. Rebuilt periodically.
Memory        → User preferences + archived decisions. NEVER deleted.
Plans         → Write-once specs. Archived with dates when superseded.
```

**Full details**: `docs/plans/KNOWLEDGE_HIERARCHY_PROPOSAL.md`
**Maintenance guide**: `docs/plans/KNOWLEDGE_HIERARCHY_MAINTENANCE.md`

---

## Step 1: Before You Start Any Session

Read these files in order to orient yourself:

1. **`CLAUDE.md`** (root) — Core rules, trading safety, workflow. ~68 lines. Non-negotiable.
2. **`docs/plans/MASTER_PLAN.md`** — Living plan. What's built, what's next.
3. **`MEMORY.md`** (loaded automatically) — User preferences index.
4. **The relevant package `CLAUDE.md`** — e.g., `cli/daemon/CLAUDE.md` if touching the daemon.

**Critical rule from root CLAUDE.md**: Before claiming anything is missing or
unbuilt, also read `docs/plans/AUDIT_FIX_PLAN.md` AND the commits since the
last `alignment:` commit. This has burned sessions before (2026-04-07 postmortem).

```bash
git log --grep='alignment:' -1 --format='%H'  # Find last alignment commit
git log <that-hash>..HEAD --oneline            # What shipped since
```

---

## Step 2: Understand the File Layout

```
agent-cli/
├── cli/                    # Interface layer (Telegram, AI agent, daemon)
│   ├── telegram_bot.py     # Command handlers + main loop (4,137 lines)
│   ├── telegram_api.py     # Telegram API operations (extracted)
│   ├── telegram_hl.py      # HyperLiquid API queries (extracted)
│   ├── telegram_menu.py    # Interactive button menus (extracted)
│   ├── telegram_approval.py # Write-command approval flow (extracted)
│   ├── agent_runtime.py    # Core AI agent (563 lines, vendor-agnostic)
│   ├── telegram_agent.py   # Telegram AI adapter (2,568 lines)
│   ├── agent_tools.py      # 31 agent tools (1,914 lines)
│   ├── telegram_commands/  # 13 command modules (extracted handlers)
│   └── daemon/             # Tick engine
│       ├── clock.py        # Main loop
│       ├── context.py      # TickContext hub + Iterator Protocol
│       ├── tiers.py        # WATCH/REBALANCE/OPPORTUNISTIC sets
│       └── iterators/      # 42 iterator files
├── common/                 # Shared utilities (38 files)
│   ├── config_schema.py    # Pydantic models for config validation
│   ├── thesis.py           # ThesisState dataclass
│   ├── memory.py           # SQLite FTS5 lessons + events
│   └── credentials.py      # Pluggable key backends
├── modules/                # Pure computation engines (64 files)
├── data/                   # All runtime data (96 MB)
│   ├── config/             # 25 config files (JSON + YAML)
│   ├── thesis/             # 6 thesis state files
│   ├── candles/            # SQLite candle cache
│   ├── memory/             # memory.db + hourly backups
│   └── ...                 # news, heatmap, strategy, research, etc.
├── docs/
│   ├── wiki/               # 60 developer reference pages
│   │   ├── learning-paths/ # YOU ARE HERE
│   │   ├── decisions/      # 14 ADRs (immutable)
│   │   ├── components/     # Per-component docs
│   │   └── operations/     # Runbooks, security, tiers
│   └── plans/              # Feature specs, assessments (write-once)
├── web/                    # Dashboard + API + docs site
│   ├── api/                # FastAPI backend (port 8420)
│   ├── dashboard/          # Next.js frontend (port 3000)
│   └── docs/               # Astro Starlight (port 4321)
└── tests/                  # 196 test files, 46K lines
```

---

## Step 3: After Changing Code

### Added a new iterator?
1. Add to `cli/daemon/tiers.py` in the appropriate tier(s)
2. Register in `cli/commands/daemon.py` (lines ~137-262)
3. Add config file to `data/config/` if it has settings
4. Add Pydantic schema to `common/config_schema.py`
5. Update `docs/wiki/learning-paths/oil-botpattern.md` if oil-related
6. Write tests in `tests/test_<name>_iterator.py`

### Added a new Telegram command?
See `docs/wiki/learning-paths/adding-a-command.md` — 8-step checklist.

### Changed a config file schema?
1. Update the Pydantic model in `common/config_schema.py`
2. Run `pytest tests/test_config_schema.py` to verify
3. The iterator will warn on unknown keys at load time

### Changed the tier system?
1. `cli/daemon/tiers.py` is the ONLY source of truth
2. Do NOT update iterator lists anywhere else — docs/wiki/site should reference tiers.py

### Changed the ThesisState model?
1. `common/thesis.py` is the source of truth
2. Check `cli/daemon/iterators/thesis_engine.py` for compatibility
3. Check `cli/daemon/iterators/execution_engine.py` for sizing impact
4. Thesis JSON files in `data/thesis/` may need migration

---

## Step 4: Testing

```bash
# Full suite (from agent-cli/)
.venv/bin/python -m pytest tests/ -x -q

# Specific component
.venv/bin/python -m pytest tests/test_oil_botpattern*.py -x -q

# Config validation
.venv/bin/python -m pytest tests/test_config_schema.py -x -q

# Quick smoke test (just imports)
.venv/bin/python -c "from cli.daemon.tiers import TIER_ITERATORS; print(f'{len(TIER_ITERATORS[\"watch\"])} WATCH iterators')"
```

**Rule**: Never modify test expectations to make tests pass — fix the source code.

---

## Step 5: Periodic Maintenance Tasks

### Weekly
- [ ] Run full test suite — catch silent regressions
- [ ] Check `data/memory/backups/` size — should be <50 MB (enforce retention)
- [ ] Glance at `data/daemon/daemon.log` size — if >10 MB, investigate

### Monthly
- [ ] Rebuild docs site: `cd web/docs && bun run serve`
- [ ] Check `data/research/evaluations/` file count — archive if >500 files
- [ ] Check `data/heatmap/zones.jsonl` line count — rotate if >10K lines
- [ ] Review memory files — any stale? Add `Superseded YYYY-MM-DD` header

### On Milestone
- [ ] Archive MASTER_PLAN.md with date suffix
- [ ] Write new MASTER_PLAN.md
- [ ] Update build-log with completion entry
- [ ] Run `/alignment` to sync docs with reality

---

## Step 6: When Things Break

### Daemon won't start?
```bash
# Check for stale PID
cat data/daemon/daemon.pid
kill -0 $(cat data/daemon/daemon.pid) 2>/dev/null && echo "Running" || echo "Stale PID"
rm data/daemon/daemon.pid  # If stale

# Check config
.venv/bin/python -c "from common.config_schema import load_config; print(load_config('oil_botpattern'))"
```

### Telegram bot not responding?
```bash
cat data/daemon/telegram_bot.pid
# Check if process exists, kill stale PID if needed
# Restart: python -m cli.telegram_bot
```

### AI agent giving wrong answers?
1. Check `data/daemon/chat_history.jsonl` — what context did it see?
2. Check `agent/AGENT.md` — system prompt up to date?
3. Check `data/agent_memory/MEMORY.md` — agent memory correct?
4. Check thesis files — stale conviction?

### Docs site won't build?
```bash
cd web/docs
rm -rf dist .astro   # Clear caches
bun run serve         # Rebuild
# If that fails, content is still readable as plain .md files in src/content/docs/
```

---

## Step 7: Key Numbers to Know

| Metric | Value | Where |
|--------|-------|-------|
| Python files | ~6,600 | Mostly tests (196 files) |
| Production LOC | ~68,000 | cli/ + common/ + modules/ |
| Test LOC | ~46,000 | tests/ |
| Daemon iterators | 42 | `cli/daemon/iterators/` |
| Telegram commands | 65+ | `HANDLERS` dict in telegram_bot.py |
| Agent tools | 31 | `cli/agent_tools.py` |
| Config parameters | ~396 | 25 files in `data/config/` |
| Kill switches | 12 | Individual config files |
| Data on disk | ~96 MB | `data/` |

---

## Step 8: Where to Find Things

| "I need to understand..." | Start here |
|---------------------------|-----------|
| How thesis drives orders | `learning-paths/thesis-to-order.md` |
| How to add a command | `learning-paths/adding-a-command.md` |
| The oil strategy system | `learning-paths/oil-botpattern.md` |
| Config system | `learning-paths/understanding-config.md` |
| Alert flow | `learning-paths/understanding-alerts.md` |
| AI agent internals | `learning-paths/understanding-ai-agent.md` |
| Data storage | `learning-paths/understanding-data-flow.md` |
| Web dashboard | `learning-paths/understanding-web-dashboard.md` |
| Repo maintenance | `learning-paths/repo-maintenance.md` (this file) |

---

## The Golden Rule

From `docs/wiki/MAINTAINING.md`: **No hardcoded counts.** Don't write "there
are 42 iterators" in documentation that isn't this learning path. The code
changes. Reference the source: "see `cli/daemon/tiers.py` for the current
iterator list."

The exception is this maintenance guide and the architecture assessment — they
capture a snapshot in time and are dated accordingly.

---

*Written 2026-04-11. Numbers reflect codebase state at that date.*
