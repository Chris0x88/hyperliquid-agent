# AI Agent

The AI agent handles free-text Telegram messages via OpenRouter or Anthropic direct API. It has tool-calling capability with a READ/WRITE approval split, persistent memory, codebase access, web search, and self-modification capability. Defined in `cli/telegram_agent.py` with tools in `cli/agent_tools.py` and `common/tools.py`.

## How It Works

When a Telegram message does not match any slash command, `handle_ai_message()` is called:

1. Build system prompt from `agent/AGENT.md` + `agent/SOUL.md` + agent memory (`data/agent_memory/MEMORY.md`)
2. Assemble live context: account state, market snapshots (1h/4h/1d candles), thesis data
3. Load chat history (last 20 messages, capped at 12000 chars)
4. Send to model (Anthropic direct or OpenRouter) with tool definitions
5. Process tool calls in a loop (max 8 iterations)
6. Send final response back to Telegram

## Triple-Mode Tool Calling

Three parsing modes form a fallback chain to support both paid and free models:

1. **Native `tool_calls`** — paid models and Anthropic (Opus/Sonnet/Haiku) return structured function calls. Parsed directly.
2. **Regex `[TOOL: name {args}]`** — free models output text-based invocations. Parsed by `_parse_text_tool_calls()`.
3. **Python code blocks** — free models write `tool_name(arg=val)` in fenced code blocks. Parsed by `common/code_tool_parser.py` using `ast.parse` (never eval/exec).

## Tool Categories

### Trading Tools (READ — auto-execute)
Market analysis, account state, prices, funding, orders, trade journal, thesis, daemon health. See `TOOL_DEFS` in `cli/agent_tools.py`.

### General Tools (READ — auto-execute)
- `read_file(path)` — read any project file (sandboxed to project root)
- `search_code(pattern, path)` — grep the codebase
- `list_files(pattern)` — glob for files
- `web_search(query)` — search the internet via DuckDuckGo
- `memory_read(topic)` — read from persistent memory

### Write Tools (require Telegram approval)
- `place_trade`, `update_thesis` — trading actions
- `memory_write(topic, content)` — persist knowledge
- `edit_file(path, old_str, new_str)` — modify project files (Claude Code pattern)
- `run_bash(command)` — run shell commands (30s timeout, blocked patterns)

## Memory System

Persistent memory in `data/agent_memory/`:
- `MEMORY.md` — index file, auto-loaded into system prompt every message
- Topic files (`{name}.md`) — created by agent via `memory_write` tool
- Agent maintains its own index when writing new topics

## Model Support

- **Anthropic direct** (Opus 4.6, Sonnet 4.6, Haiku 4.5) — session tokens or API keys
- **OpenRouter free** — Step 3.5, Qwen 3.6+, DeepSeek V3, etc.
- **OpenRouter paid** — Gemini Flash/Pro, DeepSeek R1, etc.

Model configured via `/models` command, stored in `data/config/model_config.json`.

## Security

- File operations sandboxed to project root (no `..` traversal)
- Bash has blocked command patterns and 30s timeout
- All WRITE tools require explicit user approval via Telegram inline keyboard
- Pending actions expire after 5 minutes

## Key Files

- `cli/telegram_agent.py` — agent loop, API calls, context assembly
- `cli/agent_tools.py` — tool definitions (OpenAI format) + dispatch
- `common/tools.py` — unified tool functions (return dicts)
- `common/tool_renderers.py` — compact AI output formatting
- `common/code_tool_parser.py` — AST-based code block parser
- `agent/AGENT.md` — system prompt instructions
- `agent/SOUL.md` — response protocol
