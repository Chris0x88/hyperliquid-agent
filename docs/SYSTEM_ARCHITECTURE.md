# HyperLiquid Trading System — Complete Architecture

## System Overview

```mermaid
graph TB
    subgraph HUMAN["👤 CHRIS (Human)"]
        CC["Claude Code (Opus)<br/>Manual sessions<br/>Writes thesis, reviews system"]
        TG_READ["Reads Telegram alerts"]
        TG_CMD["Sends /commands"]
        TG_CHAT["Chats with AI agent"]
    end

    subgraph EXCHANGE["🏦 HyperLiquid Exchange"]
        HL_API["HL REST API<br/>/info endpoint"]
        HL_TRADE["HL Trading API<br/>Orders, leverage, stops"]
        MAIN_ACCT["Main Account (0x80B5)<br/>Oil, Gold, Silver<br/>xyz clearinghouse"]
        VAULT_ACCT["Vault (0x9da9)<br/>BTC Power Law<br/>default clearinghouse"]
    end

    subgraph RUNTIME["⚙️ Running Processes (macOS)"]
        HB["Heartbeat<br/>launchd, every 2min<br/>common/heartbeat.py"]
        CMD_BOT["Commands Bot<br/>background process<br/>cli/telegram_bot.py"]
        VR["Vault Rebalancer<br/>launchd, hourly<br/>scripts/run_vault_rebalancer.py"]
    end

    subgraph OPENCLAW["🦞 OpenClaw Gateway"]
        GW["Gateway (localhost:18789)<br/>Routes Telegram DMs"]
        OC_AGENT["hl-trader Agent<br/>Cheap model via OpenRouter<br/>Workspace: agent-cli/openclaw/"]
        MCP["MCP Server (hl-trading)<br/>17 tools<br/>cli/mcp_server.py"]
    end

    subgraph DATA["📁 Shared State (filesystem)"]
        THESIS["data/thesis/*.json<br/>Conviction, direction, TP<br/>THE shared contract"]
        SIGNALS["data/research/signals.jsonl<br/>Trade signals log"]
        WORKING["data/memory/working_state.json<br/>ATR, prices, escalation"]
        JOURNAL_F["data/daemon/journal/<br/>Tick snapshots"]
        TRADES_F["data/research/trades/<br/>Trade records"]
        PLAYBOOK["data/apex/memory/<br/>Playbook + events"]
    end

    subgraph DAEMON_CODE["🔧 Daemon Engine (BUILT, NOT RUNNING)"]
        CLOCK["Clock Loop<br/>cli/daemon/clock.py"]
        CTX["TickContext<br/>cli/daemon/context.py"]
        subgraph ITERATORS["19 Iterators"]
            I_CONN["Connector"]
            I_ACCT["AccountCollector"]
            I_MKT["MarketStructure"]
            I_THESIS["ThesisEngine"]
            I_LIQ["Liquidity"]
            I_RISK["Risk"]
            I_XPROT["ExchangeProtection"]
            I_GUARD["Guard"]
            I_EXEC["ExecutionEngine"]
            I_REBAL["Rebalancer"]
            I_PROFIT["ProfitLock"]
            I_FUND["FundingTracker"]
            I_CAT["CatalystDeleverage"]
            I_RADAR["Radar"]
            I_PULSE["Pulse"]
            I_AUTO["AutoResearch"]
            I_JOURN["Journal"]
            I_MEM["MemoryConsolidation"]
            I_TG["Telegram"]
        end
    end

    subgraph META["📊 Meta-Evaluation (BUILT, NOT WIRED)"]
        REFLECT["ReflectEngine<br/>FIFO round-trips, win rate,<br/>PnL, fee drag, streaks"]
        CONVERGE["ConvergenceTracker<br/>Are adjustments helping?"]
        ADAPTER["ReflectAdapter<br/>Suggest config fixes"]
        HYSTER["DirectionalHysteresis<br/>Prevent oscillation"]
        JOURNAL_E["JournalEngine<br/>Trade quality, nightly review"]
        MEMORY_E["MemoryEngine<br/>Playbook, param changes"]
    end

    %% Human interactions
    CC -->|writes| THESIS
    CC -->|reviews| TRADES_F
    CC -->|reviews| PLAYBOOK
    TG_CMD --> CMD_BOT
    TG_CHAT --> GW
    TG_READ -.->|reads alerts| HB

    %% Heartbeat flow
    HB -->|fetches| HL_API
    HB -->|reads| THESIS
    HB -->|reads/writes| WORKING
    HB -->|places stops, TPs| HL_TRADE
    HB -->|alerts| TG_READ

    %% Commands Bot
    CMD_BOT -->|fetches| HL_API
    CMD_BOT -->|responds| TG_CMD

    %% Vault Rebalancer
    VR -->|trades| HL_TRADE
    VR -->|fetches| HL_API

    %% OpenClaw flow
    GW --> OC_AGENT
    OC_AGENT -->|calls| MCP
    MCP -->|fetches| HL_API
    MCP -->|reads| THESIS
    MCP -->|reads| SIGNALS

    %% Daemon (not running but designed)
    CLOCK --> CTX
    CTX --> I_CONN
    I_CONN -->|fetches| HL_API
    I_THESIS -->|reads| THESIS
    I_EXEC -->|conviction sizing| CTX
    I_REBAL -->|executes| HL_TRADE
    I_AUTO -->|writes| PLAYBOOK
    I_JOURN -->|writes| JOURNAL_F

    %% Meta-evaluation (not wired)
    REFLECT -->|analyzes| TRADES_F
    REFLECT --> CONVERGE
    CONVERGE --> ADAPTER
    ADAPTER --> HYSTER
    JOURNAL_E -->|records| JOURNAL_F
    MEMORY_E -->|accumulates| PLAYBOOK

    %% Styling
    classDef running fill:#2d5a2d,stroke:#4a4,color:#fff
    classDef built fill:#5a4a2d,stroke:#a84,color:#fff
    classDef broken fill:#5a2d2d,stroke:#a44,color:#fff
    classDef human fill:#2d4a5a,stroke:#48a,color:#fff
    classDef exchange fill:#4a2d5a,stroke:#84a,color:#fff

    class HB,CMD_BOT,VR running
    class CLOCK,CTX,I_CONN,I_ACCT,I_MKT,I_THESIS,I_LIQ,I_RISK,I_XPROT,I_GUARD,I_EXEC,I_REBAL,I_PROFIT,I_FUND,I_CAT,I_RADAR,I_PULSE,I_AUTO,I_JOURN,I_MEM,I_TG built
    class REFLECT,CONVERGE,ADAPTER,HYSTER,JOURNAL_E,MEMORY_E built
    class CC,TG_READ,TG_CMD,TG_CHAT human
    class HL_API,HL_TRADE,MAIN_ACCT,VAULT_ACCT exchange
```

