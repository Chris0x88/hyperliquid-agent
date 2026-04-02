# HyperLiquid Trading System — Architecture v3

*Updated 2026-04-02. v1: daemon-centric. v2: interface-first. v3: agentic tool-calling.*

## Changelog

| Version | Date | Shift |
|---------|------|-------|
| v1 | 2026-03 | Daemon with 19 iterators, REFLECT pipeline, 4-phase plan |
| v2 | 2026-04-02 AM | Interface-first: rich context, model selector, formatting overhaul |
| v3 | 2026-04-02 PM | Agentic: 9 tools (7 read, 2 write), dual-mode calling, approval gates |

## System Overview

```mermaid
graph TB
    subgraph HUMAN["👤 Chris"]
        CC["Claude Code (Opus)<br/>Writes thesis, builds system"]
        TG["📱 Telegram<br/>25 commands + AI chat"]
    end

    subgraph EXCHANGE["🏦 HyperLiquid Exchange"]
        HL_API["REST API /info<br/>allMids, clearinghouseState<br/>metaAndAssetCtxs"]
        HL_TRADE["Trading API<br/>Orders, leverage, stops"]
        MAIN["Main 0x80B5<br/>Oil, Gold, Silver (xyz)"]
        VAULT["Vault 0x9da9<br/>BTC Power Law"]
    end

    subgraph BOT["⚙️ Telegram Bot (telegram_bot.py)"]
        POLL["Polling Loop<br/>2s interval, single-instance"]
        HANDLERS["25 Command Handlers<br/>/status /price /chart /models<br/>/memory /orders /pnl ..."]
        CALLBACKS["Callback Handler<br/>model: approve: reject:"]
    end

    subgraph AGENT["🤖 AI Agent (telegram_agent.py)"]
        HANDLE["handle_ai_message()<br/>Tool-calling loop (max 3)"]
        SYSPROMPT["System Prompt<br/>AGENT.md + SOUL.md"]
        CONTEXT["Live Context Builder<br/>_build_live_context()"]
        HISTORY["Chat History<br/>sanitized, last 20 msgs"]
        OR_API["OpenRouter API<br/>429 retry, required headers"]
    end

    subgraph TOOLS["🔧 Agent Tools (agent_tools.py)"]
        subgraph READ_TOOLS["READ — auto-execute"]
            T1["market_brief<br/>deep market analysis"]
            T2["account_summary<br/>equity + positions"]
            T3["live_price<br/>current prices"]
            T4["analyze_market<br/>full technicals"]
            T5["get_orders<br/>open orders"]
            T6["trade_journal<br/>trade history"]
            T7["check_funding<br/>funding, OI, volume"]
        end
        subgraph WRITE_TOOLS["WRITE — require approval"]
            T8["place_trade<br/>⚠️ inline keyboard"]
            T9["update_thesis<br/>⚠️ inline keyboard"]
        end
        PENDING["Pending Actions<br/>in-memory, 5min TTL"]
    end

    subgraph CONTEXT_PIPE["📊 Context Pipeline"]
        ACCT["Account + Positions<br/>both clearinghouses"]
        SNAP["Market Snapshots<br/>trend, S/R, ATR, BBands<br/>volume POC, flags"]
        THESIS_D["Thesis Data<br/>conviction, direction, TP/SL"]
        MEM["Memory + Learnings<br/>SQLite events, summaries"]
        HARNESS["Context Harness<br/>3000 token budget<br/>relevance-scored tiers"]
    end

    subgraph MODELS_SEL["🤖 Model Selection"]
        MODEL_CFG["data/config/model_config.json"]
        CURATED["18 curated models<br/>10 free + 8 paid"]
        OR_MODELS["models.json merge"]
    end

    subgraph RUNTIME["⚙️ Other Processes"]
        HB["Heartbeat<br/>launchd 2min<br/>Stops, alerts, escalation"]
        VR["Vault Rebalancer<br/>launchd hourly"]
    end

    subgraph DATA["📁 Shared State (filesystem)"]
        THESIS_F["data/thesis/*.json"]
        WORKING["data/memory/working_state.json"]
        MEMORY_DB["data/memory/memory.db"]
        HISTORY_F["data/daemon/chat_history.jsonl"]
        CANDLE_DB["data/candles/candle_cache.db"]
    end

    subgraph LIBS["📚 Shared Libraries"]
        LIB_CTX["common/context_harness"]
        LIB_SNAP["common/market_snapshot"]
        LIB_THESIS["common/thesis"]
        LIB_MEM["common/memory_consolidator"]
        LIB_ACCT["common/account_resolver"]
        LIB_CANDLE["modules/candle_cache"]
        LIB_PROXY["parent/hl_proxy"]
    end

    %% Human → Bot
    CC -->|writes| THESIS_F
    TG <-->|commands| POLL
    POLL --> HANDLERS
    POLL --> CALLBACKS

    %% Bot → Agent
    POLL -->|free text| HANDLE

    %% Agent internals
    HANDLE --> SYSPROMPT
    HANDLE --> CONTEXT
    HANDLE --> HISTORY
    HANDLE -->|messages + tools| OR_API

    %% Tool calling (dual-mode)
    OR_API -->|"native tool_calls<br/>(paid models)"| HANDLE
    OR_API -->|"[TOOL: name {args}]<br/>(free models)"| HANDLE
    HANDLE -->|READ tools| READ_TOOLS
    HANDLE -->|WRITE tools| PENDING
    PENDING -->|"[Approve] [Reject]"| CALLBACKS
    CALLBACKS -->|approved| WRITE_TOOLS

    %% Context pipeline
    CONTEXT --> ACCT
    CONTEXT --> SNAP
    CONTEXT --> THESIS_D
    CONTEXT --> HARNESS
    HARNESS --> MEM

    %% Tools → Libraries
    T1 --> LIB_CTX
    T2 --> LIB_ACCT
    T3 --> LIB_PROXY
    T4 --> LIB_SNAP
    T4 --> LIB_CANDLE
    T7 --> LIB_PROXY
    T8 --> LIB_PROXY
    T9 --> LIB_THESIS

    %% Libraries → Exchange
    LIB_PROXY --> HL_API
    LIB_PROXY --> HL_TRADE
    LIB_CANDLE --> CANDLE_DB
    LIB_MEM --> MEMORY_DB
    LIB_THESIS --> THESIS_F

    %% Context pipeline → Data
    ACCT --> HL_API
    SNAP --> LIB_CANDLE
    SNAP --> LIB_SNAP
    THESIS_D --> THESIS_F
    MEM --> MEMORY_DB
    HISTORY --> HISTORY_F

    %% Model selection
    OR_API --> MODEL_CFG
    MODEL_CFG --> CURATED
    CURATED --> OR_MODELS

    %% Other processes
    HB -->|fetches| HL_API
    HB -->|reads| THESIS_F
    HB -->|places stops| HL_TRADE
    HB -->|alerts| TG
    VR -->|trades| HL_TRADE

    %% Handlers → Exchange
    HANDLERS -->|fetches| HL_API

    %% Styling
    classDef running fill:#2d5a2d,stroke:#4a4,color:#fff
    classDef tools fill:#2d4a5a,stroke:#48a,color:#fff
    classDef write fill:#5a2d2d,stroke:#a44,color:#fff
    classDef data fill:#5a4a2d,stroke:#a84,color:#fff
    classDef libs fill:#3a3a5a,stroke:#66a,color:#fff

    class POLL,HANDLERS,CALLBACKS,HANDLE,CONTEXT,OR_API,HB,VR running
    class T1,T2,T3,T4,T5,T6,T7 tools
    class T8,T9,PENDING write
    class THESIS_F,WORKING,MEMORY_DB,HISTORY_F,CANDLE_DB,MODEL_CFG data
    class LIB_CTX,LIB_SNAP,LIB_THESIS,LIB_MEM,LIB_ACCT,LIB_CANDLE,LIB_PROXY libs
```

