---
kind: architecture
tags:
  - architecture
  - data-discipline
  - p9
  - p10
---

# Data Discipline — P9 + P10

Two paired operating principles from [[plans/NORTH_STAR|NORTH_STAR]]:

- **P9 — Historical oracles are forever**: append-only, never delete
- **P10 — Preserve everything, retrieve sparingly, bound every read path**: the corpus grows forever, the working set per decision is bounded

These are a **pair**, not alternatives. You must honor both.

## The contract in one sentence

> Data lives forever, but no single read returns more than what fits
> cleanly in a Telegram message or in the agent's context budget for
> one decision.

## Per-surface retrieval bounds (the table)

| Surface | Reaches | Default cap | Hard ceiling | Per-row truncation |
|---|---|---|---|---|
| Agent tool that returns rows (`search_lessons`, `get_feedback`, `trade_journal`, `get_signals`) | Agent context window | 5-10 | **25-50 (hard clamp)** | ✅ body fields capped |
| Prompt injection section (`build_lessons_section`) | Agent system prompt | 5 | 5 | ✅ summary only |
| System prompt inputs (AGENT.md / SOUL.md / MEMORY.md) | Agent system prompt | N/A | **20KB per file** | ✅ with warning log |
| Telegram list commands (`/lessons`, `/feedback list`, `/chathistory`) | Telegram message | 10-15 | 25-50 | ✅ text fields capped at ~80-200 chars |
| Telegram detail commands (`/lesson <id>`, `/feedback show <id>`) | Telegram message | 1 row | 1 row | ✅ body cap at ~3000 chars |
| Iterator alerts (entry critic, action queue, liquidation monitor) | Telegram message | 1 alert per event | N/A | ✅ message body bounded |

## Why this matters — the asymmetric failure mode

An unbounded read path that returns 21 rows today returns 21,000 rows
in three years. The failure is **silent** (no crash, just ballooning
context) and **asymmetric** (adding the bound fixes it retroactively;
not adding it compounds every day).

Three latent bugs were caught by the 2026-04-09 audit (Agent E):

1. **`_tool_get_feedback`** — accepted any `limit` the agent passed,
   full-file read every call. Fixed: clamp 1-25, default 10, per-row
   truncation at 500 chars. See [[tools/get-feedback]].
2. **`_tool_trade_journal`** — full-file read + unbounded limit. Fixed:
   clamp 1-25 + streaming deque tail-read so a 10k-row journal doesn't
   get fully decoded. See [[tools/trade-journal]].
3. **`_tool_get_signals`** — same pattern. Fixed: clamp 1-50 + streaming
   tail-read. See [[tools/get-signals]].

And the **CRITICAL POTENTIAL** finding I missed on the first commit:

4. **`_build_system_prompt()` unbounded inputs** — AGENT.md, SOUL.md,
   and especially MEMORY.md (which is **agent-writable via the dream
   cycle**) were read verbatim with no cap. A runaway dream could have
   inflated the system prompt unbounded on every subsequent call.
   Fixed: new `_read_capped(path, label)` helper hard-caps each at
   20KB (~5000 tokens) with a loud warning log. See
   `cli/telegram_agent.py:_read_capped` + tests in
   `tests/test_agent_tools_p10_bounds.py`.

## The append-only stores

These files are **never deleted** (P9) but every read against them has
a hard cap (P10):

| Store | Path | Grows via | Read via |
|---|---|---|---|
| Chat history | `data/daemon/chat_history.jsonl` | `_log_chat()` in `cli/telegram_agent.py` | `_load_chat_history` (deque tail), `/chathistory` command |
| Feedback | `data/feedback.jsonl` | `/feedback <text>` + event rows | `feedback_store.load_feedback`, `/feedback list/search`, `get_feedback` tool |
| Todos | `data/todos.jsonl` | `/todo <text>` + event rows | `feedback_store.load_todos`, `/todo list/search` |
| Journal (closed trades) | `data/research/journal.jsonl` | `journal_engine` on position close | `lesson_author` iterator, `trade_journal` tool |
| Lessons corpus | `data/memory/memory.db` `lessons` table + `lessons_fts` FTS5 | `_author_pending_lessons` (dream cycle) | `search_lessons` / `get_lesson` tools, `/lessons` commands |
| News catalysts | `data/news/catalysts.jsonl` | `news_ingest` iterator (RSS/iCal) | `catalyst_deleverage` iterator, `entry_critic` |
| Supply disruptions | `data/supply/state.json` + ledger files | `/disrupt` command + scrapers | `entry_critic`, oil_botpattern |
| Heatmap zones + cascades | `data/heatmap/zones.jsonl`, `cascades.jsonl` | `heatmap` iterator (L2 + OI polling) | `entry_critic`, `/heatmap` command |
| Bot patterns | `data/research/bot_patterns.jsonl` | `bot_classifier` iterator | `oil_botpattern`, `entry_critic` |
| Entry critiques | `data/research/entry_critiques.jsonl` | `entry_critic` iterator on new position | `/critique` command |

## The critical rules (from MASTER_PLAN)

- **Rule 9 — Append-only forever**: no row ever deleted from any of
  the stores above. State changes are NEW append-only event rows that
  reference the original by id (see `modules/feedback_store.py` for
  the event-sourced pattern).
- **Rule 11 — Preserve everything, retrieve sparingly**: every code
  path that reads from a historical store and feeds the result into
  an agent prompt, a Telegram message, or a tool result MUST have a
  hard upper cap (parameter default + hardcoded ceiling that clamps
  user input).

## The rotation audit story

On 2026-04-09, Agent C audited `chat_history.jsonl` for rotation
bugs. Result: **121 historical chat rows were deleted**, not by code
— by a manual session-level truncation on April 2-3 before the
"never delete" rule was documented. The 102 rows in
`chat_history.jsonl.bak` and 19 rows in `.bak2` covered the gap but
weren't reachable via `/chathistory search` until [[commands/chathistory]]
was taught to union the .bak files for search queries.

**Going forward, manual deletion cannot recur.** The writer
(`_log_chat()`) has always been append-only; Agent C added a
**static source-code scan test** to `test_chat_history_persistence.py`
that fails if any `open(..., "w")`, `unlink`, `rename`, or
`write_text` pattern is ever added to the writer module.

## Why this is load-bearing

Every historical-oracle store will grow to gigabytes over a 5-year
trading horizon. At that scale:
- Unbounded file reads become wall-clock latency dominators (the
  agent's chat history read used to scan the whole file on every
  turn — fixed by deque tail-read in commit 347d8e5)
- Unbounded tool returns blow out the LLM's context window silently
- Missing per-row truncation lets a single giant row (pasted article
  in `/feedback`, bloated lesson body) eat the entire tool result budget
- A runaway agent write (dream cycle → MEMORY.md) can cascade into
  the system prompt on the next session

All of these have been fixed. The tests in
`tests/test_agent_tools_p10_bounds.py` pin the bounds so they can't
regress.

## See also

- [[Overview]] — system architecture
- [[plans/NORTH_STAR]] — P9 + P10 full text
- [[plans/MASTER_PLAN]] — Critical Rules 9 + 11
- [[tools/_index]] — agent tools index
- [[data-stores/_index]] — data stores and configs