## Execution Tiers

```mermaid
graph LR
    subgraph WATCH["WATCH Tier (observation only)"]
        W1["Connector"]
        W2["AccountCollector"]
        W3["MarketStructure"]
        W4["ThesisEngine"]
        W5["Liquidity"]
        W6["Risk"]
        W7["AutoResearch"]
        W8["MemoryConsolidation"]
        W9["Journal"]
        W10["Telegram"]
    end

    subgraph REBALANCE["REBALANCE Tier (+ position management)"]
        R1["ExecutionEngine<br/>Conviction → sizing"]
        R2["ExchangeProtection<br/>Liq-buffer SL"]
        R3["Guard<br/>Trailing stops"]
        R4["Rebalancer<br/>Strategy execution"]
        R5["ProfitLock<br/>Sweep 25% realized"]
        R6["FundingTracker<br/>Hourly cost accounting"]
        R7["CatalystDeleverage<br/>Pre-event risk reduction"]
    end

    subgraph OPP["OPPORTUNISTIC Tier (+ scanning)"]
        O1["Radar<br/>Setup scanner (5min)"]
        O2["Pulse<br/>Momentum detector (2min)"]
    end

    WATCH --> REBALANCE --> OPP

    classDef watch fill:#2d4a3a,stroke:#4a8,color:#fff
    classDef rebal fill:#4a3a2d,stroke:#a84,color:#fff
    classDef opp fill:#3a2d4a,stroke:#84a,color:#fff

    class W1,W2,W3,W4,W5,W6,W7,W8,W9,W10 watch
    class R1,R2,R3,R4,R5,R6,R7 rebal
    class O1,O2 opp
```

## Data Flow: The Thesis Contract