## Tool-Calling Architecture (NEW in v3)

```mermaid
sequenceDiagram
    participant U as 👤 Chris (Telegram)
    participant B as telegram_bot.py
    participant A as telegram_agent.py
    participant OR as OpenRouter API
    participant T as agent_tools.py
    participant HL as HyperLiquid API

    U->>B: "analyze oil technicals"
    B->>A: handle_ai_message()

    Note over A: Build system prompt + live context<br/>+ chat history + TOOL_DEFS

    A->>OR: messages + tools (9 definitions)

    alt Paid model (native function calling)
        OR-->>A: tool_calls: [analyze_market({coin: "xyz:BRENTOIL"})]
    else Free model (text-based)
        OR-->>A: "Let me check...[TOOL: analyze_market {\"coin\": \"xyz:BRENTOIL\"}]"
        Note over A: _parse_text_tool_calls() extracts tool call
    end

    A->>T: execute_tool("analyze_market", {coin: "xyz:BRENTOIL"})
    T->>HL: Fetch candles, compute technicals
    HL-->>T: OHLCV data
    T-->>A: "=== xyz:BRENTOIL @ 108.1 ===\nFLAGS: above_vwap...\nSUPPORT: ..."

    Note over A: Append tool result, re-call OpenRouter

    A->>OR: messages + tool result + tools
    OR-->>A: "🛢️ Oil is trading at $108.10 above VWAP..."
    A->>B: Send formatted response
    B->>U: Telegram message with analysis
```

