# Vault-as-Auditor — Proposal

> **Phase E output** of `SYSTEM_REVIEW_HARDENING_PLAN.md` §8.
> **Status:** proposal. No code shipped in Phase E.
> **Companion pages shipped:**
> `docs/vault/runbooks/Drift-Detection.md`,
> `docs/vault/architecture/Cohesion-Map.md`,
> `docs/vault/architecture/Time-Loop-Interweaving.md`.

## Vision

The obsidian vault becomes the system's **first-class audit
surface**. The auto-generator already reads the authoritative sources
(iterators, commands, tools, tiers, configs, plans, ADRs). Every
regeneration produces a file with frontmatter + body. The **diff
between two regenerations IS the structural change surface**. No
other tool is needed — the vault already knows what changed.

The user's framing, verbatim:
> "I really do believe the obsidian vault gives eyes into how well
> linked and cohesive our app actually is. If it's a total mess, it
> will show in the vault where the key points we have to work on
> are. Especially if we consider the element of time loops in that
> process too so we track processes that interweave and not just
> waterfall code structure alone."

Phase E operationalises this in two layers:

1. **Drift-detection layer** (already working — just needs a runbook):
   regenerate + `git diff docs/vault/` = drift report.
2. **Health-signal layer** (proposed): extend `build_vault.py` with
   new query paths that emit `docs/vault/health/*.md` pages for
   things the current generator doesn't show. These are the "where
   the key points we have to work on are" signals.

## Layer 1 — Drift-detection (shipped in Phase E)

- **`docs/vault/runbooks/Drift-Detection.md`** — the protocol. When
  to run the regen, how to read the diff, how to tell noise from
  signal.
- **`docs/vault/architecture/Cohesion-Map.md`** — hand-written
  parallel-writer matrix. Captures cross-process contracts
  (`daemon` ↔ `telegram` ↔ `heartbeat`) that the auto-generator
  cannot see because they span files the generator parses
  independently.
- **`docs/vault/architecture/Time-Loop-Interweaving.md`** — hand-written
  catalog of cross-iterator signal chains with worst-case end-to-end
  latencies (C1: catalyst→strategy 12 min; C2: AI thesis→daemon
  ≤60 s with race window; etc.). Captures the time dimension that
  iterator-by-iterator pages can't.

