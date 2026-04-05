# AI Agent

The AI agent handles free-text Telegram messages via OpenRouter. It has tool-calling capability with a READ/WRITE approval split. Defined in `cli/telegram_agent.py` with tools in `cli/agent_tools.py`.

## How It Works

When a Telegram message does not match any slash command, `handle_ai_message()` is called:

1. Build system prompt from `openclaw/AGENT.md` + `openclaw/SOUL.md`
2. Assemble live context: account state, market snapshots (1h/4h/1d candles), thesis data, memory summaries
3. Load chat history (last 20 messages, capped at 12000 chars)
4. Send to OpenRouter with tool definitions
5. Process tool calls in a loop (max 3 iterations)
6. Send final response back to Telegram

## Triple-Mode Tool Calling

Three parsing modes form a fallback chain to support both paid and free models:

1. **Native `tool_calls`** -- paid models return structured function calls via OpenRouter's native API. Parsed directly.
2. **Regex `[TOOL: name {args}]`** -- free models output text-based invocations. Parsed by `_parse_text_tool_calls()` in `telegram_agent.py`.
3. **Python code blocks** -- free models write `tool_name(arg=val)` in fenced code blocks. Parsed by `common/code_tool_parser.py` using `ast.parse` (never eval/exec). Only whitelisted function names and literal arguments are accepted.

All three modes converge at `agent_tools.execute_tool()`.

## READ vs WRITE Tools

Tool definitions live in `TOOL_DEFS` in `agent_tools.py`. The split:

- **READ tools** execute automatically and return results to the model for the next loop iteration. These include market analysis, account summaries, price checks, order queries, funding data, and trade journal lookups.
- **WRITE tools** (listed in `WRITE_TOOLS` set) require user approval. The agent stores a pending action with a 5-minute TTL and sends an inline keyboard (`[Approve] [Reject]`) to Telegram. Only after the user taps Approve does execution proceed.

See `TOOL_DEFS` and `WRITE_TOOLS` in `cli/agent_tools.py` for the current tool inventory.

## Context Pipeline

Every AI message triggers a fresh context build (`_build_live_context()`):

- Account equity + open positions from both clearinghouses (native + xyz)
- Market snapshots with technicals for all watchlist coins + any coins with open positions
- Active thesis data (conviction, direction, TP/SL)
- Compressed memory summaries from SQLite event log
- Context harness enforces a ~3500 token budget with relevance scoring

## Model Selection

Models are configured in `data/config/model_config.json` with a curated list of free and paid models. The user can switch models via `/models` in Telegram. Default: a free model (currently `stepfun/step-3.5-flash:free`). All requests go through `openrouter.ai/api/v1/chat/completions` with proper required headers and 429 retry logic.