```mermaid
sequenceDiagram
    participant U as 👤 Chris (Telegram)
    participant B as telegram_bot.py
    participant A as telegram_agent.py
    participant OR as OpenRouter API
    participant T as agent_tools.py
    participant HL as HyperLiquid API

    U->>B: "go long 1 oil"
    B->>A: handle_ai_message()
    A->>OR: messages + tools
    OR-->>A: tool_calls: [place_trade({coin: "BRENTOIL", side: "buy", size: 1.0})]

    Note over A: WRITE tool detected → store pending

    A->>T: store_pending("place_trade", args)
    T-->>A: action_id: "abc12345"
    A->>B: tg_send_buttons("Confirm: BUY 1.0 BRENTOIL", [Approve, Reject])
    B->>U: ⚠️ Confirm Trade<br/>BUY 1.0 BRENTOIL<br/>[✅ Approve] [❌ Reject]

    A->>OR: messages + "awaiting approval"
    OR-->>A: "I've sent a confirmation..."
    A->>U: "Trade confirmation sent. Tap to approve."

    alt User taps Approve
        U->>B: callback: approve:abc12345
        B->>T: pop_pending("abc12345")
        T->>T: execute_tool("place_trade", args)
        T->>HL: Market order BUY 1.0 BRENTOIL
        HL-->>T: Order filled
        T-->>B: "Trade executed: BUY 1.0 BRENTOIL"
        B->>U: ✅ place_trade — Trade executed
    else User taps Reject
        U->>B: callback: reject:abc12345
        B->>U: ❌ Action rejected.
    end
```

## Dual-Mode Tool Calling

The system supports two tool invocation paths, chosen automatically:

```mermaid
graph LR
    MSG["User Message"] --> OR["OpenRouter API<br/>(tools param always sent)"]

    OR -->|"finish_reason: tool_calls<br/>(Claude, GPT, Gemini)"| NATIVE["Native Function Calling<br/>Structured tool_calls array"]
    OR -->|"finish_reason: stop<br/>(Step 3.5, Qwen, Llama)"| TEXT["Text Response"]

    TEXT --> PARSE["_parse_text_tool_calls()<br/>Regex: [TOOL: name {args}]"]
    PARSE -->|"matches found"| EXEC
    PARSE -->|"no matches"| DIRECT["Direct text response<br/>(context-only mode)"]

    NATIVE --> EXEC["execute_tool()"]
    EXEC --> RESULT["Tool result → re-call OpenRouter"]

    classDef native fill:#2d5a2d,stroke:#4a4,color:#fff
    classDef text fill:#2d4a5a,stroke:#48a,color:#fff
    classDef fallback fill:#5a4a2d,stroke:#a84,color:#fff

    class NATIVE native
    class TEXT,PARSE text
    class DIRECT fallback
```

## AI Context Pipeline

Every message triggers a fresh context build (~450 tokens):

