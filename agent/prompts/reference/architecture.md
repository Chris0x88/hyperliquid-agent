# Architecture — Where You Live

This is the on-demand detail about the system you run inside. The always-loaded prompt only has the essentials — read this when you need to understand *why* something is structured the way it is, or *what* a file actually does.

## The three processes

You — the AI agent — run as part of the **Telegram bot process**, not the daemon. There are three long-running processes managed by launchd:

1. **Daemon** (`com.hyperliquid.daemon`) — `python -m cli.main daemon start --tier watch --mainnet`. Ticks every ~120s. Runs all the iterators (risk, guard, connector, signal generation, REFLECT, journal). Owns the ground truth for positions and risk gates.
2. **Telegram bot** (`com.hyperliquid.telegram`) — `python -m cli.telegram_bot`. Polls Telegram for messages every 2s. When a user message arrives, it routes to the AI agent (you) via `cli/telegram_agent.py`. Single-instance enforced via PID file.
3. **Heartbeat** (`com.hyperliquid.heartbeat`) — `common/heartbeat.py`. Lightweight 2-min monitoring loop. Detects daemon failures and broadcasts alerts.

You only run inside process #2. The daemon runs without you. Strategies execute autonomously via daemon iterators; you provide judgment on top.

## How a Telegram message becomes a response

1. `cli/telegram_bot.py` polls and receives the message.
2. If it's a slash command (e.g. `/status`, `/position`), the bot handles it directly via `cmd_*` handlers in `telegram_bot.py`.
3. If it's free-text, the bot calls `cli.telegram_agent.handle_ai_message(token, chat_id, text, user_name)`.
4. `handle_ai_message` (cli/telegram_agent.py:436) builds the message list:
   - System prompt from `agent/AGENT.md` + `agent/SOUL.md`
   - LIVE CONTEXT (built fresh — see below)
   - Last 20 messages of history from `data/daemon/chat_history.jsonl`
   - The new user message
5. The list is sent to your model (Sonnet 4.6 by default — see `data/config/model_config.json`).
6. You may emit tool calls. The runtime executes them via `cli/agent_tools.py:_TOOL_DISPATCH` (READ tools auto, WRITE tools require user approval via inline keyboard).
7. Your final text response goes back via Telegram.
8. Both the user message and your response are appended to `chat_history.jsonl`.

## The model routing

`_get_active_model()` reads `data/config/model_config.json` and returns the user's selection. The user changes it via `/models`. As of the F3 fix (audit), all subsystems honour this — including dream consolidation and context compaction, which used to be hardcoded to Haiku via OpenRouter.

When the active model is Anthropic, calls go through the Claude Code CLI binary (`_call_via_claude_cli`) which uses your OAuth session token. When it's a non-Anthropic model, calls fall through to `_call_openrouter_direct` which needs an OpenRouter API key. Free-model fallback chain (`_try_fallback_chain`) is only entered after the primary model fails.

## LIVE CONTEXT — what gets injected

Built by `_fetch_account_state_for_harness()` in `cli/telegram_agent.py:825`. This fetches:
- Native HL clearinghouse state (positions, equity, margin)
- xyz dex clearinghouse state (BRENTOIL, GOLD, SILVER, etc.)
- Spot USDC balance
- Working state (escalation level, alerts) from `data/memory/working_state.json`
- Then `build_multi_market_context()` in `common/context_harness.py` adds technical signals, candles, thesis snippets, and budgets the whole thing to ~3500 tokens

Critically: the markets list is `watchlist + any coin with an open position`. Position-having markets are auto-included even if not on the watchlist. This is why you can see positions in non-watchlist markets like SP500.

## The daemon iterators

The daemon ticks every ~120s. On each tick, iterators run in order against a shared `TickContext`. Notable ones in `cli/daemon/iterators/`:

- `connector.py` — fetches all positions from native + xyz, merges into `ctx.positions`
- `risk.py` — protection chain (drawdown, stoploss, daily loss, ruin protection). Walks all positions.
- `guard.py` — per-position trailing stops and profit-protection logic. Walks all positions.
- `account_collector.py` — snapshots equity + drawdown every 5 min, tracks high-water mark
- `execution_engine.py` — applies conviction-band sizing, weekend/thin-session leverage caps, ruin prevention (40% drawdown = unconditional close-all)
- `journal.py` — appends realised trades to the trade journal
- `reflect_engine` (via `modules/reflect_engine.py`) — meta-evaluation, win-rate, Sharpe, lessons

The daemon does NOT need you to be running. Strategies execute autonomously based on signals + thesis. Your role is judgment on top — discretionary decisions, novel situations, conviction calls.

## Key data files

- `data/config/watchlist.json` — the markets you can act on (THIS IS THE SOURCE OF TRUTH for "approved", not `AGENT.md` text)
- `data/config/model_config.json` — currently selected AI model
- `data/thesis/<market>_state.json` — per-market conviction and direction. Drives execution sizing.
- `data/agent_memory/MEMORY.md` + `<topic>.md` — your persistent memory across sessions
- `data/daemon/chat_history.jsonl` — every chat message ever, append-only
- `data/daemon/state.json` — daemon tick state
- `data/feedback.jsonl` — user feedback via `/feedback`
- `data/bugs.md` — user bugs via `/bug`
- `data/todos.jsonl` — user todos via `/todo`

## Key code files

- `cli/telegram_bot.py` — slash command handlers (`cmd_*`), button menu (`mn:` callbacks), single-instance enforcement
- `cli/telegram_agent.py` — adapter that turns a Telegram message into an agent invocation. Owns model routing, history loading, dream/compaction triggers.
- `cli/agent_runtime.py` — the core agent runtime (ported from Claude Code). Tool calling loop, streaming, compaction, dream. **Load-bearing — do not modify casually.**
- `cli/agent_tools.py` — tool definitions and dispatch. Where new tools get registered.
- `cli/hl_adapter.py` — `DirectHLProxy` exchange adapter. `place_order(instrument, side, size, price, tif)` is the canonical order entry. Note: there is no `market_order` method (was a long-standing bug in the agent's tool wrapper, fixed in audit F7-A).
- `common/context_harness.py` — multi-market context assembly with token budget
- `common/tools.py` — pure-function tool implementations (web_search, memory_read/write, etc.)

## What to remember

- Read `data/config/watchlist.json` for ground truth on approved markets, not `AGENT.md`
- The daemon is doing real work without you — don't assume "the system" is just you and your tool calls
- LIVE CONTEXT is built fresh per message, but cached for 10s — usually current to within 10s
- Your chat history is loaded per turn, not held in memory across restarts
- Both clearinghouses have positions (native HL + xyz dex) — always check both when reasoning about exposure
