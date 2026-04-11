# Learning Path: AI Agent Architecture

How the embedded AI agent works -- from user message to tool execution to response. Read these files in order.

---

## 1. `agent/AGENT.md` + `agent/SOUL.md` -- System prompt files

**Start here.** These two files define WHO the agent is and HOW it behaves.

`AGENT.md` -- Trading domain instructions:
- Role definition: autonomous trading agent for HyperLiquid perps
- Coin name mapping table (user says "oil" -> tool uses "BRENTOIL")
- Complete tool catalogue: READ tools (auto-execute) vs WRITE tools (approval required)
- Codebase tools for self-inspection (`read_file`, `search_code`, `list_files`)
- Trading rules, memory system, critical gotchas

`SOUL.md` -- Response protocol:
- Data source priority: LIVE CONTEXT in system prompt > tool calls > chat history
- Response quality rules: numbers-first, under 3500 chars, Telegram-formatted
- Confidence levels ("The data shows..." vs "My read is...")
- Persona: Druckenmiller mindset, challenge thesis with data, respect oil expertise

These files are read from disk on every message and injected into the system prompt. Editing them changes agent behavior immediately -- no restart required.

**What you'll learn:** The agent's identity, what tools it has access to, and the response contract.

---

## 2. `cli/agent_runtime.py` -- Core agent loop

**The engine.** This module is ported from Claude Code's architecture and provides the mechanical bones of the agent.

### System prompt assembly (`build_system_prompt()`, line ~48)

Assembles the full prompt from five sections, joined by `---` separators:

1. `_PROMPT_CORE` (line ~39) -- universal agent instructions (plan, act, verify, parallel tools)
2. `agent_md` -- contents of `agent/AGENT.md`
3. `soul_md` -- contents of `agent/SOUL.md`
4. `memory_content` -- agent memory from `data/agent_memory/`
5. `lessons_section` -- BM25-ranked lessons from `data/memory/memory.db` (via `build_lessons_section()`, line ~83)
6. `live_context` -- real-time prices, positions, thesis (assembled by `context_harness.py`)

### Lesson injection (`build_lessons_section()`, line ~83)

- Searches the FTS5 lessons corpus for relevant past trade lessons
- Ranks by BM25 over summary + body + tags
- Kill switch: `_LESSON_INJECTION_ENABLED` module attribute (line ~45)
- Failure-safe: any exception is logged and swallowed (never breaks the prompt)

### Context compaction (`accordion_truncate()`, line ~431)

Claude Code-style context management:
- Triggers when total token estimate exceeds 150k tokens
- Walks backward through message history
- Truncates tool-result text in messages older than the last 4 messages (2 turns)
- Preserves the narrative flow while cutting large data dumps

### Memory consolidation (`should_dream()`, line ~496)

- Triggers after 24h AND 3+ conversations since last dream
- Compresses conversation history into persistent memory
- Stored in `data/agent_memory/`

**What you'll learn:** How the system prompt is assembled, how context is managed within token limits, and the memory lifecycle.

---

## 3. `cli/telegram_agent.py` -- Telegram adapter

**The bridge between Telegram and the agent runtime.** Handles model selection, API calls, streaming, and tool execution loops.

### Auth & model selection (lines ~32-68)