```mermaid
graph TD
    subgraph FETCH["Data Fetching"]
        F1["HL API: clearinghouseState<br/>(native + xyz)"]
        F2["HL API: allMids<br/>(native + xyz)"]
        F3["CandleCache: OHLCV<br/>(SQLite persistent)"]
        F4["Thesis files<br/>(data/thesis/*.json)"]
        F5["Memory DB<br/>(events, learnings, summaries)"]
        F6["Working State<br/>(escalation, ATR cache)"]
    end

    subgraph BUILD["Context Assembly"]
        B1["_fetch_account_state_for_harness()<br/>equity + positions"]
        B2["_fetch_market_snapshots()<br/>build_snapshot + render_snapshot<br/>+ thesis data injection"]
        B3["build_multi_market_context()<br/>relevance-scored, 3000t budget"]
    end

    subgraph OUTPUT["Injected Context"]
        O1["ACCOUNT: equity + positions"]
        O2["TIME: day, session, UTC"]
        O3["SNAPSHOT: flags, S/R, ATR, BBands"]
        O4["THESIS: conviction, direction, TP/SL"]
        O5["MEMORY: recent events + learnings"]
    end

    F1 --> B1
    F2 --> B2
    F3 --> B2
    F4 --> B2
    F5 --> B3
    F6 --> B1

    B1 --> B3
    B2 --> B3

    B3 --> O1
    B3 --> O2
    B3 --> O3
    B3 --> O4
    B3 --> O5

    classDef fetch fill:#2d4a5a,stroke:#48a,color:#fff
    classDef build fill:#5a4a2d,stroke:#a84,color:#fff
    classDef output fill:#2d5a2d,stroke:#4a4,color:#fff

    class F1,F2,F3,F4,F5,F6 fetch
    class B1,B2,B3 build
    class O1,O2,O3,O4,O5 output
```

## Telegram Command & Callback Architecture

```mermaid
graph TD
    subgraph POLL["Polling Loop (2s)"]
        UPD["tg_get_updates()"]
    end

    UPD -->|"callback_query"| CB_ROUTER{"Callback Router"}
    UPD -->|"message"| MSG_ROUTER{"Message Router"}

    CB_ROUTER -->|"model:*"| MODEL_CB["_handle_model_callback()<br/>Switch AI model"]
    CB_ROUTER -->|"approve:*"| APPROVE_CB["_handle_tool_approval()<br/>Execute pending tool"]
    CB_ROUTER -->|"reject:*"| REJECT_CB["_handle_tool_approval()<br/>Discard pending tool"]

    MSG_ROUTER -->|"/command"| CMD_DISPATCH{"HANDLERS dict<br/>(25 commands)"}
    MSG_ROUTER -->|"/chart*"| CHART_REWRITE["Dynamic chart shorthand<br/>/chartoil → /chart oil"]
    MSG_ROUTER -->|"free text"| AI_HANDLER["handle_ai_message()<br/>Tool-calling loop"]

    CMD_DISPATCH --> FIXED["Fixed Handlers<br/>Zero AI cost<br/>Direct HL API"]

    subgraph INLINE_KB["Inline Keyboards"]
        KB_MODELS["/models<br/>10 free + 8 paid buttons"]
        KB_TRADE["Trade confirmation<br/>[✅ Approve] [❌ Reject]"]
        KB_THESIS["Thesis confirmation<br/>[✅ Approve] [❌ Reject]"]
    end

    MODEL_CB --> KB_MODELS
    APPROVE_CB --> KB_TRADE
    APPROVE_CB --> KB_THESIS

    classDef router fill:#5a4a2d,stroke:#a84,color:#fff
    classDef handler fill:#2d5a2d,stroke:#4a4,color:#fff
    classDef kb fill:#2d4a5a,stroke:#48a,color:#fff

    class CB_ROUTER,MSG_ROUTER,CMD_DISPATCH router
    class MODEL_CB,APPROVE_CB,REJECT_CB,FIXED,AI_HANDLER,CHART_REWRITE handler
    class KB_MODELS,KB_TRADE,KB_THESIS kb
```

## Process Architecture

