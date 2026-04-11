# Knowledge Hierarchy — Maintenance Guide

> **Written**: 2026-04-11
> **Purpose**: How to maintain the knowledge system if AI automation fails.
> **Audience**: Human operator (Chris) and any future AI session.

---

## Core Intent (Captured 2026-04-11)

This system was built by one person with AI assistance. The knowledge accumulated
across months of building — trading rules, architectural decisions, user preferences,
domain expertise, failed experiments, and hard-won lessons — is an ASSET, not overhead.

**We never delete knowledge.** We archive it with dates. Like common law: precedent
is preserved, newer decisions cite and sometimes override older ones, but the
reasoning trail is always traceable. A thought from January that was superseded in
March still explains WHY March happened.

**The hierarchy exists to prevent confusion, not to reduce volume.** Five knowledge
systems coexist because they serve different audiences at different speeds. The
hierarchy tells you which one to trust when they disagree.

---

## The Five Layers

```
Layer 1: CODE          → Always correct. When code and docs disagree, code wins.
Layer 2: WIKI          → Developer reference. Updated when code changes.
Layer 3: DOCS SITE     → User-facing. Allowed to lag. Rebuilt periodically.
Layer 4: MEMORY        → User preferences + archived decisions. Never deleted.
Layer 5: PLANS         → Write-once specs. Archived with dates when superseded.
```

### Layer 1: Code (Source of Truth)

| Concern | Canonical File |
|---------|---------------|
| Iterator lists per tier | `cli/daemon/tiers.py` |
| Telegram commands | `HANDLERS` dict in `cli/telegram_bot.py` |
| Config schemas | `common/config_schema.py` (Pydantic models) |
| Market definitions | `data/config/markets.yaml` via `common/markets.py` |
| ThesisState model | `common/thesis.py` |
| Authority model | `common/authority.py` |

**Maintenance rule**: When you change code, the code IS the update. No docs
update is required for Layer 1 — the code speaks for itself.

### Layer 2: Wiki (`docs/wiki/`)

60 markdown files organized by:
- `components/` — how each component works
- `operations/` — runbooks, security, tier management
- `decisions/` — ADRs (Architecture Decision Records) — IMMUTABLE
- `workflows/` — input routing, message tracing
- `trading/` — domain knowledge, oil expertise

**Maintenance rule**: When you add a major feature or change architecture,
update the relevant wiki page. ADRs are write-once — create a new ADR to
override an old one, never edit the old one.

**When AI automation fails**: Read `docs/wiki/MAINTAINING.md` for the golden
rule (no hardcoded counts). Walk through the wiki directory listing and check
each component file against the actual codebase.

### Layer 3: Docs Site (`web/docs/`)

22 Starlight pages with Mermaid diagrams. User-facing.

**Maintenance rule**: Rebuild periodically. Run `bun run serve` from
`web/docs/` to build and preview. The docs site is allowed to lag behind
the wiki by days or weeks — it's a snapshot, not a live mirror.

**When AI automation fails**: The docs site is static HTML. If it breaks:
1. `cd agent-cli/web/docs`
2. `rm -rf dist .astro`
3. `bun run serve`
4. If that fails, the content is still in `src/content/docs/*.md` — readable
   as plain markdown.

### Layer 4: Memory (`~/.claude/.../memory/`)

~45 files containing user preferences, feedback, project status, references.

**CRITICAL: Memory files are NEVER deleted.** They are the common law of this
project. When a memory becomes outdated:
1. Add a date header: `> Superseded 2026-04-11 — see [newer file]`
2. Move to an `archive/` subdirectory if the index gets cluttered
3. The original reasoning is preserved for future reference

**Date convention**: All memories should include their creation date in the
frontmatter or first line. Format: `YYYY-MM-DD` (e.g., `2026-04-11`).

**When AI automation fails**: Memory files are plain markdown in a known
directory. Read `MEMORY.md` for the index. Each file has YAML frontmatter
with `name`, `description`, and `type`.

