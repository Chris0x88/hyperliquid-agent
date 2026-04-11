---
title: Lesson & Review System
description: Automated trade review pipeline — from closed positions to searchable lessons and brutal self-assessment.
---

The Lesson system closes the feedback loop between execution and learning. When a position closes, the system assembles context, authors a lesson candidate, and queues it for review. Approved lessons are stored in a searchable SQLite database with full-text search. Separate tools grade entries in real time and provide on-demand deep-dive reviews.

## Lesson Cycle

```
Closed position (journal.jsonl)
        ↓
  lesson_author iterator
        ↓
  Candidate JSON (data/daemon/lesson_candidates/)
        ↓
  /lessonauthorai (AI authors the lesson)
        ↓
  memory.db (SQLite + FTS5)
        ↓
  /lessons, /lessonsearch
```

### Step 1: Position Closes

When a position closes, the trade details are written to `journal.jsonl` by the daemon.

### Step 2: Lesson Author Iterator

The `lesson_author` iterator watches `journal.jsonl` for new closed trades. For each one, it assembles the full context package:

- Thesis snapshot at entry time (conviction, targets, invalidation)
- Active catalysts during the trade
- Relevant learnings from previous lessons
- Entry and exit prices, PnL, duration

This context is written as a candidate JSON file to `data/daemon/lesson_candidates/`.

A garbage filter (Bug A fix) prevents low-quality or duplicate candidates from entering the pipeline.

| | |
|---|---|
| **Iterator** | `lesson_author` |
| **Config** | `data/config/lesson_author.json` |

### Step 3: AI Authoring

The `/lessonauthorai` command triggers AI to read each candidate's context package and write a structured lesson: what happened, why, what to do differently, and what to repeat.

### Step 4: Storage & Search

Approved lessons are stored in `memory.db` using SQLite with FTS5 (full-text search). Every lesson is indexed and searchable by keyword, market, date, or outcome.

## Commands

| Command | Description |
|---------|-------------|
| `/lessons [N]` | List recent lessons (default: 10) |
| `/lesson <id>` | View a specific lesson by ID |
| `/lesson approve <id>` | Approve a candidate lesson into the database |
| `/lesson reject <id>` | Reject a candidate (discarded, not stored) |
| `/lesson unreview <id>` | Reset a lesson back to candidate status |
| `/lessonsearch <query>` | Full-text search across all approved lessons |
| `/lessonauthorai [N\|all]` | AI-author pending candidates (AI suffix) |

## Entry Critic

A deterministic grading system that runs on every new position entry. No AI involved — pure rule-based assessment.

### Grading Axes

| Axis | What it checks |
|------|---------------|
| **Sizing** | Is the position sized correctly for the conviction level? |
| **Direction** | Does the direction align with the active thesis? |
| **Catalyst timing** | Is the entry positioned ahead of a known catalyst, or chasing? |
| **Liquidity** | Are we entering into favorable liquidity conditions? |
| **Funding** | Is the funding rate working for or against us? |

### Grade Scale

| Grade | Meaning |
|-------|---------|
| GREAT | Textbook entry — thesis-aligned, well-timed, properly sized |
| GOOD | Solid entry with minor imperfections |
| OK | Acceptable but not ideal |
| RISKY | One or more axes flagged — entry has notable weaknesses |
| BAD | Multiple axes failed — entry violates core principles |

| | |
|---|---|
| **Command** | `/critique` |
| **Config** | `data/config/entry_critic.json` |

The Entry Critic provides immediate feedback at entry time. It does not block execution — it grades and records, letting the operator (or AI agent) decide whether to act on the assessment.

## Brutal Review

An on-demand AI deep-dive into recent trading performance. Unlike the Entry Critic (which is deterministic and per-entry), the Brutal Review looks across multiple trades and asks hard questions:

- Are we repeating the same mistakes?
- Is the thesis still valid or are we holding on to a broken narrative?
- Where is the edge, and is it real?
- What would a hostile reviewer say about this track record?

| | |
|---|---|
| **Command** | `/brutalreviewai` (AI suffix) |
| **Output** | `data/reviews/brutal_review_YYYY-MM-DD.md` |

The output is a markdown file saved to disk. It is blunt by design — the point is to surface uncomfortable truths, not to validate existing positions.
