---
kind: iterator
last_regenerated: 2026-04-09 16:05
iterator_name: lesson_author
class_name: LessonAuthorIterator
source_file: cli/daemon/iterators/lesson_author.py
tiers:
  - watch
  - rebalance
  - opportunistic
kill_switch: data/config/lesson_author.json
daemon_registered: true
tags:
  - iterator
  - tier-watch
  - tier-rebalance
  - tier-opportunistic
---
# Iterator: lesson_author

**Class**: `LessonAuthorIterator` in [`cli/daemon/iterators/lesson_author.py`](../../cli/daemon/iterators/lesson_author.py)

**Registered in tiers**: `watch`, `rebalance`, `opportunistic`

**Kill switch config**: `data/config/lesson_author.json`

**Registered in `daemon_start()`**: ✅ yes

## Description

LessonAuthorIterator — watches journal.jsonl for closed positions and
writes verbatim lesson candidate files for later authoring.

This is wedge 5 of the trade lesson layer. The iterator is intentionally
"dumb" — it does no AI calls, no LLM, no model interaction whatsoever.
It only assembles the verbatim source context (closed JournalEntry +
optional thesis snapshot + optional learnings.md slice) and writes the
result to disk as a candidate JSON file.

The actual "agent authors the post-mortem and persists to the lessons
table" step is a future wedge — it can live in the dream cycle, in a
Telegram-side periodic task, or in a manual /lesson author <id> command.
Decoupling the watcher from the model call mirrors the existing
autoresearch.py pattern (the daemon never calls the model directly;
it writes structured outputs that the agent reads on its own loop).

Cursor tracking: a tiny state file at
``data/daemon/lesson_author_state.json`` stores the last byte offset
read from journal.jsonl plus a set of processed entry_ids. On every
tick the iterator seeks to the last offset, parses new lines, filters
to closed-position records, and writes one candidate file per close.
Dedup is done two ways:
  1. In-memory `_processed_ids` set to skip rows already seen this run.
  2. Filesystem check on the candidate filename (deterministic from
     entry_id) to skip rows seen in a previous daemon run.

Kill switch: ``data/config/lesson_author.json`` → ``{"enabled": false}``.

Refuse-to-write-garbage rule (Bug A pattern from 2026-04-08): if the
journal row is missing required fields (entry_id, instrument,
direction, exit_price, pnl, close_ts) or the values are obviously
broken (entry_price/exit_price = 0, |roe_pct| > 1000), the row is
logged and skipped — no candidate file is written.

## See also

- Tier registration: [[Tier-Ladder]]
- Kill switch: `data/config/lesson_author.json` → [[config-lesson_author]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here. The generator preserves this section on regeneration._
<!-- HUMAN:END -->