```mermaid
sequenceDiagram
    participant Chris as 👤 Chris + Claude Code
    participant Thesis as 📄 data/thesis/*.json
    participant HB as ⚙️ Heartbeat (2min)
    participant HL as 🏦 HyperLiquid
    participant TG as 📱 Telegram
    participant OC as 🦞 OpenClaw Agent

    Note over Chris,OC: THE THESIS IS THE SHARED CONTRACT

    Chris->>Thesis: Writes conviction (0.0-1.0),<br/>direction, TP, evidence

    loop Every 2 minutes
        HB->>HL: Fetch positions, equity, funding
        HB->>Thesis: Read conviction + direction

        alt Conviction > 0.5 + no position
            HB->>HL: Size entry per conviction bands
        end

        alt Thesis stale > 24h
            HB->>HB: Clamp conviction to 0.3
            HB->>TG: Alert "thesis stale"
        end

        alt Liq distance < 4%
            HB->>HL: Auto-deleverage (L2)
            HB->>TG: Alert "delevered"
        end

        alt Action taken OR escalation change
            HB->>TG: Brief action alert
        end

        alt Hourly
            HB->>TG: "$654 | L0 | BRENTOIL L50@101"
        end
    end

    OC->>Thesis: Reads current conviction
    OC->>HL: Fetches live prices via MCP
    Chris->>OC: "How's oil looking?"
    OC->>Chris: Analysis + challenges thesis

    Note over OC: Can update thesis in a pinch<br/>but Chris+Opus is primary writer
```

## Meta-Evaluation: The REFLECT Loop

```mermaid
graph TD
    TRADES["Closed Trades<br/>trades.jsonl"] --> RE["ReflectEngine<br/>Compute metrics"]

    RE --> METRICS["ReflectMetrics<br/>• Win rate, PnL, FDR<br/>• Direction bias<br/>• Holding period dist<br/>• Monster trade dependency<br/>• Strategy breakdown"]

    METRICS --> REPORT["ReflectReporter<br/>Markdown report + distill"]
    METRICS --> CT["ConvergenceTracker<br/>Is performance improving<br/>across REFLECT cycles?"]

    CT -->|converging| RA["ReflectAdapter<br/>Suggest parameter fixes"]
    CT -->|not converging| HUMAN["⚠️ Escalate to Chris<br/>Pause auto-adjustments"]

    RA --> HG["DirectionalHysteresis<br/>Require 2 consecutive<br/>same-direction before flip"]

    HG -->|approved| APPLY["Apply config adjustments<br/>• radar_score_threshold<br/>• pulse_confidence<br/>• daily_loss_limit"]

    APPLY --> MEM["MemoryEngine<br/>Log param_change event<br/>Update Playbook"]

    MEM --> PB["Playbook<br/>Per (instrument, signal_source):<br/>trade_count, win_count,<br/>total_pnl, avg_roe"]

    subgraph JOURNAL["Journal (per trade)"]
        JE["JournalEngine<br/>create_entry()"]
        JE --> QUALITY["Signal Quality<br/>good / fair / poor"]
        JE --> RETRO["Retrospective<br/>What to do differently"]
    end

    subgraph NIGHTLY["Nightly Review"]
        NR["compute_nightly_review()<br/>Today vs 7-day rolling avg"]
        NR --> FINDINGS["Key Findings<br/>Underperformance flags<br/>Strong day highlights"]
    end

    PB -->|"informs next cycle"| RE

    classDef active fill:#2d5a2d,stroke:#4a4,color:#fff
    classDef built fill:#5a4a2d,stroke:#a84,color:#fff

    class TRADES,RE,METRICS,REPORT,CT,RA,HG,APPLY,MEM,PB,JE,QUALITY,RETRO,NR,FINDINGS built
```

## Current State vs Target State

