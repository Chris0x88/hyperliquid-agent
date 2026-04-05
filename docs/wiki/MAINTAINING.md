# Maintaining the Documentation System

This is the single most important document for keeping docs honest. Read this before updating anything.

## The Four Doc Types

| Type | Location | Purpose | Update trigger | Who updates |
|------|----------|---------|---------------|-------------|
| **Wiki** | `docs/wiki/` | System knowledge, how things work | When architecture changes | Claude Code |
| **CLAUDE.md** | Per-package | Routing — point to the right files | When files are added/removed/renamed | Claude Code |
| **Memory** | `~/.claude/.../memory/` | User preferences, feedback, working style | When Chris gives new guidance | Claude Code |
| **ADRs** | `docs/wiki/decisions/` | Why decisions were made | When a significant decision is made | Claude Code |

### Rules

1. **Wiki pages describe HOW things work.** They contain narrative, diagrams, and explanations.
2. **CLAUDE.md files are routing only.** File tables + wiki links + gotchas. No narrative, no architecture.
3. **Memory files are preferences only.** User feedback, trading rules, AI behavior guidance. No system state.
4. **ADRs are append-only.** Never edit an existing ADR. Write a new one if the decision changes.
5. **Build log is append-only.** Add new entries at the top. Never rewrite history.

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
