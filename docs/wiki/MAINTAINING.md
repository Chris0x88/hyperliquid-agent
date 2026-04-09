# Maintaining the Documentation System

This is the single most important document for keeping docs honest. Read this before updating anything.

## The Two Drift Failure Modes

Doc rot kills projects. There are exactly two ways docs go wrong:

1. **Stale claims** — the doc says X is true but reality says X is false.
   Example: MASTER_PLAN.md says "lesson_author iterator not yet wired"
   when the file exists, is registered in tiers.py, and has shipped commits.
   Caught by: Guardian's `detect_stale_plan_claims()` (added 2026-04-09)
   and the periodic Brutal Review Loop.
2. **Hardcoded counts** — the doc says "32 commands, 19 iterators" and is
   wrong the moment someone adds a function. See "Golden Rule" below.

When you find either, **fix the source first** (the running code is the
truth), then update the docs to match.

## The Five Doc Types

| Type | Location | Purpose | Update trigger | Who updates |
|------|----------|---------|---------------|-------------|
| **Wiki** | `docs/wiki/` | System knowledge, how things work | When architecture changes | Claude Code |
| **Architecture** | `docs/wiki/architecture/` | Versioned architecture specs + diagrams | When a major version ships | Claude Code |
| **CLAUDE.md** | Per-package | Routing — point to the right files | When files are added/removed/renamed | Claude Code |
| **Memory** | `~/.claude/.../memory/` | User preferences, feedback, working style | When Chris gives new guidance | Claude Code |
| **ADRs** | `docs/wiki/decisions/` | Why decisions were made | When a significant decision is made | Claude Code |

### Rules

1. **Wiki pages describe HOW things work.** They contain narrative, diagrams, and explanations.
2. **Architecture versions are historical records.** `current.md` is the live system. `vN-*.md` files are snapshots — never edit old versions, create a new one.
3. **CLAUDE.md files are routing only.** File tables + wiki links + gotchas. No narrative, no architecture.
4. **Memory files are preferences only.** User feedback, trading rules, AI behavior guidance. No system state.
5. **ADRs are append-only.** Never edit an existing ADR. Write a new one if the decision changes.
6. **Build log is append-only.** Add new entries at the top. Never rewrite history.

## The Golden Rule: No Hard-Coded Counts

**NEVER** write numbers that will go stale:
- "32 commands" — NO
- "19 iterators" — NO
- "1694 tests passing" — NO
- "41 files" — NO

**INSTEAD** reference where to find the truth:
- "see `def cmd_*` in `cli/telegram_bot.py`" — YES
- "see `iterators/` directory" — YES
- "run `pytest tests/ -x -q`" — YES
- "see `modules/` directory" — YES

Counts are the #1 cause of doc rot. If someone needs a count, they can grep for it.

## When to Update Each Type

### Architecture Versions (`docs/wiki/architecture/`)

The architecture folder tracks the system's evolution over time:

```
docs/wiki/architecture/
├── current.md              ← ALWAYS the live system (update this)
├── current.html            ← Rendered mermaid diagrams (open in browser)
├── v1-daemon-simplification.md   ← Historical: v1 daemon design
├── v2-memory-system.md           ← Historical: v2 memory design
├── v3-unified-tools.md           ← Historical: v3 tool system
└── v4-embedded-agent-runtime.md  ← Historical: v4 agent runtime
```

**When a major version ships:**
1. Snapshot `current.md` as `vN-descriptive-name.md` (never edit after)
2. Update `current.md` to reflect the new architecture
3. Update `current.html` if mermaid diagrams changed
4. Add a build-log entry

**Never edit old versions.** They're historical records. If something was wrong in v3, that's what v3 actually was. The fix goes in `current.md`.

### Wiki Pages (`docs/wiki/`)

**Update when:**
- A new component is added or an existing one fundamentally changes
- A new system is wired up (e.g., REFLECT moves from CLI-only to daemon)
- The architecture diagram no longer matches reality

**Don't update when:**
- A bug is fixed (the fix is in the code)
- A count changes (no counts in wiki)
- A minor feature is added to an existing component

**How:**
1. Read the current wiki page
2. Read the actual code it describes
3. Update the wiki to match reality
4. If the change is significant, add a build-log entry

### CLAUDE.md Files

**Update when:**
- Files are added, removed, or renamed in the package
- A new key file emerges that future sessions need to know about
- A gotcha is discovered that burned time