```mermaid
graph TB
    subgraph NOW["🔴 Current State"]
        N1["Heartbeat: runs but simplified<br/>Missing 12 iterators worth<br/>of capability"]
        N2["Daemon: BUILT but NOT RUNNING<br/>19 iterators, 3 tiers,<br/>full orchestration"]
        N3["REFLECT: BUILT but CLI ONLY<br/>Not wired into any loop"]
        N4["Thesis: MANUALLY WRITTEN<br/>No scheduled evaluation<br/>Goes stale for days"]
        N5["OpenClaw Agent: ALIVE<br/>but no write path,<br/>no live price tool"]
        N6["Alerts: noisy thesis spam<br/>No failure alerting<br/>One-way only"]
    end

    subgraph TARGET["🟢 Target State"]
        T1["Daemon replaces heartbeat<br/>All 19 iterators active<br/>Full tick orchestration"]
        T2["REFLECT wired into daemon<br/>AutoResearch every 30min<br/>Nightly journal review<br/>Weekly summary to Telegram"]
        T3["Thesis: Chris writes via Opus<br/>Daemon reads + executes<br/>Agent reads + discusses<br/>Stale safety clamps conviction"]
        T4["OpenClaw Agent: has tools<br/>update_thesis, live_price<br/>Can discuss and adjust"]
        T5["Alerts: action-only + hourly<br/>Failure alerting at 10+ fails<br/>Weekly REFLECT summary"]
        T6["Meta-evaluation: Playbook<br/>tracks what works,<br/>convergence detects drift,<br/>weekly report card for Chris"]
    end

    N1 -->|"Phase 2"| T1
    N2 -->|"Phase 2"| T1
    N3 -->|"Phase 3"| T2
    N4 -->|"Phase 1 (immediate)"| T3
    N5 -->|"Phase 1 (immediate)"| T4
    N6 -->|"Phase 1 (immediate)"| T5
    N3 -->|"Phase 3"| T6

    classDef now fill:#5a2d2d,stroke:#a44,color:#fff
    classDef target fill:#2d5a2d,stroke:#4a4,color:#fff

    class N1,N2,N3,N4,N5,N6 now
    class T1,T2,T3,T4,T5,T6 target
```

## Module Map (224 files, 0 orphans)

```mermaid
graph TD
    subgraph ENTRY["Entry Points"]
        MAIN["cli/main.py<br/>23 commands"]
        HB_SCRIPT["scripts/run_heartbeat.py"]
        VR_SCRIPT["scripts/run_vault_rebalancer.py"]
        SC_SCRIPT["scripts/scheduled_check.py"]
    end

    subgraph CLI["cli/ (23 commands)"]
        CMD_DAEMON["daemon.py"]
        CMD_STATUS["status.py"]
        CMD_TRADE["trade.py"]
        CMD_REFLECT["reflect.py"]
        CMD_GUARD["guard.py"]
        CMD_RADAR["radar.py"]
        CMD_PULSE["pulse.py"]
        CMD_APEX["apex.py"]
        CMD_TG["telegram.py"]
        CMD_MCP["mcp.py"]
        CMD_OTHER["+ 13 more"]
    end

    subgraph DAEMON["cli/daemon/ (orchestration)"]
        D_CLOCK["clock.py"]
        D_CTX["context.py<br/>21 importers"]
        D_TIERS["tiers.py"]
        D_STATE["state.py"]
        D_ROSTER["roster.py"]
        D_ITERS["19 iterators/"]
    end

    subgraph MODULES["modules/ (7 engines)"]
        M_APEX["apex_engine"]
        M_GUARD["guard_bridge<br/>5 importers"]
        M_RADAR["radar_engine<br/>3 importers"]
        M_PULSE["pulse_engine<br/>3 importers"]
        M_REFLECT["reflect_engine<br/>6 importers"]
        M_JOURNAL["journal_engine<br/>2 importers"]
        M_MEMORY["memory_engine<br/>3 importers"]
    end

    subgraph COMMON["common/ (25 utilities)"]
        C_MODELS["models<br/>39 importers"]
        C_CREDS["credentials<br/>8 importers"]
        C_HB["heartbeat<br/>4 importers"]
        C_THESIS["thesis<br/>5 importers"]
        C_CONV["conviction_engine"]
        C_MEMORY["memory<br/>5 importers"]
        C_OTHER["+ 19 more"]
    end

    subgraph PARENT["parent/ (exchange layer)"]
        P_PROXY["hl_proxy<br/>17 importers"]
        P_RISK["risk_manager<br/>9 importers"]
        P_POS["position_tracker<br/>6 importers"]
        P_OTHER["store, house_risk,<br/>sdk_patches"]
    end

    subgraph STRAT["strategies/ (22)"]
        S_ALL["power_law_btc<br/>brent_oil_squeeze<br/>oil_war_regime<br/>+ 19 more"]
    end

    subgraph SDK["sdk/strategy_sdk"]
        SDK_BASE["base.py<br/>32 importers"]
        SDK_LOAD["loader.py"]
        SDK_REG["registry.py"]
    end

    subgraph EXEC["execution/ (6)"]
        E_ROUTE["routing"]
        E_ORDER["order_types"]
        E_TWAP["twap"]
        E_OTHER["order_book,<br/>parent_order,<br/>portfolio_risk"]
    end

    subgraph QE["quoting_engine/ (13)"]
        QE_ALL["Market making engine<br/>(self-contained subsystem)"]
    end

    subgraph MCP_SRV["MCP Server"]
        MCP_TOOLS["17 tools<br/>market_context, account,<br/>status, analyze, trade..."]
    end

    subgraph OC_WS["openclaw/ (workspace)"]
        OC_AGENT_MD["AGENT.md"]
        OC_SOUL["SOUL.md"]
        OC_TOOLS["TOOLS.md"]
        OC_MEMORY_MD["MEMORY.md"]
    end

    MAIN --> CLI
    CLI --> DAEMON
    CLI --> MODULES
    CLI --> COMMON
    HB_SCRIPT --> C_HB
    CMD_DAEMON --> D_CLOCK
    D_CLOCK --> D_CTX
    D_CTX --> D_ITERS
    D_ITERS --> MODULES
    D_ITERS --> COMMON
    D_ITERS --> PARENT
    MODULES --> COMMON
    MODULES --> PARENT
    S_ALL --> SDK_BASE
    SDK_LOAD --> S_ALL
    CMD_MCP --> MCP_TOOLS
    MCP_TOOLS --> COMMON
    MCP_TOOLS --> PARENT
    C_HB --> C_THESIS
    C_HB --> C_CONV
    C_HB --> P_PROXY
    PARENT --> EXEC

    classDef hub fill:#4a3a2d,stroke:#a84,color:#fff
    class C_MODELS,SDK_BASE,P_PROXY,D_CTX hub
```

