# Knowledge Hierarchy Proposal — APPROVED 2026-04-11

> **Status**: APPROVED. Option B + learning paths. No deletions — archive with dates.
> See KNOWLEDGE_HIERARCHY_MAINTENANCE.md for the maintenance guide.

---

## The Problem

5 parallel knowledge systems, no hierarchy:

| System | Files | What It Knows |
|--------|-------|---------------|
| docs/wiki/ | 60 | Architecture, components, operations, ADRs |
| docs/plans/ | 31 | Feature specs, implementation plans, audits |
| CLAUDE.md (6 files) | ~300 lines | AI routing rules per directory |
| Memory (~45 files) | ~2,000 lines | User preferences, feedback, project status |
| Starlight docs site (22 pages) | ~4,000 lines | User-facing documentation |

**Measured duplication**:
- "BRENTOIL" in 25+ places across all 5 systems
- "session token" rule in 14 places
- Iterator lists in: tiers.py, wiki, docs site, daemon CLAUDE.md
- Tier capabilities in: wiki/operations/tiers.md, docs site operations/tiers, architecture/tiers

When something changes (e.g., a new iterator is added), nobody knows which of
the 5 systems to update, so either all get updated (expensive) or some go stale
(dangerous for AI context).

---

## Proposed Hierarchy: Code → Wiki → Docs Site

```
┌──────────────────────────────────────────────────┐
│ Layer 1: CODE (always correct)                    │
│ tiers.py, HANDLERS dict, config files, models     │
│ This is truth. When code and docs disagree,       │
│ code wins.                                        │
├──────────────────────────────────────────────────┤
│ Layer 2: WIKI (developer reference)               │
│ docs/wiki/ — architecture, components, operations │
│ Updated when code changes. ADRs are immutable.    │
│ CLAUDE.md files point here for deep dives.        │
├──────────────────────────────────────────────────┤
│ Layer 3: DOCS SITE (user-facing)                  │
│ web/docs/ Starlight pages                         │
│ Derived from wiki + code. Updated periodically.   │
│ Allowed to lag behind wiki by days/weeks.         │
├──────────────────────────────────────────────────┤
│ Layer 4: MEMORY (preferences, not facts)          │
│ ~/.claude/.../memory/ files                       │
│ User preferences, feedback, workflow notes.       │
│ NEVER stores facts that belong in code or wiki.   │
├──────────────────────────────────────────────────┤
│ Layer 5: PLANS (ephemeral, archival)              │
│ docs/plans/ — feature specs, assessments          │
│ Write-once. Never updated after execution.        │
│ Archived when superseded.                         │
└──────────────────────────────────────────────────┘
```

### Key Rules

1. **Code is truth.** Iterator lists come from tiers.py. Command lists come from
   HANDLERS. Config schemas come from Pydantic models. Never hardcode these
   anywhere else.

2. **Wiki explains code.** When an AI needs to understand "how does thesis drive
   sizing?", the wiki should have a learning-path document that says "read these
   5 files in this order." The wiki does NOT duplicate the code — it LINKS to it.

3. **Docs site is for humans.** It can paraphrase, simplify, add diagrams. It's
   allowed to be slightly behind. Updated via `bun run serve` rebuild.

4. **Memory is preferences only.** "User prefers terse responses" belongs in
   memory. "BRENTOIL uses xyz clearinghouse" does NOT — that's a code fact.

5. **Plans are write-once.** After a plan is executed, it's archived. Never
   edited. The wiki captures the outcome.

---

## Specific Changes (If Approved)

### A. Dedup Iterator Lists

**Current**: Iterator lists are hardcoded in:
- cli/daemon/tiers.py (canonical)
- cli/daemon/CLAUDE.md (copy)
- docs/wiki/operations/tiers.md (copy)
- docs/wiki/components/daemon.md (copy)
- web/docs/architecture/tiers.md (copy)
- web/docs/components/daemon.md (copy)

**Proposed**: All non-code references say:
> "Iterator sets are defined in `cli/daemon/tiers.py`. Run
> `python -c "from cli.daemon.tiers import TIER_ITERATORS; print(TIER_ITERATORS['watch'])"`
> to see the current list."

No hardcoded lists in docs. Diagrams can show categories (Protection, Intelligence,
Execution) but not enumerate every iterator.

**Risk**: Medium. AI agents loading wiki context won't see the full list without
reading the code file. Mitigated by CLAUDE.md pointing to tiers.py.

### B. Dedup Market Rules

