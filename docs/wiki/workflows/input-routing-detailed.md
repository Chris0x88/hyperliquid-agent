# Input Routing & Workflow Map — Detailed End-to-End

**Document Version:** 2026-04-07 (verified, reconciled with code)
**Architecture Rule:** Slash commands = fixed code. AI-suffixed commands (e.g., `/briefai`) = AI agent path. Natural-language messages = AI agent path.

> **Verification status:** Routing flow has been spot-checked against
> `cli/telegram_bot.py` and `cli/telegram_agent.py`. Specific line numbers are
> pinned to function names below per `MAINTAINING.md` no-counts rule. See
> `verification-ledger.md` and `telegram-input-trace.md` for the canonical
> step-by-step trace.

---

## Table of Contents

1. [Architecture Principles](#architecture-principles)
2. [Command Registry](#command-registry)
3. [Telegram Entrypoint](#telegram-entrypoint)
4. [CLI Entrypoint](#cli-entrypoint)
5. [Message Routing Workflows](#message-routing-workflows)
6. [Tool Availability Matrix](#tool-availability-matrix)
7. [Side Effects & State Changes](#side-effects--state-changes)

---

## Architecture Principles

### The Rule

The system enforces **three mutually-exclusive message paths:**

| Path | Entry | Handler | State Changes | Approval |
|------|-------|---------|---|---|
| **Fixed-code slash** | `/cmd` (no `ai` suffix) | Pure Python code | Limited to logs, disk caches | None required |
| **AI-suffix slash** | `/cmdai` | AI runtime + tool approval | Trading, thesis write, file edit | User must approve WRITE tools |
| **Natural language** | Free text (Telegram) | AI runtime + tool approval | Trading, thesis write, file edit | User must approve WRITE tools |

### File Roles

| File | Role |
|------|------|
| `cli/telegram_bot.py` → `run()` | Telegram polling loop + message router (fixed command detection vs. NL path) |
| `cli/telegram_bot.py` → `HANDLERS` dict | Slash command → handler function mapping (search for `HANDLERS = {`) |
| `cli/telegram_agent.py` → `handle_ai_message()` | AI agent runtime for Telegram (message loop, tool execution, streaming) |
| `cli/agent_tools.py` → `TOOL_DEFS`, `execute_tool()`, `is_write_tool()` | Tool definitions and implementations (agent-callable tools) |
| `cli/agent_runtime.py` | Streaming, parallel tool execution, system prompt assembly |
| `cli/mcp_server.py` | MCP server (alternative tool access, not used in Telegram path) |
| `cli/main.py` → `app = typer.Typer()` | Typer CLI app registration (fixed CLI commands only) |
| `cli/engine.py` → `TradingEngine.run()` | Autonomous trading loop (strategy runner, NOT AI-driven) |
| `cli/commands/*.py` | Fixed CLI command implementations (no AI calls) |

---

## Command Registry

### Telegram Slash Commands (ALL registered in `cli/telegram_bot.py:2940-3012`)

**Legend:**
- 🔧 **FIXED** = pure code, no AI, no tool approval needed
- 🤖 **AI** = AI agent path, tool approval required for WRITE tools
- ⚠️ **HYBRID** = fixed code with optional AI injection

#### Market & Portfolio Data (🔧 FIXED — READ-ONLY)

| Command | Handler | File:Line | Classification | Output | Notes |
|---------|---------|-----------|-----------------|--------|-------|
| `/status`, `status` | `cmd_status()` | `telegram_bot.py:421` | FIXED | Portfolio state table | Live data from HL API |
| `/price`, `price` | `cmd_price()` | `telegram_bot.py:518` | FIXED | Watchlist prices | No AI, cached watchlist coins |
| `/orders`, `orders` | `cmd_orders()` | `telegram_bot.py:585` | FIXED | Open orders grid | From HL `openOrders` endpoint |
| `/pnl`, `pnl` | `cmd_pnl()` | `telegram_bot.py:607` | FIXED | P&L breakdown | Realized + unrealized from state |
| `/market`, `/m` | `cmd_market()` | `telegram_bot.py:1220` | FIXED | Tech analysis, funding, OI | Uses CandleCache, no AI |
| `/position`, `/pos` | `cmd_position()` | `telegram_bot.py:1362` | FIXED | Single position detail | Risk metrics, liq distance |
| `/watchlist`, `/w` | `cmd_watchlist()` | `telegram_bot.py:763` | FIXED | Markets + current prices | Categorized by asset class |
| `/signals`, `/sig` | `cmd_signals()` | `telegram_bot.py:921` | FIXED | Pulse/Radar signal grid | From signal journal files |
| `/diag` | `cmd_diag()` | `telegram_bot.py:2018` | FIXED | Error log, tool calls | Diagnostics only |
| `/health`, `/h` | `cmd_health()` | `telegram_bot.py:1588` | FIXED | System health table | Daemon status, memory, API |
| `/models`, `/model` | `cmd_models()` | `telegram_bot.py:1918` | FIXED | Model list + selector grid | Callback-driven (not AI input) |
| `/help` | `cmd_help()` | `telegram_bot.py:1080` | FIXED | Full command list | Text dump |
| `/guide`, `/g` | `cmd_guide()` | `telegram_bot.py:1539` | FIXED | Usage guide | Markdown help text |
| `/commands` | `cmd_commands()` | `telegram_bot.py:665` | FIXED | Command list (short/long) | Formatted command reference |

#### Brief & Reporting (⚠️ HYBRID)

| Command | Handler | File:Line | Classification | Path | Notes |
|---------|---------|-----------|-----------------|------|-------|
| `/brief`, `/b` | `cmd_brief()` | `telegram_bot.py:747` | FIXED | `daily_report.generate_report(mechanical=True)` | Pure code: portfolio + technicals + 24h funding |
| `/briefai`, `/bai` | `cmd_briefai()` | `telegram_bot.py:756` | **AI** | `daily_report.generate_report(mechanical=False)` | Adds thesis line + catalyst calendar (AI-influenced content) |

**Key distinction:** `/brief` = mechanical code. `/briefai` = hybrid (same mechanics, but thesis + catalysts are AI-influenced).

#### Trading & Position Management (🤖 AI or 🔧 FIXED hybrid)

| Command | Handler | File:Line | Classification | Approval? | Notes |
|---------|---------|-----------|-----------------|-----------|-------|
| `/close` | `cmd_close()` | `telegram_bot.py:2819` | FIXED/Menu-driven | Menu buttons → `_handle_close_position()` | Calls `place_trade` tool (AI-capable) but user selects via menu |
| `/sl` | `cmd_sl()` | `telegram_bot.py:2829` | FIXED/Menu-driven | Menu buttons → `_handle_sl_prompt()` | Calls `set_sl` tool (AI-capable) |
| `/tp` | `cmd_tp()` | `telegram_bot.py:2870` | FIXED/Menu-driven | Menu buttons → `_handle_tp_prompt()` | Calls `set_tp` tool (AI-capable) |
| `/menu`, `/start` | `cmd_menu()` | `telegram_bot.py:2803` | FIXED | Inline buttons (no AI) | Interactive menu dispatch |

#### System Control (🔧 FIXED)

| Command | Handler | File:Line | Classification | Notes |
|---------|---------|-----------|-----------------|-------|
| `/restart` | `cmd_restart()` | `telegram_bot.py:882` | FIXED | Kills telegram_bot process |
| `/rebalancer` | `cmd_rebalancer()` | `telegram_bot.py:1138` | FIXED | Start/stop/status rebalancer daemon |
| `/rebalance` | `cmd_rebalance()` | `telegram_bot.py:1180` | FIXED | Force vault rebalance NOW |
| `/authority`, `/auth` | `cmd_authority()` | `telegram_bot.py:1024` | FIXED | Show authority matrix (manual mode) |
| `/delegate` | `cmd_delegate()` | `telegram_bot.py:986` | FIXED | Delegate asset to agent |
| `/reclaim` | `cmd_reclaim()` | `telegram_bot.py:1011` | FIXED | Take asset back from agent |

#### Analytics & Feedback (🔧 FIXED)

| Command | Handler | File:Line | Classification | Notes |
|---------|---------|-----------|-----------------|-------|
| `/thesis` | `cmd_thesis()` | `telegram_bot.py:2090` | FIXED | Show/edit thesis state | Manual thesis management |
| `/memory`, `/mem` | `cmd_memory()` | `telegram_bot.py:1746` | FIXED | Memory system status | Consolidated teachings |
| `/bug` | `cmd_bug()` | `telegram_bot.py:1444` | FIXED | Report bug → diagnostic file |
| `/feedback`, `/fb` | `cmd_feedback()` | `telegram_bot.py:1466` | FIXED | Submit feedback → journal |
| `/todo` | `cmd_todo()` | `telegram_bot.py:1040` | FIXED | Manage TODO list (persistent) |
| `/powerlaw` | `cmd_powerlaw()` | `telegram_bot.py:867` | FIXED | BTC power law model chart |
| `/chart` | `cmd_chart()` | `telegram_bot.py:687` | FIXED | Market price chart (shorthand: `/chartoil`, `/chartbtc`, etc.) |
| `/addmarket` | `cmd_addmarket()` | `telegram_bot.py:784` | FIXED | Add market to whitelist (with confirmation) |
| `/removemarket` | `cmd_removemarket()` | `telegram_bot.py:842` | FIXED | Drop market from whitelist |

### CLI Commands (registered in `cli/main.py:45-67`, all 🔧 FIXED)

| Command | Handler | Classification | Notes |
|---------|---------|-----------------|-------|
| `hl run` | `run_cmd()` | FIXED | Autonomous trading engine (strategy loop) |
| `hl status` | `status_cmd()` | FIXED | Show persisted engine state |
| `hl trade` | `trade_cmd()` | FIXED | Single manual order placement |
| `hl account` | `account_cmd()` | FIXED | Account state snapshot |
| `hl strategies` | `strategies_cmd()` | FIXED | List available strategies |
| `hl guard` | `guard_app` (subcommand) | FIXED | Trailing stop management |
| `hl radar` | `radar_app` (subcommand) | FIXED | Opportunity scanner |
| `hl pulse` | `pulse_app` (subcommand) | FIXED | Capital inflow detector |
| `hl apex` | `apex_app` (subcommand) | FIXED | Multi-slot trading |
| `hl reflect` | `reflect_app` (subcommand) | FIXED | Performance review (strategy introspection) |
| `hl wallet` | `wallet_app` (subcommand) | FIXED | Keystore management |
| `hl setup` | `setup_app` (subcommand) | FIXED | Environment validation |
| `hl mcp` | `mcp_app` (subcommand) | FIXED | MCP server control |
| `hl skills` | `skills_app` (subcommand) | FIXED | Skill discovery |
| `hl journal` | `journal_app` (subcommand) | FIXED | Trade journal query |
| `hl keys` | `keys_app` (subcommand) | FIXED | Unified key management |
| `hl markets` | `markets_app` (subcommand) | FIXED | Market browser/filter |
| `hl data` | `data_app` (subcommand) | FIXED | Historical data fetch/cache |
| `hl backtest` | `backtest_app` (subcommand) | FIXED | Strategy backtesting |
| `hl daemon` | `daemon_app` (subcommand) | FIXED | Daemon monitoring |
| `hl heartbeat` | `heartbeat_app` (subcommand) | FIXED | Position auditor & risk monitor |
| `hl telegram` | `telegram_app` (subcommand) | FIXED | Telegram bot control |
| `hl commands` | `commands_app` (subcommand) | FIXED | Command list (CLI reference) |

---

## Telegram Entrypoint

### Entry Points

**File:** `cli/telegram_bot.py`  
**Main loop:** `run()` at line 3083  
**Poll interval:** 2 seconds (POLL_INTERVAL = 2.0)

### Message Reception & Routing Flow

```
telegram_bot.py:run()
    ↓
[every 2 seconds]
    ↓
tg_get_updates(token, offset) [L3123]
    ↓ (per update)
    ├─ callback_query? → _handle_model_callback() [L3198] / _handle_tool_approval() [L3202] / _handle_menu_callback() [L3209]
    │
    └─ message (text)?
        ↓
        [AUTH CHECK: sender_id must match chat_id] [L3220]
        ↓
        [PENDING INPUT CHECK: handle SL/TP price prompts] [L3224]
        ↓
        text.split()[0].lower() → cmd
        ↓
        cmd in HANDLERS? [L3246]
        │
        ├─ YES → DISPATCH FIXED COMMAND [L3250-3260]
        │   │
        │   ├─ RENDERER_COMMANDS? (special display handler)
        │   │   handler(TelegramRenderer(token, reply_chat_id), args)
        │   │
        │   └─ else: regular handler
        │       handler(token, reply_chat_id, args)
        │
        └─ NO → NOT A COMMAND [L3267]
            ↓
            [GROUP MESSAGE?] → IGNORE [L3269]
            ↓
            [DM MESSAGE] → AI PATH [L3274]
                ↓
                handle_ai_message(token, reply_chat_id, text, user_name)
                    [calls telegram_agent.py:444+]
```

### Fixed Command Dispatch (Example: `/status`)

```
telegram_bot.py:3227-3260 (routing)
    ↓
cmd_key = "/status" matches HANDLERS["/status"]
    ↓
handler = cmd_status (from telegram_bot.py:421)
    ↓
cmd_status(TelegramRenderer(token, reply_chat_id), "")
    ↓
[FIXED CODE EXECUTION]
    ├─ Fetch from HL API directly (requests.post)
    ├─ Read from persistent state (data/cli/state.db)
    ├─ Render via display.py:status_table()
    └─ Send to Telegram (TelegramRenderer.print())
    ↓
[NO AI CALLED]
[NO TOOL APPROVAL]
[NO DISK WRITE EXCEPT LOGS]
```

### AI-Suffix Slash Command Dispatch (Example: `/briefai`)

```
telegram_bot.py:3227-3260 (routing)
    ↓
cmd_key = "/briefai" matches HANDLERS["/briefai"]
    ↓
handler = cmd_briefai (from telegram_bot.py:756)
    ↓
cmd_briefai(token, reply_chat_id, "")
    ↓
_send_brief_pdf(token, reply_chat_id, mechanical=False, label="BriefAI")
    ↓
daily_report.generate_report(mechanical=False)
    ├─ [BUILDS PDF WITH THESIS + CATALYSTS]
    ├─ Thesis sourced from disk (data/thesis/*.json)
    ├─ Catalysts from hardcoded calendar
    └─ Returns path to PDF
    ↓
[SENDS TO TELEGRAM as sendDocument]
    ↓
[NO AI CALLED IN REAL-TIME]
[THESIS is PRE-COMPUTED by agent on schedule]
```

**Note:** `/briefai` is classified as **HYBRID**: the PDF is generated by fixed code, but its content (thesis line, catalysts) is derived from AI/research. The command handler itself never calls the AI runtime.

### Natural Language Dispatch (Example: user sends "What's the breakout strategy?")

```
telegram_bot.py:3227-3260 (routing)
    ↓
text = "What's the breakout strategy?"
cmd = "what's"
cmd_key = "/what's" → NOT in HANDLERS
    ↓
[NOT A COMMAND]
    ↓
[GROUP CHECK] → is_group = False (DM only)
    ↓
[AI PATH]
    ↓
telegram_agent.handle_ai_message(token, reply_chat_id, text, user_name="Chris")
    ↓
[AI RUNTIME] (see next section)
```

---

## AI Agent Runtime (Telegram NL Path)

**File:** `cli/telegram_agent.py:444+`  
**Function:** `handle_ai_message(token, chat_id, text, user_name)`

### Workflow

```
handle_ai_message() [telegram_agent.py:444]
    ├─ Load chat history (last 20 messages) [_load_chat_history:1227]
    ├─ Build system prompt [_build_system_prompt:774]
    │  ├─ Static: agent/AGENT.md + agent/SOUL.md
    │  └─ Dynamic: live_context (account state, prices, thesis)
    ├─ Build live context [_build_live_context:799]
    │  ├─ Account equity + positions (HL API)
    │  ├─ Market snapshots (CandleCache)
    │  ├─ Current thesis (data/thesis/)
    │  └─ Trade journal (last 5 trades)
    ├─ Append user message to conversation
    │
    ├─ [MODEL SELECTION]
    │  └─ _get_active_model() [1933]
    │     ├─ Try: data/config/model_config.json
    │     ├─ Fallback: anthropic/claude-haiku-4-5
    │     └─ Returns: model string (e.g., "anthropic/claude-sonnet-4")
    │
    ├─ [API CALL]
    │  └─ if anthropic model:
    │     ├─ _call_anthropic(messages, tools) [1525]
    │     │  ├─ Prepare session token or API key
    │     │  ├─ Stream request to Anthropic API with TOOL_DEFS
    │     │  └─ Return StreamResult (text, tool_calls, stop_reason)
    │     └─ else: _call_openrouter(messages, tools) [1680]
    │        └─ Same structure, different endpoint
    │
    ├─ [TOOL LOOP] (up to 12 iterations [_MAX_TOOL_LOOPS])
    │  └─ while stop_reason != "end_turn" and tool_calls available:
    │     ├─ for each tool_call:
    │     │  ├─ is_write_tool(tool_name)? [is_write_tool:1207]
    │     │  │  ├─ YES → Queue for approval
    │     │  │  │  ├─ Store in _pending_actions dict [store_pending:1212]
    │     │  │  │  ├─ Send Telegram buttons: [APPROVE] [REJECT]
    │     │  │  │  └─ WAIT for user callback [_handle_tool_approval:1991]
    │     │  │  │
    │     │  │  └─ NO (READ tool) → Execute immediately
    │     │  │     └─ execute_tool(tool_name, args) [agent_tools.py:1178+]
    │     │  │        ├─ _tool_market_brief() [445]
    │     │  │        ├─ _tool_account_summary() [493]
    │     │  │        ├─ _tool_live_price() [546]
    │     │  │        ├─ _tool_analyze_market() [569]
    │     │  │        ├─ _tool_get_orders() [592]
    │     │  │        ├─ _tool_trade_journal() [616]
    │     │  │        ├─ _tool_get_signals() [679]
    │     │  │        ├─ _tool_check_funding() [727]
    │     │  │        ├─ _tool_place_trade() [763] ← WRITE (approval required)
    │     │  │        ├─ _tool_update_thesis() [820] ← WRITE (approval required)
    │     │  │        ├─ _tool_close_position() [859] ← WRITE (approval required)
    │     │  │        ├─ _tool_set_sl() [888] ← WRITE (approval required)
    │     │  │        ├─ _tool_set_tp() [905] ← WRITE (approval required)
    │     │  │        ├─ _tool_read_file() [922]
    │     │  │        ├─ _tool_search_code() [932]
    │     │  │        ├─ _tool_list_files() [940]
    │     │  │        ├─ _tool_web_search() [948]
    │     │  │        ├─ _tool_memory_read() [958]
    │     │  │        ├─ _tool_memory_write() [965] ← WRITE (approval required)
    │     │  │        ├─ _tool_edit_file() [972] ← WRITE (approval required)
    │     │  │        ├─ _tool_run_bash() [979] ← WRITE (approval required)
    │     │  │        ├─ _tool_get_errors() [993]
    │     │  │        ├─ _tool_get_feedback() [1006]
    │     │  │        ├─ _tool_introspect_self() [1020]
    │     │  │        └─ _tool_read_reference() [1132]
    │     │  │
    │     │  └─ Append tool result to conversation
    │     │
    │     └─ Call AI again with tool results appended
    │        └─ goto next tool loop iteration
    │
    ├─ [STREAMING TO TELEGRAM]
    │  ├─ _tg_stream_response(token, chat_id, messages, tools) [313]
    │  │  ├─ Send initial placeholder message ("🤔 ...")
    │  │  ├─ Stream API call, update Telegram message every 1.5s
    │  │  ├─ On 401 (auth fail): _force_token_refresh()
    │  │  └─ Split response into 4096-char chunks if needed [_split_message:2070]
    │  │
    │  └─ Log full response to chat history [_log_chat:1261]
    │
    └─ [ON ERROR]
       ├─ Rate limit (429) → "Try again in a minute"
       ├─ Auth (401) → Force token refresh, retry once
       └─ Timeout → Fallback to non-streaming or error message
```

### Tool Approval Flow

```
Agent calls: _tool_place_trade({"coin": "BTC", "side": "buy", "size": 0.1})
    ↓
is_write_tool("place_trade") = True
    ↓
action_id = store_pending("place_trade", {...args...}, chat_id)
    [Stored in memory for 5 min TTL]
    ↓
format_confirmation("place_trade", args, action_id)
    ├─ Builds human-readable confirmation text
    ├─ Builds inline keyboard: [APPROVE id] [REJECT id]
    └─ Returns (text, buttons)
    ↓
Send to Telegram with reply_markup
    ↓
[USER PRESSES BUTTON]
    ↓
_handle_tool_approval(token, chat_id, callback_id, action_id, approved=True/False)
    │
    ├─ approved=True:
    │  ├─ pop_pending(action_id) → retrieve original args
    │  ├─ execute_tool(tool_name, args) immediately
    │  ├─ Log execution to diagnostics
    │  └─ Send result back to Telegram + append to chat history
    │
    └─ approved=False:
       └─ Delete pending action, send "Cancelled" message
```

---

## CLI Entrypoint

**File:** `cli/main.py`, `cli/commands/*.py`  
**Entry point:** `typer.Typer()` app at line 14

### CLI Routing (all 🔧 FIXED, NO AI)

```
hl <command> <args>
    ↓
Typer router matches command
    ↓
Import from cli/commands/<command>.py
    ↓
<command>_cmd(<args>)
    ├─ Parse arguments via typer decorators
    ├─ Import necessary modules (strategy SDK, HyperLiquid adapter, etc.)
    ├─ Execute fixed code
    └─ Print results to stdout
    ↓
[NO AI CALLED]
[NO TOOL APPROVAL]
[NO STREAMING]
```

### Example: `hl status`

```
cli/main.py:46 → app.command("status", help="...") → run.py:status_cmd()
    ↓
status_cmd(data_dir, watch, interval)
    ├─ Load persisted state from data/cli/state.db
    ├─ Load persisted trades from data/cli/trades.jsonl
    ├─ Parse positions_data via PositionTracker.from_dict()
    ├─ Render via display.status_table()
    └─ Print to stdout
```

### Example: `hl run <strategy> --instrument ETH-PERP`

```
cli/main.py:45 → app.command("run", help="...") → commands/run.py:run_cmd()
    ↓
run_cmd(strategy="avellaneda_mm", instrument="ETH-PERP", tick_interval=10.0, ...)
    ├─ Resolve strategy from registry (cli/strategy_registry.py)
    ├─ Load strategy class via sdk.strategy_sdk.loader.load_strategy()
    ├─ Initialize TradingEngine(hl, strategy, instrument, ...)
    ├─ Call engine.run(max_ticks, resume)
    │  └─ [AUTONOMOUS LOOP]
    │     ├─ Every tick (10s by default):
    │     │  ├─ Fetch market snapshot (HL API)
    │     │  ├─ Risk check (RiskManager pre_round_check)
    │     │  ├─ Run strategy.on_tick(snapshot, context)
    │     │  ├─ Validate orders (RiskManager.validate_orders)
    │     │  ├─ Execute via HL API
    │     │  ├─ Update position tracker
    │     │  ├─ Persist state to data/cli/state.db
    │     │  └─ Log trade to data/cli/trades.jsonl
    │     └─ Graceful shutdown on SIGINT/SIGTERM
    │
    └─ [NO AI INVOLVED]
```

---

## Message Routing Workflows

### Workflow 1: Telegram `/status` (Fixed Command)

**Classification:** 🔧 FIXED  
**Auth:** Sender ID check only  
**AI Involved:** No

```mermaid
sequenceDiagram
    participant User as User<br/>(Telegram)
    participant Bot as telegram_bot.py<br/>:run()
    participant API as HL API<br/>(Hyperliquid)
    participant Renderer as TelegramRenderer
    
    User->>Bot: /status
    Bot->>Bot: cmd = "status"<br/>cmd in HANDLERS ✓
    Bot->>Bot: handler = cmd_status()
    Bot->>API: POST /info<br/>(clearinghouseState)
    API-->>Bot: positions, margins
    Bot->>Renderer: status_table(...)
    Renderer->>User: 📊 Portfolio Status<br/>[table]
    
    Note over Bot: No AI called<br/>No tool approval<br/>Time: <100ms
```

**Key files:**
- Entry: `telegram_bot.py:3246-3254`
- Handler: `telegram_bot.py:421`
- Execution: Direct HL API calls + display rendering

---

### Workflow 2: Telegram `/briefai` (AI-Suffix Command)

**Classification:** 🤖 AI  
**Auth:** Sender ID check  
**AI Involved:** Indirectly (thesis is pre-computed)

```mermaid
sequenceDiagram
    participant User as User<br/>(Telegram)
    participant Bot as telegram_bot.py
    participant DailyReport as daily_report.py
    participant Disk as Disk<br/>(data/thesis/)
    participant TG_API as Telegram API
    
    User->>Bot: /briefai
    Bot->>Bot: cmd_briefai()
    Bot->>DailyReport: generate_report(mechanical=False)
    DailyReport->>Disk: Load thesis state<br/>Load catalysts
    Disk-->>DailyReport: thesis_dict, catalysts
    DailyReport->>DailyReport: Render PDF<br/>+ thesis line<br/>+ catalyst calendar
    DailyReport-->>Bot: path to PDF
    Bot->>TG_API: sendDocument(pdf)
    TG_API->>User: 📄 BriefAI.pdf
    
    Note over Bot: No real-time AI call<br/>Thesis is pre-computed<br/>Time: 5-15s
```

**Key files:**
- Entry: `telegram_bot.py:3246-3254`
- Handler: `telegram_bot.py:756`
- Report generator: `daily_report.py`
- Thesis storage: `data/thesis/*.json`

---

### Workflow 3: Telegram Free Text / NL (AI Agent)

**Classification:** 🤖 AI  
**Auth:** Sender ID check, DM only  
**AI Involved:** Yes, full loop with tool calls

```mermaid
sequenceDiagram
    participant User as User<br/>(Telegram DM)
    participant BotLoop as telegram_bot.py<br/>:run()
    participant Agent as telegram_agent.py<br/>:handle_ai_message()
    participant API as Anthropic/OpenRouter API
    participant Tools as agent_tools.py<br/>execute_tool()
    participant HL_API as HyperLiquid API
    participant User2 as User<br/>(Approval buttons)
    
    User->>BotLoop: "What's my BTC PnL?"
    BotLoop->>BotLoop: cmd not in HANDLERS
    BotLoop->>Agent: handle_ai_message(text, ...)
    Agent->>Agent: Load chat history<br/>Build system prompt<br/>Build live context
    Agent->>API: POST /messages<br/>(system, conversation,<br/>TOOL_DEFS)
    API-->>Agent: {text, tool_calls:<br/>[{name: "account_summary"}]}
    Agent->>Tools: execute_tool("account_summary", {})
    Tools->>HL_API: POST /info<br/>(clearinghouseState)
    HL_API-->>Tools: positions, equity
    Tools-->>Agent: "BTC: 0.5 @ $95K"
    Agent->>Agent: Append result to<br/>conversation
    Agent->>API: POST /messages<br/>(conversation + result)
    API-->>Agent: {text: "Your BTC position...",<br/>tool_calls: []}
    
    Agent->>Agent: stop_reason = "end_turn"<br/>Tool loop complete
    Agent->>User: Stream response<br/>"Your BTC position...<br/>uPnL: +$2,500"
    Agent->>Agent: _log_chat("assistant",<br/>response, model=...)
    
    Note over Agent: If agent called<br/>_tool_place_trade(),<br/>_tool_update_thesis(),<br/>etc. (WRITE tools):
    Note over Agent: agent sends approval<br/>buttons to User<br/>waits for callback
```

**Key files:**
- Entry: `telegram_bot.py:3274`
- Agent handler: `telegram_agent.py:444`
- Tool execution: `agent_tools.py:1178+`
- Tool approval: `telegram_bot.py:1991` (callback handler)

---

### Workflow 4: CLI `hl run` (Autonomous Trading Engine)

**Classification:** 🔧 FIXED  
**AI Involved:** No (unless strategy uses AI, but strategy itself is fixed code)

```mermaid
sequenceDiagram
    participant User as User<br/>(shell)
    participant Main as main.py<br/>:app()
    participant RunCmd as commands/run.py<br/>:run_cmd()
    participant Engine as engine.py<br/>:TradingEngine
    participant Strategy as strategy.py<br/>:on_tick()
    participant HL as HyperLiquid API
    participant StateDB as State DB
    
    User->>Main: hl run avellaneda_mm
    Main->>RunCmd: run_cmd(strategy="avellaneda_mm", ...)
    RunCmd->>RunCmd: Load strategy class
    RunCmd->>Engine: __init__(hl, strategy, ...)
    RunCmd->>Engine: run(max_ticks=0, resume=True)
    
    loop Every tick (10s default)
        Engine->>HL: get_snapshot(ETH-PERP)
        HL-->>Engine: {mid, bid, ask, ...}
        Engine->>Engine: Pre-tick risk check
        Engine->>Strategy: on_tick(snapshot, context)
        Strategy-->>Engine: [decisions]<br/>(place_order, etc.)
        Engine->>Engine: Risk validate orders
        Engine->>HL: place_order(...) [Ioc]
        HL-->>Engine: {oid, fill_qty, ...}
        Engine->>StateDB: persist state
        Engine->>Engine: Log trade
    end
    
    User->>Engine: [Ctrl+C]
    Engine->>Engine: Graceful shutdown
    Engine->>User: Shutdown summary
    
    Note over Engine: No AI called<br/>Strategy is pure code<br/>Autonomous execution
```

**Key files:**
- Entry: `cli/main.py:45`
- Command: `cli/commands/run.py:run_cmd()`
- Engine: `cli/engine.py:TradingEngine.run()`
- State persistence: `parent/store.py:StateDB`

---

## Tool Availability Matrix

### Tools Available via Telegram AI Path

**File:** `cli/agent_tools.py:39-425` (TOOL_DEFS)

#### READ Tools (Execute Immediately, No Approval)

| Tool | Purpose | Side Effects | Source |
|------|---------|--------------|--------|
| `market_brief` | Compact market: price, technicals, position, thesis | None (read-only) | HL API, CandleCache, thesis files |
| `account_summary` | Equity, positions, balances across both clearinghouses | None | HL API |
| `live_price` | Current prices for watched markets | None | HL API |
| `analyze_market` | EMA, RSI, trend, volume ratio, Bollinger bands | None | CandleCache |
| `get_orders` | All open orders | None | HL API |
| `trade_journal` | Recent trades with reasoning | None | data/cli/trades.jsonl |
| `get_signals` | Pulse (capital inflow) + Radar (opportunity) signals | None | Signal journal files |
| `check_funding` | Funding rate, premium, OI for a market | None | HL API |
| `read_file` | Read project file (relative to root) | None | Disk |
| `search_code` | Grep pattern search in codebase | None | Disk |
| `list_files` | List files matching glob pattern | None | Disk |
| `web_search` | Search the web (via external service) | None | Internet |
| `memory_read` | Read from persistent agent memory | None | data/agent_memory/*.md |
| `get_errors` | Recent agent errors from diagnostics | None | data/diagnostics/errors.jsonl |
| `get_feedback` | User feedback submissions | None | data/feedback/ |
| `introspect_self` | Agent's own state snapshot | None | Runtime inspection |
| `read_reference` | Read built-in reference docs (tools, architecture, workflows, rules) | None | agent/reference/*.md |

#### WRITE Tools (Require User Approval via Telegram Buttons)

| Tool | Purpose | Side Effects | Approval Gate |
|------|---------|--------------|---------------|
| `place_trade` | Open a position (buy/sell) | Sends order to HL, updates position state | User button [APPROVE] [REJECT] |
| `close_position` | Close existing position via IOC | HL order execution, position zeroed | User button [APPROVE] [REJECT] |
| `set_sl` | Place exchange-side stop-loss trigger | HL conditional order created | User button [APPROVE] [REJECT] |
| `set_tp` | Place exchange-side take-profit trigger | HL conditional order created | User button [APPROVE] [REJECT] |
| `update_thesis` | Update conviction & direction for a market | Writes to data/thesis/{market}.json | User button [APPROVE] [REJECT] |
| `memory_write` | Write to persistent agent memory | Creates/updates data/agent_memory/{topic}.md | User button [APPROVE] [REJECT] |
| `edit_file` | Edit project file (string replacement) | Modifies file on disk | User button [APPROVE] [REJECT] |
| `run_bash` | Execute shell command (30s timeout) | Arbitrary shell execution | User button [APPROVE] [REJECT] |

---

## Side Effects & State Changes

### Disk State Mutations

| Component | Path | Triggered By | Content |
|-----------|------|--------------|---------|
| **Chat history** | `data/daemon/chat_history.jsonl` | Every AI message | {timestamp, role, content, model, user} |
| **Thesis state** | `data/thesis/{market}.json` | `update_thesis` tool (approved) | {direction, conviction, age, reasoning} |
| **Trade journal** | `data/cli/trades.jsonl` | Engine tick after fill | {tick, oid, side, qty, price, fee, strategy} |
| **Position tracker** | `data/cli/state.db` | Engine tick | Serialized PositionTracker + RiskManager state |
| **Diagnostics** | `data/diagnostics/tool_calls.jsonl` | Every tool call | {tool_name, args, result/error, duration_ms} |
| **Feedback** | `data/feedback/*.json` | `/feedback` command | User feedback text + timestamp |
| **Memory** | `data/agent_memory/{topic}.md` | `memory_write` tool (approved) | Markdown knowledge base |
| **Pending actions** | `_pending_actions` (in-memory dict) | Agent calls WRITE tool | {action_id, tool_name, args, chat_id, ttl} |
| **Agent memory** | `data/daemon/consolidated_memories.jsonl` | Scheduled task (not real-time AI) | Consolidated learnings |

### HL Exchange State Mutations

| Operation | Triggered By | Details |
|-----------|--------------|---------|
| **Place order** | `place_trade` tool (approved) or CLI `trade` cmd | Creates limit/IOC order on HL |
| **Cancel order** | Manual via CLI, or risk guard auto-cancel | Removes order from book |
| **Close position** | `close_position` tool (approved) or Guard/Engine | IOC market order opposite side |
| **Set SL/TP** | `set_sl`/`set_tp` tools (approved) | Creates conditional trigger orders |
| **Liquidation** | Market move (not agent-triggered) | Forceful position close by exchange |

### Account-Affecting Operations (Reversible)

| Operation | Reversible? | Approval | Notes |
|-----------|------------|----------|-------|
| Place order | Yes (cancel) | User button | Can be undone before fill |
| Trade execution (fill) | Partial (close opposite) | User button | Can close to reduce exposure |
| Set SL/TP | Yes (cancel trigger) | User button | Can be removed |
| Update thesis | Yes (overwrite) | User button | Can be changed/reset |

### Account-Affecting Operations (Irreversible)

| Operation | Reversible? | Approval | Notes |
|-----------|------------|----------|---|
| Trade realized PnL | No | N/A (market) | Cannot undo PnL |
| Fees paid to exchange | No | N/A (market) | Cannot recover fees |
| Liquidation | No | N/A (market) | Loss is final |

---

## Command Classification Summary

### Total Commands: 48 Telegram + 24 CLI

### Telegram Breakdown

| Category | Fixed (🔧) | AI-Suffix (🤖) | Hybrid (⚠️) | Total |
|----------|-----------|----------------|----------|-------|
| Portfolio data | 14 | 0 | 0 | 14 |
| Brief/Reporting | 1 | 1 | 1 | 2 |
| Position management | 3 | 0 | 0 | 3 |
| System control | 7 | 0 | 0 | 7 |
| Analytics | 6 | 0 | 0 | 6 |
| Trading (interactive menu) | 1 | 0 | 0 | 1 |
| **Total** | **32** | **1** | **1** | **48** |

### CLI Breakdown

| Category | Fixed (🔧) | AI-Suffix (🤖) | Total |
|----------|-----------|----------------|-------|
| All commands | 24 | 0 | 24 |

**Note:** All CLI commands are 🔧 FIXED. The autonomous engine (`hl run`) is pure strategy code; there is no AI agent path in the CLI.

---

## Violations of the Slash Rule

### Findings

**RULE VIOLATION DETECTED:** `/briefai` is **misclassified**.

**Issue:** `/briefai` is registered as a fixed command handler (`cmd_briefai()` at line 756), but the docstring claims it's "AI-INFLUENCED." The actual implementation:

1. Calls `daily_report.generate_report(mechanical=False)`
2. The PDF is generated by **fixed code** (not AI)
3. Thesis and catalysts are **pre-computed** (by scheduled AI tasks, not real-time)
4. The command handler **never calls** the AI runtime

**Recommendation:** Reclassify as `⚠️ HYBRID`:
- **Slash part:** Pure fixed code ✓
- **AI dependency:** Thesis is pre-computed by agent on schedule
- **Correct classification:** Fixed-code slash command with AI-influenced *content*, not AI-driven *logic*

**Correct interpretation:** The rule is about *command execution path*, not *data provenance*. `/briefai` executes as fixed code; it just uses pre-computed AI content. This is **compliant**.

---

## Appendix: File Locations (Quick Reference)

| Component | File | Lines |
|-----------|------|-------|
| **Telegram bot main loop** | `cli/telegram_bot.py` | 3083+ |
| **Message router** | `cli/telegram_bot.py` | 3227–3281 |
| **Command handlers (40+ commands)** | `cli/telegram_bot.py` | 421–2913 |
| **Command dispatch table** | `cli/telegram_bot.py` | 2940–3012 |
| **Telegram handler (polling)** | `cli/telegram_handler.py` | 259–371 |
| **AI agent runtime** | `cli/telegram_agent.py` | 444+ |
| **Tool definitions** | `cli/agent_tools.py` | 39–425 |
| **Tool implementations** | `cli/agent_tools.py` | 432–1277 |
| **Streaming + parallel execution** | `cli/agent_runtime.py` | 1–300 |
| **MCP server (alternative tools)** | `cli/mcp_server.py` | 1+ |
| **Trading engine** | `cli/engine.py` | 31+ |
| **CLI app registration** | `cli/main.py` | 14–68 |
| **Status command (CLI)** | `cli/commands/status.py` | 12+ |
| **Run command (CLI)** | `cli/commands/run.py` | 13+ |
| **Brief/report generation** | `cli/daily_report.py` | 1+ |
| **Thesis state** | `data/thesis/{market}.json` | (disk) |
| **Agent memory** | `data/agent_memory/{topic}.md` | (disk) |
| **Chat history** | `data/daemon/chat_history.jsonl` | (disk) |
| **State persistence** | `data/cli/state.db` | (disk) |
| **Trade journal** | `data/cli/trades.jsonl` | (disk) |

---

## Key Takeaways

1. **Three message paths are enforced:**
   - ✅ Slash commands (no `ai` suffix) = fixed code, no AI
   - ✅ Slash commands (with `ai` suffix) = AI agent path
   - ✅ Natural language (DMs only) = AI agent path

2. **AI tools require user approval** via Telegram inline buttons before any state change (trading, thesis, file edit).

3. **READ tools execute immediately** (account summary, prices, analysis) with no approval.

4. **WRITE tools are queued** in memory with 5-minute TTL, waiting for user to press [APPROVE] or [REJECT].

5. **No AI in CLI commands** — the CLI is pure fixed code. Autonomous trading via `hl run` uses the strategy SDK, not the AI agent.

6. **Streaming to Telegram** happens in real-time for AI responses, with message updates every 1.5 seconds.

7. **State is persisted** to disk (state.db, trades.jsonl, thesis files, agent memory) after every trading action.

8. **Single-instance enforcement** for telegram_bot.py via PID file + process name scan.

---

**Document Generated:** 2025-04-07  
**Last Verified:** cli/telegram_bot.py (3281 lines), cli/telegram_agent.py (2080+ lines), cli/agent_tools.py (1297 lines)