- Session token detection: keys with the OAuth session prefix use Bearer auth, others use x-api-key
- Beta headers (line ~62-68): must match Claude Code's exact beta set for features to work
- Cache control (line ~83): 1h TTL for subscribers (cached tokens don't count against rate limits)
- Default model: `anthropic/claude-haiku-4-5` (line ~41)
- Fallback chain (line ~43): free models on OpenRouter if primary fails
- Model config: user selects via `/models` command, stored in `data/config/model_config.json`

### Dual API support

- **Anthropic direct** (line ~40): `https://api.anthropic.com/v1/messages` -- used when session token is available
- **OpenRouter** (line ~39): `https://openrouter.ai/api/v1/chat/completions` -- used for free/fallback models

### Tool execution loop (line ~54)

- Maximum 12 tool loops per message (`_MAX_TOOL_LOOPS`)
- Triple-mode tool calling:
  1. **Native function calling** -- model returns structured tool_use blocks (Anthropic/OpenRouter)
  2. **Regex parsing** (line ~98) -- `[TOOL: name {"arg": "val"}]` text patterns (for free models)
  3. **Code block parsing** -- Python code blocks parsed by `common/code_tool_parser.py` (AST-based)

### Chat history

- Last 20 messages stored in `data/daemon/chat_history.jsonl` (line ~36)
- Capped at 12000 chars total (line ~37) to stay within context windows
- Logged to JSONL for Claude Code to learn from

**What you'll learn:** How auth works (session tokens vs API keys), the fallback chain, and the three tool-calling modes.

---

## 4. `cli/agent_tools.py` -- Tool definitions

**The agent's hands.** Defines tool schemas (OpenAI format) and their implementations.

### Tool categories (lines ~29-32)

| Category | Behavior | Examples |
|----------|----------|---------|
| READ | Auto-execute, no approval needed | `market_brief`, `account_summary`, `live_price`, `analyze_market`, `check_funding`, `get_orders` |
| WRITE | Require user approval via inline keyboard | `place_trade`, `update_thesis`, `close_position`, `set_sl`, `set_tp`, `memory_write` |
| DISPLAY | Pre-formatted output sent directly to Telegram | `get_calendar`, `get_research`, `get_technicals` |

### Tool approval flow (lines ~34-64)

WRITE tools use a durable pending-action store:
1. Agent requests a WRITE tool call
2. System creates a pending action (UUID key) and sends Telegram inline keyboard with Approve/Reject buttons
3. Pending actions are file-backed (`data/state/pending_actions.json`) so approvals survive bot restarts
4. Actions expire after 300 seconds (5 min)
5. On approval, the tool executes; on reject/timeout, the action is dropped

### Tool definitions (`TOOL_DEFS`, line ~71)

OpenAI function-calling format. Each tool has:
- `name` -- the identifier the model uses
- `description` -- one-line purpose (the model reads this to decide when to call)
- `parameters` -- JSON Schema for arguments

Key READ tools:
- `market_brief` -- price, technicals, position, thesis, memory for one market
- `account_summary` -- equity, positions, spot balances
- `analyze_market` -- deep technicals (ATR, Bollinger, volume, support/resistance)
- `check_funding` -- cumulative funding cost for a position

Key WRITE tools:
- `place_trade` -- submits an order via the HL adapter
- `update_thesis` -- writes/updates a thesis JSON file

Implementations call the same underlying libraries as the Telegram slash commands (`common/tools.py`, `modules/candle_cache`, `common/account_state`).

**What you'll learn:** The three tool categories, the approval flow for writes, and how tools map to the underlying trading infrastructure.

---

## 5. `common/context_harness.py` -- Relevance-scored context assembly

**How the agent gets its situational awareness.** This module replaces flat data dumps with a tiered, token-budgeted context assembler.

### Tier model (line ~46)

| Tier | Budget % | Contents |
|------|----------|----------|
| `critical` | 40% | Active alerts, current position, market snapshot |
| `relevant` | 35% | Thesis state, recent events, learnings |
| `background` | 25% | Historical summaries, research notes |

### ContextBlock (line ~54)

Each piece of context is wrapped in a `ContextBlock` with:
- `name` -- identifier for logging which blocks were included/dropped
- `content` -- the actual text
- `tier` -- critical/relevant/background
- `relevance` -- 0.0-1.0 score for sorting within a tier

### Assembly (`build_thesis_context()`, line ~81)

1. Scores each context block by relevance (recent > active position > historical)
2. Fills critical tier first (always included)
3. Fills relevant tier if budget remains
4. Fills background tier last
5. Returns `AssembledContext` with the text plus metadata (blocks included/dropped, budget usage)

The result is injected into the system prompt as "--- LIVE CONTEXT ---".

**What you'll learn:** How the agent sees a relevance-ranked view of the world, and how token budgets prevent context overflow.

---

## Message flow diagram

```
User sends message on Telegram
        |
        v
telegram_bot.py
  (not a /command? route to agent)
        |
        v
telegram_agent.py
  1. Load AGENT.md + SOUL.md from disk
  2. Load chat history (last 20 messages)
  3. Select model (Anthropic direct or OpenRouter)
        |
        v
agent_runtime.py :: build_system_prompt()
  1. _PROMPT_CORE (universal agent instructions)
  2. agent_md (AGENT.md)
  3. soul_md (SOUL.md)
  4. agent memory (data/agent_memory/)
  5. lessons (FTS5 BM25 search in memory.db)
  6. live context (context_harness.py)
        |
        v
API call (Anthropic or OpenRouter)
        |
        v
Response with possible tool_use blocks
        |
   ┌────┴────┐
   | Tool?   |
   └────┬────┘
   yes  |  no
   |    |   \
   v    |    v
agent_tools.py    Send text to Telegram
  |
  ├── READ tool? -> execute immediately, return result
  ├── WRITE tool? -> create pending action, send approve/reject keyboard
  └── DISPLAY tool? -> execute, send formatted output directly
  |
  v
Loop back to API with tool result (up to 12 iterations)
  |
  v
Final text response -> Telegram
  |
  v
accordion_truncate() if context is getting large
  |
  v
should_dream()? -> consolidate memory if due
```