### Layer 5: Plans (`docs/plans/`)

Feature specs, implementation plans, architecture assessments.

**Maintenance rule**: Plans are write-once. After execution:
1. The plan stays as-is (historical record)
2. Outcomes go into the wiki (living reference)
3. MASTER_PLAN.md is the exception — it gets archived and rewritten at
   major milestones (with dated archive copies)

**When AI automation fails**: Plans are markdown files. They don't drive
anything — they're documentation of intent. Safe to ignore if they go stale.

---

## The Common Law Principle

Every piece of knowledge in this system follows the common law pattern:

1. **Precedent is preserved.** A memory from 2026-01-31 about oil trading
   philosophy is still valid context even if the strategy evolved. The date
   tells you when it was written. The current code tells you what's active.

2. **Newer overrides older, with citation.** If a March decision overrides a
   January decision, the March document should reference the January one.
   This makes the reasoning chain traceable.

3. **Nothing is deleted.** Deletion destroys context. Archival preserves it.
   Use date-prefixed filenames or `archive/` subdirectories.

4. **Keywords enable lookup.** Memory files have `description` fields in
   frontmatter. Plans have titles. Wiki has directory structure. Together
   they form a keyword-searchable corpus.

### Date Sequencing Convention

For any knowledge artifact that changes over time:
```
YYYY-MM-DD — Brief description of the state at that date
```

Examples:
- `MASTER_PLAN_ARCHIVE_2026_04_09.md`
- `ARCHITECTURE_ASSESSMENT_2026_04_11.md`
- Memory frontmatter: `description: "Oil philosophy — long only, first principles (2026-02-15)"`

This makes chronological lookup trivial: sort by filename or date field.

---

## Feedback as User Data

The `/feedback` Telegram command captures user feedback and stores it in the
system. This is USER DATA — it belongs in the data layer, not the knowledge
layer. The feedback pipeline:

```
User types /feedback "don't mock the database"
  → Stored in data/daemon/feedback.jsonl (append-only)
  → May be promoted to memory/ by AI if it's a durable preference
  → Memory file includes date + context
```

**Feedback that becomes a memory**: The AI session reads feedback, identifies
durable preferences, and writes memory files. The original feedback is preserved
in the data layer. The memory is the distilled, actionable version.

**Feedback that stays as data**: One-off feedback, bug reports, and transient
notes stay in the data layer and are NOT promoted to memory.

---

## Emergency Maintenance Checklist

If everything breaks and you need to rebuild understanding from scratch:

1. **Read root `CLAUDE.md`** — 68 lines of core rules. This is the constitution.
2. **Read `docs/wiki/MAINTAINING.md`** — how the wiki system works.
3. **Read `MEMORY.md`** — index of all user preferences and feedback.
4. **Run tests**: `cd agent-cli && .venv/bin/python -m pytest tests/ -x -q`
5. **Check code health**: `git log --oneline -20` for recent changes.
6. **Start the docs site**: `cd web/docs && bun run serve` — browse at :4321.
7. **Check daemon state**: `cat data/memory/working_state.json`

The system is designed to be self-documenting. Code is truth. Wiki explains
code. Docs present wiki. Memory preserves preferences. Plans record intent.

---

## Automation Integration Points

When AI sessions manage this hierarchy automatically:

1. **On code change**: AI should check if wiki pages reference the changed
   component and flag them for update.
2. **On new feature**: AI should create a wiki component page and a docs site
   page (or flag that they're needed).
3. **On user feedback**: AI should check if it's a durable preference (→ memory)
   or transient note (→ data only).
4. **On milestone**: AI should archive MASTER_PLAN with date suffix and
   create a fresh version.

If automation fails at any of these points, the human can do them manually
using the checklists above. The system degrades gracefully — stale docs are
worse than no docs, but they're not dangerous. Only stale CLAUDE.md safety
rules are dangerous, and those are protected by redundancy.

---

*Written 2026-04-11. This document itself is part of Layer 5 (Plans) and
should be updated when the hierarchy evolves.*