**Don't update when:**
- Line counts change (no line counts in CLAUDE.md)
- Internal implementation changes (that's in the wiki)

**How:**
1. Update the file table (add/remove rows)
2. Update gotchas if needed
3. Keep it under 30 lines

### Memory Files

**Update when:**
- Chris gives new feedback about how to work ("don't do X", "always do Y")
- Chris's preferences change
- A new trading rule is established

**Don't update when:**
- System architecture changes (that's wiki)
- A component is built or modified (that's wiki + build-log)

### ADRs (`docs/wiki/decisions/`)

**Create a new ADR when:**
- A significant architectural decision is made
- An existing approach is replaced with a new one
- A trade-off is chosen that future sessions should understand

**Format:**
```markdown
# ADR-NNN: Title

**Date:** YYYY-MM-DD
**Status:** Accepted

## Context
What problem or situation led to this decision?

## Decision
What was decided?

## Consequences
What changed? What are the trade-offs?
```

Number sequentially. Check the highest existing number in `docs/wiki/decisions/` first.

### MASTER_PLAN.md (`docs/plans/MASTER_PLAN.md`)

MASTER_PLAN.md is the **living plan**: it always reflects current reality
and forward direction. It is **not** a historical record — that's what the
build log and the archive directory are for.

**Update when:**
- Reality drifts from what the plan says (a "Not yet wired" item ships,
  a workstream is parked, a new active workstream begins)
- Open Questions / Known Gaps section needs additions or strikeouts
- Critical Rules need to be tightened (a new safety lesson learned)

**Versioning convention** (added 2026-04-09):

When MASTER_PLAN.md drifts meaningfully from reality — typically when a
phase finishes or a major workstream pivots — **archive the current
version + rewrite fresh**. Do not try to preserve historical narrative
inside the live file.

```
# 1. Snapshot the current MASTER_PLAN to the archive (append-only,
#    sortable filename, kebab-case slug describing the moment)
cp docs/plans/MASTER_PLAN.md \
   docs/plans/archive/MASTER_PLAN_YYYY-MM-DD_<slug>.md

# 2. Add an HTML comment header to the archived file with:
#    - Date archived
#    - Reason for archival (what drifted, what shipped)
#    - "DO NOT EDIT" instruction

# 3. Rewrite docs/plans/MASTER_PLAN.md fresh against current reality.
#    Forward-looking. Crisp. No embedded history.

# 4. Add a build-log entry explaining the archive + rewrite.
```

The archive captures **plan state at a moment**. The build log captures
**incremental change**. MASTER_PLAN.md captures **now**. All three together
let any future session reconstruct any past state of the project.

**Do NOT** edit archived plan snapshots. They are append-only by
convention. If a snapshot is wrong, the WHY of the wrongness is exactly
what makes it valuable for reflection.

**Do NOT** keep large historical sections inside MASTER_PLAN.md. If you
catch yourself writing "_this section was historically..._" you should
be archiving + rewriting instead.

### Build Log (`docs/wiki/build-log.md`)

**Add an entry when:**
- A phase is completed
- A major feature ships (new component, new system)
- A significant incident occurs (postmortem)

**Don't add when:**
- Bug fixes, minor features, refactors
- That's what git log is for

## The /alignment Skill

Run `/alignment` at the start and end of every session. It:
1. Checks what's actually running (processes, daemon state)
2. Compares reality against docs
3. Reports drift

**Morning:** Read the report, note drift, don't fix yet (today's work may change things)
**Evening:** Fix any drift found, update wiki pages, commit

## Scheduled Maintenance

A weekly scheduled task runs automatically to check for drift:
- Counts commands, tools, iterators from code
- Checks thesis freshness
- Flags wiki pages not updated in 30+ days
- Reports via the session

If it reports drift, update the relevant wiki page — not the CLAUDE.md, not the memory.

## Common Mistakes to Avoid

1. **Duplicating info across systems.** If it's in the wiki, don't also put it in CLAUDE.md or memory.
2. **Writing counts anywhere.** They're wrong the moment someone adds a function.
3. **Updating memory with architecture info.** Memory is for preferences, wiki is for architecture.
4. **Editing ADRs.** Write a new one instead.
5. **Putting narrative in CLAUDE.md.** That's what the wiki is for.
6. **Skipping the build log.** Major changes need a record. Git log exists but is noisy.
7. **Archiving when you should delete.** Old wiki pages get replaced, not archived. Old docs are deleted (preserved in git history).
