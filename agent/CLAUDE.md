# agent/ — AI Agent Runtime, Tools, Context

The embedded Claude agent: runtime, tool definitions, context assembly, and prompt files.

## Key Files

| File | Purpose |
|------|---------|
| `runtime.py` | Core agent runtime — system prompt, parallel tools, SSE streaming, compaction |
| `tools.py` | Agent tool definitions (READ/WRITE/DISPLAY modes), pending action store |
| `tool_functions.py` | Pure data functions returning dicts — the single source of truth for all tool logic |
| `context_harness.py` | Context pipeline — assembles candles, positions, memory for agent decisions |
| `tool_renderers.py` | Output formatting — `render_for_ai()` (compact) + future `render_for_telegram()` |
| `code_tool_parser.py` | Code block parser for tool call extraction |
| `trade_evaluator.py` | Deterministic trade setup evaluations injected into agent context |

## Prompt Files

| File | Purpose |
|------|---------|
| `prompts/AGENT.md` | Agent system prompt |
| `prompts/SOUL.md` | Agent personality and trading philosophy |
| `prompts/reference/` | Architecture, rules, tools, workflows reference docs |

## Gotchas

- Triple-mode tool calling: native → regex → code blocks fallback
- Context pipeline refreshes candles for ALL watchlist + position coins
- Agent memory persisted in `data/agent_memory/`
- `common/renderer.py` (Renderer ABC) is the interface abstraction — NOT in this package