## Telegram Interface Map

```mermaid
graph LR
    subgraph CHRIS["👤 Chris's Phone"]
        CHAT1["@Hyperliquid0x88_bot<br/>Commands Bot<br/>DM chat"]
        CHAT2["@HyperLiquidOpenClaw_bot<br/>AI Agent<br/>DM chat"]
        CHAT3["Chris0x88Claude<br/>Alert Board<br/>One-way alerts"]
    end

    subgraph BOTS["Running Systems"]
        BOT1["cli/telegram_bot.py<br/>Polls every 2s<br/>22 fixed commands<br/>Zero AI credits"]
        BOT2["OpenClaw Gateway<br/>hl-trader agent<br/>MCP tools<br/>Cheap model"]
        BOT3["Heartbeat<br/>common/heartbeat.py<br/>Action alerts only<br/>Hourly status"]
    end

    CHAT1 <-->|"/status, /chartoil 72"| BOT1
    CHAT2 <-->|"free text AI chat"| BOT2
    BOT3 -->|"alerts (one-way)"| CHAT3

    classDef cmd fill:#2d5a2d,stroke:#4a4,color:#fff
    classDef ai fill:#2d4a5a,stroke:#48a,color:#fff
    classDef alert fill:#5a4a2d,stroke:#a84,color:#fff

    class CHAT1,BOT1 cmd
    class CHAT2,BOT2 ai
    class CHAT3,BOT3 alert
```

## File Inventory Summary

| Area | Files | Hub Nodes | Status |
|------|-------|-----------|--------|
| **cli/commands/** | 23 | main.py | ✅ All connected |
| **cli/daemon/** | 25 | context.py (21 importers) | 🟡 Built, not running as daemon |
| **modules/** | 35 | reflect_engine (6), guard_bridge (5) | 🟡 Built, partially wired |
| **common/** | 25 | models (39), credentials (8) | ✅ All connected |
| **parent/** | 6 | hl_proxy (17), risk_manager (9) | ✅ All connected |
| **execution/** | 6 | order_types (2) | ✅ All connected |
| **strategies/** | 22 | via sdk.base (32) | ✅ All connected |
| **quoting_engine/** | 13 | config (10) | ✅ Self-contained |
| **plugins/** | 6 | power_law | ✅ Connected |
| **scripts/** | 7 | entry points | ✅ All connected |
| **openclaw/** | 10 | workspace files | ✅ Connected to gateway |
| **TOTAL** | **224** | **0 orphans** | |