These hand-written pages live under `architecture/` and `runbooks/`,
both of which `scripts/build_vault.py` explicitly preserves ("Does
NOT touch hand-written pages — Home.md, architecture/\*.md,
runbooks/\*.md"). Regeneration is safe.

## Layer 2 — Health-signal pages (proposed)

Each page is one new function added to `scripts/build_vault.py`,
~50–150 LOC. They all share the frontmatter + body scheme the
existing auto-pages use. None of them ship in Phase E; this section
is the spec the next implementation wedge works from.

### 2.1 `docs/vault/health/untested.md`

**What it emits:** a table of every iterator in
`cli/daemon/iterators/*.py` that does NOT have a matching
`tests/test_<iterator>*.py` file. Frontmatter tags with
`health-signal` + `missing-test` so Obsidian graph view clusters
them.

**Query:**
```python
for py in ITERATORS_SRC.glob("*.py"):
    if py.name.startswith("_"): continue
    stem = py.stem
    candidates = [
        TESTS_DIR / f"test_{stem}.py",
        TESTS_DIR / f"test_{stem}_iterator.py",
        TESTS_DIR / f"test_{stem}_module.py",
    ]
    if not any(c.exists() for c in candidates):
        emit_row(stem, "missing test file")
```

**Why it matters:** Phase D P1-12 and P1-13 both flagged missing
tests. This page auto-flags them on every regen.

### 2.2 `docs/vault/health/kill_switches.md`

**What it emits:** one row per file under `data/config/*.json` with
the parsed `enabled: true|false` state. Highlight rows where
`enabled=true` for a subsystem the user expected off.

**Query:**
```python
for cfg in CONFIG_SRC.glob("*.json"):
    data = json.loads(cfg.read_text())
    if isinstance(data, dict):
        enabled = data.get("enabled")
        tick = data.get("tick_interval_s") or data.get("interval_hours")
        emit_row(cfg.stem, enabled, tick)
```

**Why it matters:** the user's ask is "key points we have to work
on" — a kill-switch dashboard is the most literal answer. Replaces
the hand-maintained "Known Iterators" section of
`cli/daemon/CLAUDE.md` (that section stays as routing, this page
becomes the live dashboard).

### 2.3 `docs/vault/health/stale_data.md`

**What it emits:** for each write-target file referenced in an
iterator, show the `mtime` in human-friendly form (`3m ago`, `2d
stale`). If anything is older than its expected cadence (pulled from
the same `data/config/*.json`), emit a `⚠️` marker.

**Query:**
```python
write_targets = {
    "news_ingest": "data/news/catalysts.jsonl",
    "supply_ledger": "data/supply/state.json",
    "heatmap": "data/heatmap/zones.jsonl",
    "bot_classifier": "data/research/bot_patterns.jsonl",
    ...
}
for name, target in write_targets.items():
    mtime = path.stat().st_mtime
    expected_cadence = load_cadence_from_config(name)
    age = time.time() - mtime
    emit_row(name, target, human_age(age), "STALE" if age > expected_cadence * 2 else "fresh")
```

**Why it matters:** Phase B surfaced `cascades.jsonl` as missing,
and `rebalancer.last_tick` as 4 days stale — both discovered by hand
during classification. This page catches them on every regen.

### 2.4 `docs/vault/health/orphans.md`

**What it emits:** iterators registered in `tiers.py` that are NOT
wired via `clock.register()` in `cli/commands/daemon.py` (or vice
versa). Plus: Telegram commands in `HANDLERS` that have no
`_set_telegram_commands` entry (or vice versa — incomplete
5-surface checklist).

**Query:** two-pass:
1. Parse `tiers.py` for iterator names in each tier list.
2. Parse `cli/commands/daemon.py` for `clock.register(...)` calls.
3. Emit any name in (1) but not (2) and vice versa.

Similarly for Telegram:
1. Parse `HANDLERS` dict keys in `cli/telegram_bot.py`.
2. Parse the command list in `_set_telegram_commands()`.
3. Parse `cmd_help()` for one-line entries.
4. Emit any command present in one surface and missing from others.

**Why it matters:** the `CLAUDE.md` Telegram checklist is
hand-enforced today. Guardian's completeness checker caught these
until it was disabled. Phase E proposes replacing Guardian's job
with a vault health page that runs whenever the vault is regenerated
— no hook loop, no sub-agent dispatch, just a static diff.

### 2.5 `docs/vault/health/plan_ships.md`

**What it emits:** for each "shipped" claim in
`docs/plans/MASTER_PLAN.md` (grep for `✅` or `shipped`), verify the
referenced file path exists and was touched recently. Emit a table
of claims + verification status.

**Query:**
```python
master_plan = (PLANS_SRC / "MASTER_PLAN.md").read_text()
for claim in re.findall(r"[✅].*?shipped.*?`(.*?)`", master_plan):
    path = PROJECT_ROOT / claim
    if not path.exists():
        emit_row(claim, "MISSING FILE", "critical")
    else:
        age = time.time() - path.stat().st_mtime
        emit_row(claim, f"exists, {human_age(age)} old", "ok")
```

**Why it matters:** catches stale "shipped" claims in the plan
without re-enabling Guardian's stale-claim drift detector. This is a
Guardian feature migrated to a vault-regeneration-time check.

### 2.6 `docs/vault/health/parallel_writers.md` (extended)

**What it emits:** cross-reference of files written by the daemon
(`cli/daemon/iterators/*.py`) and files written by the telegram
process (`cli/telegram_commands/*.py` + `cli/agent_tools.py`). Flag
any file written by both.

**Query:** AST-parse both source trees for `open(..., "w")`,
`atomic_write`, `.write_text`, json.dump patterns; collect write
targets; intersect the daemon and telegram sets.

**Why it matters:** this is the auto-generated version of the
hand-written `docs/vault/architecture/Cohesion-Map.md` parallel-writer
matrix. The hand-written page stays as the narrative; this page
surfaces NEW races the moment someone adds a new writer.

### 2.7 `docs/vault/health/cadence_interweaving.md` (extended — time loops)

**What it emits:** for each iterator with a `tick_interval_s` or
equivalent cadence, compute the worst-case end-to-end latency from
its upstream dependencies (read from `Time-Loop-Interweaving.md`
chain definitions) to its downstream consumers. Flag any chain
whose worst-case exceeds a configured "acceptable" bound.

**Query:** this is the hardest of the seven because dependency
edges aren't in the AST. Two options:

- **Option A (cheap):** maintain a `docs/vault/_chains.yaml` file
  that lists each chain with its edges. The generator reads it,
  computes latencies from the cadences in `data/config/*.json`, and
  emits a rendered page.
- **Option B (expensive):** infer edges from the source by grepping
  each iterator for `read_json(...)` / `open(...)` / `read_text(...)`
  calls and matching read paths to write paths of other iterators.
  More automation, more fragile.

**Why it matters:** this is the time-loop dimension the user
explicitly asked for. Today `Time-Loop-Interweaving.md` captures it
by hand; Option A makes the computation automatic while keeping the
chain-definition YAML hand-maintained (single source of truth the
user can edit without writing code).

## Implementation order

If this proposal is approved and shipped later:

1. **Wedge 1 — kill_switches.md + untested.md** (~2 h).
   These two are pure scan-and-emit with no AST work. Highest value
   per hour: gives Chris a dashboard of enablement + test coverage
   in one regen.
2. **Wedge 2 — stale_data.md** (~2 h).
   Needs the write-target → iterator mapping. Catches Phase B's
   cascades-missing and rebalancer-stale findings automatically.
3. **Wedge 3 — orphans.md** (~3 h).
   AST parsing of `tiers.py` + `cli/commands/daemon.py` + Telegram
   5-surface checklist. Replaces the hot-path of Guardian's
   completeness checker in one static-diff regen.
4. **Wedge 4 — plan_ships.md** (~1 h).
   Grep + path verification. Tiny. Migrates Guardian's stale-claim
   detector.
5. **Wedge 5 — parallel_writers.md** (~4 h).
   AST pattern matching across two source trees. Most complex.
   Replaces the need to hand-maintain
   `architecture/Cohesion-Map.md`'s parallel-writer matrix.
6. **Wedge 6 — cadence_interweaving.md (Option A)** (~2 h).
   YAML reader + cadence computer + page emitter. Closes the
   time-loop dimension.

Wedges 1–4 are each landable as their own commit with no
dependencies. Wedges 5 + 6 are the time-loop and cohesion layers
and deliver the most value per dollar but also cost the most.

## Non-goals

- **NOT** a reimplementation of Guardian as a hook. All of this runs
  on-demand when the user runs `scripts/build_vault.py`.
- **NOT** a replacement for unit tests. The health pages surface
  issues; tests prove fixes.
- **NOT** a real-time dashboard. The vault regenerates on demand.
  Stale vault = stale dashboard, which is fine because the protocol
  says regen at session boundaries.
- **NOT** a tool for non-Chris users. This is a personal audit
  surface for one operator.

## Drift-detection protocol (from the runbook)

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
.venv/bin/python scripts/build_vault.py
git diff --stat docs/vault/
git diff docs/vault/ | less
```

See `docs/vault/runbooks/Drift-Detection.md` for how to read the
diff.

## Estimated total effort

All 7 proposed health pages: **~14 hours** spread across 6 wedges.
Can be done sequentially or in parallel with Phase D fixes.

## Dependencies on Phase D

None strictly. But the health pages would be most valuable AFTER
Phase D fixes land, because they'd catch regressions in the fixed
areas automatically. Recommended sequence:

1. Land Phase D P0s (5 items).
2. Ship Wedges 1 + 2 (untested + stale_data) — catches regressions
   in the P0 fixes immediately.
3. Land Phase D P1s.
4. Ship Wedges 3–6 at leisure.

## Open questions for the user

- Is **Option A** (hand-maintained chain YAML) the right choice for
  cadence_interweaving.md, or should we go direct to **Option B**
  (AST-inferred edges)? Option A ships faster, Option B needs less
  maintenance but is fragile.
- Should the health pages be committed to git, or gitignored? Same
  decision as the rest of the vault — currently committed, fine to
  keep that pattern.
- Should any health page have a **`⚠️` → Telegram alert** bridge,
  or are they vault-only? Vault-only is the Phase E default; a
  bridge would mean re-introducing a daemon-side observer, which
  is outside Phase E's scope.

## Related

- `SYSTEM_REVIEW_HARDENING_PLAN.md` — parent plan.
- `docs/vault/runbooks/Drift-Detection.md` — the runbook for the
  regen protocol.
- `docs/vault/architecture/Cohesion-Map.md` — parallel-writer matrix.
- `docs/vault/architecture/Time-Loop-Interweaving.md` — chain
  catalog.
- `COHESION_HARDENING_LIST.md` — the Phase D backlog that several
  health pages would catch automatically.
- `BATTLE_TEST_LEDGER.md` — Phase B classification; `stale_data.md`
  would have surfaced several items here automatically.
- `TIMER_LOOP_AUDIT.md` — Phase C audit; `cadence_interweaving.md`
  would automate its §5 findings.