```mermaid
graph LR
    subgraph LAUNCHD["macOS launchd"]
        L1["com.hyperliquid.heartbeat<br/>every 2 min"]
        L2["com.hyperliquid.rebalancer<br/>every 60 min"]
    end

    subgraph BACKGROUND["Background Processes"]
        P1["telegram_bot.py<br/>PID: data/daemon/telegram_bot.pid<br/>Single-instance (pgrep + PID)"]
    end

    L1 --> HB["common/heartbeat.py<br/>Fetch positions → check stops<br/>→ escalation → alerts"]
    L2 --> VR["scripts/run_vault_rebalancer.py<br/>Power Law bands → rebalance"]
    P1 --> BOT["Polling + dispatch<br/>25 handlers + AI router"]

    HB -->|"alerts"| TG_ALERTS["📱 Alert Board<br/>(one-way)"]
    BOT <-->|"commands + AI"| TG_CMD["📱 Commands Bot<br/>(two-way)"]

    classDef process fill:#2d5a2d,stroke:#4a4,color:#fff
    class P1,L1,L2 process
```

## File Dependency Map

```mermaid
graph TD
    subgraph ENTRY["Entry Layer"]
        TB["cli/telegram_bot.py<br/>1800 lines<br/>25 handlers, polling, callbacks"]
        TA["cli/telegram_agent.py<br/>760 lines<br/>OpenRouter, tool loop, context"]
        AT["cli/agent_tools.py<br/>550 lines<br/>9 tools, pending store"]
    end

    subgraph COMMON_LAYER["Common Layer"]
        CH["common/context_harness.py<br/>Relevance-scored assembly"]
        MS["common/market_snapshot.py<br/>build_snapshot, render_snapshot"]
        TH["common/thesis.py<br/>ThesisState dataclass"]
        AR["common/account_resolver.py<br/>Wallet resolution"]
        MC["common/memory_consolidator.py<br/>Event compression"]
        MM["common/memory.py<br/>SQLite 6-table store"]
        DG["common/diagnostics.py<br/>Tool call logging"]
        HB_C["common/heartbeat.py<br/>2-min monitoring"]
    end

    subgraph MODULE_LAYER["Module Layer"]
        CC_M["modules/candle_cache.py<br/>OHLCV SQLite cache"]
    end

    subgraph PARENT_LAYER["Parent Layer"]
        HP["parent/hl_proxy.py<br/>17 importers<br/>Exchange API wrapper"]
    end

    TB -->|"routes AI"| TA
    TB -->|"approval callbacks"| AT
    TA -->|"tool definitions"| AT
    TA -->|"context build"| CH
    TA -->|"snapshots"| MS
    AT -->|"market_brief"| CH
    AT -->|"analyze_market"| MS
    AT -->|"analyze_market"| CC_M
    AT -->|"account_summary"| AR
    AT -->|"update_thesis"| TH
    AT -->|"live_price, funding"| HP
    CH -->|"memory"| MC
    MC -->|"storage"| MM
    MS -->|"candles"| CC_M
    HB_C -->|"exchange"| HP
    HP -->|"REST"| HL["HL API"]

    classDef entry fill:#5a4a2d,stroke:#a84,color:#fff
    classDef common fill:#2d4a5a,stroke:#48a,color:#fff
    classDef module fill:#3a3a5a,stroke:#66a,color:#fff
    classDef parent fill:#2d5a2d,stroke:#4a4,color:#fff

    class TB,TA,AT entry
    class CH,MS,TH,AR,MC,MM,DG,HB_C common
    class CC_M module
    class HP parent
```

## OpenRouter Integration

