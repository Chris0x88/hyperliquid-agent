# Trade Lesson Corpus

**Runs in:** all tiers (writer iterator) + dream cycle (consumer)
**Iterator:** `cli/daemon/iterators/lesson_author.py`
**Consumer:** `cli/telegram_agent.py:_author_pending_lessons`
**Engine:** `modules/lesson_engine.py` (pure computation: dataclass, prompt, parser)
**Persistence:** `common/memory.py` (lessons table + lessons_fts FTS5 + helpers)
**Telegram surfaces:** `cli/telegram_bot.py:cmd_lessons`, `cmd_lesson`, `cmd_lessonsearch`, `cmd_lessonauthorai`
**Agent tools:** `cli/agent_tools.py:_tool_search_lessons`, `_tool_get_lesson`
**Prompt injection:** `cli/agent_runtime.py:build_lessons_section`
**Build-log:** see 2026-04-09 entries for the wedge-by-wedge ship history

## Purpose

The lesson corpus is the agent's own structured memory of trade outcomes. After
every closed position, a verbatim post-mortem is authored by the agent and
persisted with enough fidelity that the next analogous setup can be evaluated
against actual track record instead of the agent's short context window.

The design principles came from the failed MemPalace integration scoping in
the 2026-04-09 build-log: **store verbatim, don't let an LLM decide what's worth
keeping, make it findable by structure plus search**. Built on Python stdlib
(SQLite FTS5) instead of a third-party vector store — zero new dependencies,
zero MCP, zero external party code.

## End-to-end loop

```
 Trade closes
   ↓ JournalIterator writes journal.jsonl row (existing behaviour)
 LessonAuthorIterator (every tick)
   ↓ Validates row (refuses garbage per Bug A pattern)
   ↓ Assembles verbatim LessonAuthorRequest
       (journal entry + thesis snapshot from H6 backup
       + tail of learnings.md + news context from catalysts table)
   ↓ Writes candidate file: data/daemon/lesson_candidates/<entry_id>.json
 Dream cycle (every 24h + 3 sessions, OR /lessonauthorai on demand)
   ↓ _author_pending_lessons reads pending candidates
   ↓ For each: build_lesson_prompt → _call_anthropic(Haiku) → parse_lesson_response
   ↓ Idempotency check via journal_entry_id
   ↓ log_lesson → row in lessons table + auto-sync to lessons_fts
   ↓ Unlink candidate file on success
 Next decision-time prompt
   ↓ build_lessons_section → BM25 ranks corpus → top 5 hits
   ↓ build_system_prompt injects "## RECENT RELEVANT LESSONS"
 Agent references lessons by id when discussing trades
 Chris curates from Telegram (/lesson approve|reject)
   ↓ Approved lessons get [approved] flag in injection ranking
   ↓ Rejected lessons hidden from injection but searchable via include_rejected
```

## The schema

`common/memory.py:_init()` creates the `lessons` table on first connection:

- `id`, `created_at`, `trade_closed_at`
- `market`, `direction` (CHECK long/short/flat), `signal_source`
- `lesson_type` (sizing | entry_timing | exit_quality | thesis_invalidation | funding_carry | catalyst_timing | pattern_recognition)
- `outcome` (CHECK win/loss/breakeven/scratched), `pnl_usd`, `roe_pct`, `holding_ms`
- `conviction_at_open`, `journal_entry_id`, `thesis_snapshot_path`
- `summary` (1-3 sentences agent-authored, prompt-injected)
- `body_full` (verbatim assembled context + agent analysis — NEVER summarized)
- `tags` (JSON array, mutable for curation)
- `reviewed_by_chris` (-1 rejected / 0 unreviewed / 1 approved, mutable for curation)

Plus a `lessons_fts` virtual table indexing summary + body_full + tags via FTS5
with `porter unicode61` tokenizer for BM25-ranked search. Three triggers:

- `lessons_ai` — INSERT FTS sync
- `lessons_append_only` — BEFORE UPDATE blocks edits to 14 frozen content columns
  (everything except `tags` and `reviewed_by_chris`)
- `lessons_tags_au` — UPDATE OF tags re-syncs FTS5 so curation edits stay searchable

## Idempotency

Three layers:

1. **Iterator** dedupes via `_processed_ids` set + filesystem check on the
   deterministic candidate filename (`<entry_id>.json` with `:` and `/`
   replaced).
2. **Consumer** queries `journal_entry_id` against existing rows before insert
   and silently skips + unlinks the candidate if a duplicate is found.
3. **Append-only trigger** prevents the unlikely case where two consumers race
   on the same candidate from corrupting an existing row's content columns.

## Kill switches

- **Iterator**: `data/config/lesson_author.json` → `{"enabled": false}`. Defaults
  to enabled when the file is absent. Reloaded every tick so the kill switch
  takes effect on the next tick after Chris flips it.
- **Prompt injection**: `cli.agent_runtime._LESSON_INJECTION_ENABLED = False`.
  Module-level constant; flip in code or monkeypatch in tests. Disabling makes
  `build_lessons_section()` return `""` so the section is naturally skipped.
- **Consumer**: no explicit kill switch — failures are swallowed and logged at
  debug. Set the iterator's kill switch off if you want to stop new candidates
  from being created in the first place. Existing candidate files can be
  deleted by hand if you want to discard a queue.

## Refusal patterns (Bug A from 2026-04-08)

The 2026-04-08 build-log entry documents a production incident where the
journal iterator wrote `exit_price=$0` rows producing fake +/-100% PnL on
real positions. The lesson layer applies the same "refuse to write garbage
records" rule at three points:

1. **Iterator**: `_is_valid_close()` rejects rows with `entry_price <= 0`,
   `exit_price <= 0`, `|roe_pct| > 1000`, or `holding_ms < 0`. Garbage rows
   are marked processed (so we don't re-evaluate) but no candidate file is
   written.
2. **Consumer parser**: `LessonEngine.parse_lesson_response()` raises
   `ValueError` on missing or invalid sentinels. The consumer catches the
   error, logs it, and **leaves the candidate in place** for the next run —
   never inserts a partial row.
3. **Consumer model call**: empty `content`, model exceptions, JSON decode
   errors all leave the candidate in place. The candidate file is only
   unlinked on a successful insert.

## Telegram surfaces

Five commands, all with the five-surface registration checklist (HANDLERS dict
with slash + bare forms, `_set_telegram_commands` menu, `cmd_help`, `cmd_guide`,
plus tests):

- `/lessons [N]` — list recent lessons (default 10, max 25). Approved get a
  ✅ flag, rejected are excluded by default.
- `/lesson <id>` — full verbatim body (truncated at 3000 chars to fit Telegram's
  4096 cap).
- `/lesson approve|reject|unreview <id>` — curation. Approved lessons get a
  ranking boost in prompt injection; rejected stay searchable as anti-patterns.
- `/lessonsearch <query>` — BM25 search. FTS5 operators in user input are
  neutralized by `_fts5_escape_query`.
- `/lessonauthorai [N|all]` — manually trigger the consumer. AI-dependent so
  the `ai` suffix is required per CLAUDE.md slash-command rule. Defaults to
  3, capped at 25 to keep the bot responsive. Also runs automatically every
  dream cycle.

## Why Haiku for the model call

The dream cycle and the lesson author both use `_call_anthropic` with
`model_override="claude-haiku-4-5"`. Reasons:

- **Speed**: Haiku is fast enough that a synchronous call from the bot doesn't
  block the next user message. Sonnet/Opus via the CLI binary path takes
  60-90s+ which would queue every other interaction.
- **Cost**: Lessons are batch-friendly — 3 candidates per dream cycle is the
  default. Haiku is cheap enough that the marginal cost is negligible.
- **Quality threshold**: Lesson authoring is a structured task with a strict
  prompt format (sentinel-wrapped output). The strictness of the parser means
  Haiku's output is enforced to the same shape as Sonnet/Opus would produce.
  Future enhancement: use the active model from the model selector for
  high-stakes lessons (e.g. a trade with PnL > $X), Haiku for the rest.

## Files in this component

| Layer | File |
|---|---|
| Pure engine (dataclass, prompt, parser) | `modules/lesson_engine.py` |
| SQLite + FTS5 + helpers | `common/memory.py` (lessons table + log_lesson/get_lesson/search_lessons/set_lesson_review) |
| Daemon writer iterator | `cli/daemon/iterators/lesson_author.py` |
| Tier registration | `cli/daemon/tiers.py` (lesson_author in all three tiers) |
| Iterator wiring | `cli/commands/daemon.py` |
| Consumer (model call + insert) | `cli/telegram_agent.py:_author_pending_lessons` |
| Dream cycle hook | `cli/telegram_agent.py:handle_ai_message` (inside the dream try block) |
| Prompt injection helper | `cli/agent_runtime.py:build_lessons_section` |
| System prompt parameter | `cli/agent_runtime.py:build_system_prompt(lessons_section=...)` |
| Agent tools | `cli/agent_tools.py:_tool_search_lessons`, `_tool_get_lesson` |
| Telegram commands | `cli/telegram_bot.py:cmd_lessons`, `cmd_lesson`, `cmd_lessonsearch`, `cmd_lessonauthorai` |
| Agent guidance | `agent/AGENT.md` (the "Lessons" tool section) |
| Tool reference | `agent/reference/tools.md` (search_lessons + get_lesson entries) |

## Tests

Search `tests/` for:

- `test_lesson_engine.py` — pure engine
- `test_lesson_memory.py` — schema + FTS5 + helpers + append-only trigger + `_DB_PATH` runtime lookup regression
- `test_agent_tools_lessons.py` — agent tool surfaces
- `test_agent_runtime.py:TestBuildLessonsSection` — prompt injection
- `test_telegram_lesson_commands.py` — Telegram commands + 5-surface checklist
- `test_lesson_author_iterator.py` — daemon iterator (cursor, dedup, garbage filter, candidate shape)
- `test_lesson_author_consumer.py` — consumer (model call mocked, idempotency, dream-cycle integration)

## Future enhancements (not blocking)

- **News context enrichment** (wedge 6 polish): the iterator currently writes
  `news_context_at_open: ""` as a placeholder. Enriching it from the
  catalysts table (sub-system 1) at the time the trade was opened would give
  the agent the actual catalyst landscape to reason about in the post-mortem.
- **Per-trade model selection**: high-PnL trades author with Sonnet/Opus,
  routine trades stay on Haiku.
- **Lesson rollups**: a periodic summarizer that consolidates N lessons into a
  parent "pattern" lesson when the agent notices a repeated theme. Would need
  a `parent_lesson_id` column added (still append-only on content).
- **Embedding backup**: when the corpus crosses ~1000 entries and BM25 starts
  feeling thin, layer a local sentence-transformers + sqlite-vss extension on
  top — only when there's evidence BM25 alone is insufficient.