**Current**: "BRENTOIL is long-only" appears in:
- data/config/markets.yaml (canonical)
- Root CLAUDE.md (copy)
- memory/feedback_market_restrictions.md (copy)
- memory/feedback_oil_philosophy.md (copy)
- docs/wiki/trading/oil-knowledge.md (copy)
- web/docs/trading/markets.md (copy)

**Proposed**: markets.yaml is truth. Memory keeps the user preference context
("WHY long-only" — petroleum engineering background). Wiki and docs site reference
markets.yaml but don't duplicate the rule.

**Risk**: High. The CLAUDE.md rule is a safety guardrail. Removing it from
CLAUDE.md means the AI might miss it if it doesn't load markets.yaml. The
duplication in CLAUDE.md is INTENTIONAL safety redundancy.

**Recommendation**: Keep the CLAUDE.md rule. Remove from memory (it's a code
fact, not a preference). Accept duplication in CLAUDE.md as safety redundancy.

### C. Create Learning Paths

**New directory**: `docs/wiki/learning-paths/`

| File | Teaches | Reads |
|------|---------|-------|
| thesis-to-order.md | How a thesis drives position sizing | context.py → thesis_engine → execution_engine → clock._execute_orders |
| adding-a-command.md | How to add a new Telegram command | telegram_bot.py checklist + telegram_commands/ pattern |
| oil-botpattern.md | Sub-system 1-6 end-to-end | 10 iterator files + OIL_BOT_PATTERN_SYSTEM.md |
| understanding-config.md | Config system and where params live | config_schema.py + data/config/ |

**Risk**: Low. Pure addition, no deletion. Helps AI navigate.

### D. Archive Memory — Never Delete (APPROVED)

**Principle**: Common law system. Nothing is ever deleted. Old memories are
preserved with dates for traceability. Newer decisions cite and override older
ones, but the reasoning chain is always intact.

**Current**: 20+ feedback files, some overlap:
- feedback_market_restrictions.md — "Approved: BTC, BRENTOIL, CL, GOLD, SILVER"
- feedback_oil_philosophy.md — "long only on oil"
- feedback_entry_logic.md — "position ahead of events"

Some encode code facts, some encode user preferences, some encode domain
expertise. ALL are preserved — they form the decision trail.

**Approved approach**:
- **NEVER delete memory files.** Even if a memory is superseded, it stays.
- When a memory is outdated, add a date header: `> Superseded YYYY-MM-DD — see [newer file]`
- All memories MUST include creation date in frontmatter or first line
- Date format: `YYYY-MM-DD` (e.g., `2026-01-31` = 31 Jan 2026)
- If the index gets cluttered, move old memories to `archive/` subdirectory
- Keyword mapping via frontmatter `description` field enables search

**Why**: A thought from January that was superseded in March still explains
WHY March happened. Deleting it destroys the reasoning chain. This is how
common law works — precedent is preserved, newer rulings override, but the
trail is always there.

**Feedback as user data**: The `/feedback` Telegram command writes to the
data layer (`data/daemon/feedback.jsonl`). Durable preferences get promoted
to memory files by the AI. The original feedback is preserved in the data
layer regardless — it's user data, not just knowledge.

---

## What I Would NOT Change

1. **Root CLAUDE.md safety rules** — Keep all trading safety rules even if
   duplicated. Safety redundancy is a feature, not a bug.

2. **ADR documents** (docs/wiki/decisions/) — These are immutable historical
   records. Never edit or delete.

3. **Plan archives** — Write-once documents. The build-log is append-only.

4. **Per-directory CLAUDE.md files** — These are AI routing hints. They're
   cheap to maintain and critical for AI context loading.

---

## Decision — APPROVED 2026-04-11

**Option B + learning paths + common law archival.**

1. **Dedup docs layers** — wiki and docs site should reference code as truth,
   not duplicate iterator lists or config parameters.
2. **Keep safety redundancy** — CLAUDE.md and critical memory files keep
   duplicated safety rules (session tokens, SL/TP mandatory, etc.)
3. **Never delete memory** — archive with dates, common law principle.
4. **Add learning paths** — `docs/wiki/learning-paths/` for AI navigation.
5. **Feedback is user data** — `/feedback` writes to data layer, promoted
   to memory when durable.

See `KNOWLEDGE_HIERARCHY_MAINTENANCE.md` for the full maintenance guide.

---

*Approved 2026-04-11 by user. Maintenance guide written same date.*