```mermaid
graph TD
    subgraph CONFIG["Configuration"]
        KEY["API Key<br/>~/.openclaw/.../auth-profiles.json"]
        MODEL["Active Model<br/>data/config/model_config.json"]
        MODELS["Curated List<br/>10 free + 8 paid<br/>+ models.json merge"]
    end

    subgraph HEADERS["Required Headers"]
        H1["Authorization: Bearer sk-or-..."]
        H2["HTTP-Referer: https://openclaw.ai"]
        H3["X-Title: OpenClaw"]
    end

    subgraph RETRY["429 Retry Logic"]
        R1["Attempt 1 → 2s backoff"]
        R2["Attempt 2 → 4s backoff"]
        R3["Attempt 3 → 8s backoff"]
        R4["All failed → user message"]
    end

    subgraph SELECTOR["/models Command"]
        S1["Inline Keyboard Buttons"]
        S2["Free: Qwen, GPT-OSS, Nemotron..."]
        S3["Paid: Sonnet, Opus, Gemini..."]
    end

    CONFIG --> CALL["_call_openrouter()<br/>POST /chat/completions"]
    HEADERS --> CALL
    CALL -->|"200 OK"| RESPONSE["Response dict<br/>content or tool_calls"]
    CALL -->|"429"| RETRY
    RETRY -->|"retry"| CALL
    SELECTOR -->|"writes"| MODEL

    classDef config fill:#5a4a2d,stroke:#a84,color:#fff
    class KEY,MODEL,MODELS config
```

## Infrastructure Health Assessment

| Area | Status | Notes |
|------|--------|-------|
| **Import chains** | ✅ CLEAN | Zero circular deps, all lazy imports correct |
| **Orphaned files** | ✅ ZERO | Every .py file has at least one importer |
| **Data flow** | ✅ COMPLETE | User → Bot → Agent → Tools → HL API fully traced |
| **Config files** | ✅ ALL REFERENCED | 4 configs, all loaded by code |
| **Process management** | ✅ ROBUST | PID + pgrep single-instance, SIGTERM/SIGKILL |
| **Error handling** | ✅ GRACEFUL | 429 retry, tool fallback, context-only degradation |
| **Security** | ✅ LAYERED | WRITE tools gated by approval buttons, 5min TTL |
| **Test coverage** | ⚠️ GAP | agent_tools.py, telegram_agent.py untested |
| **Chat history** | ✅ SANITIZED | Stale data stripped before LLM injection |
| **Context budget** | ✅ BOUNDED | 3000 tokens, relevance-scored tiers |

## Module Inventory

| Area | Files | Key Nodes | Status |
|------|-------|-----------|--------|
| cli/commands/ | 23 | main.py | ✅ All connected |
| cli/ (bot+agent+tools) | 8 | telegram_bot.py | ✅ Running, agentic |
| cli/daemon/ | 25 | context.py (21 importers) | 🟡 Built, not running |
| modules/ | 41 | candle_cache, radar, pulse | ✅ Used by tools |
| common/ | 31 | context_harness, market_snapshot | ✅ All connected |
| parent/ | 7 | hl_proxy (17 importers) | ✅ All connected |
| execution/ | 7 | order_types | ✅ Connected |
| strategies/ | 25 | via sdk.base (32 importers) | ✅ Connected |
| openclaw/ | 10 | AGENT.md, SOUL.md | ✅ Active (direct mode) |
| **TOTAL** | **~230** | **0 orphans** | |

## Build Phases

### ✅ Phase 1: Foundation (DONE)
Heartbeat, thesis contract, conviction engine, single-instance processes.

### ✅ Phase 1.5: Agentic Interface (DONE — this session)
- 25 Telegram commands with consistent registration
- `/price` with 24h change arrows, `/models` with inline keyboards
- OpenRouter with required headers, 429 retry, 18 curated models
- Rich AI context: positions, technicals (S/R, ATR, BBands), thesis, memory
- 9 agent tools with dual-mode calling (native + text-based)
- WRITE tool approval gates via Telegram buttons
- Chat history sanitization, single-instance enforcement

### Phase 2: Daemon Switch (NEXT)
- Replace heartbeat with full daemon (19 iterators, 3 tiers)
- All existing heartbeat functionality preserved
- Add AutoResearch, Journal, MemoryConsolidation iterators
- Daemon writes thesis updates automatically

### Phase 3: REFLECT Loop
- Wire ReflectEngine into daemon
- Nightly journal review, weekly report card to Telegram
- Convergence tracking — is performance improving?

### Phase 4: Self-Improving
- Playbook accumulates what works per (instrument, signal)
- DirectionalHysteresis prevents oscillation
- Meta-evaluation suggests parameter adjustments
- Weekly REFLECT summary to Chris
