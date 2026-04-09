#!/usr/bin/env python3
"""Generate SYSTEM_ARCHITECTURE.pdf — comprehensive system map for the HyperLiquid Bot."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.lib.colors import HexColor, black, white, grey
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    Preformatted, KeepTogether,
)
from reportlab.pdfgen import canvas
from pathlib import Path
import datetime

OUTPUT = Path(__file__).parent / "SYSTEM_ARCHITECTURE.pdf"

# Colors
NAVY = HexColor("#1a1a2e")
TEAL = HexColor("#16213e")
ACCENT = HexColor("#0f3460")
GOLD = HexColor("#e94560")
LIGHT_BG = HexColor("#f0f0f5")
MED_BG = HexColor("#d8d8e8")

styles = getSampleStyleSheet()

# Custom styles
styles.add(ParagraphStyle(
    "DocTitle", parent=styles["Title"], fontSize=28, spaceAfter=6,
    textColor=NAVY, alignment=TA_CENTER,
))
styles.add(ParagraphStyle(
    "DocSubtitle", parent=styles["Normal"], fontSize=14, spaceAfter=20,
    textColor=ACCENT, alignment=TA_CENTER, italic=True,
))
styles.add(ParagraphStyle(
    "SectionHead", parent=styles["Heading1"], fontSize=18, spaceBefore=20,
    spaceAfter=10, textColor=NAVY, borderWidth=1, borderColor=ACCENT,
    borderPadding=4,
))
styles.add(ParagraphStyle(
    "SubHead", parent=styles["Heading2"], fontSize=14, spaceBefore=14,
    spaceAfter=6, textColor=ACCENT,
))
styles.add(ParagraphStyle(
    "SubSubHead", parent=styles["Heading3"], fontSize=12, spaceBefore=10,
    spaceAfter=4, textColor=TEAL,
))
styles.add(ParagraphStyle(
    "Body", parent=styles["Normal"], fontSize=10, leading=14,
    spaceAfter=8, alignment=TA_JUSTIFY,
))
styles.add(ParagraphStyle(
    "BodySmall", parent=styles["Normal"], fontSize=9, leading=12,
    spaceAfter=4,
))
styles.add(ParagraphStyle(
    "CodeBlock", fontName="Courier", fontSize=8, leading=10,
    spaceAfter=8, backColor=LIGHT_BG, borderWidth=0.5,
    borderColor=MED_BG, borderPadding=6,
))
styles.add(ParagraphStyle(
    "CalloutBox", parent=styles["Normal"], fontSize=10, leading=13,
    backColor=HexColor("#fff3cd"), borderWidth=1, borderColor=HexColor("#ffc107"),
    borderPadding=8, spaceAfter=12,
))
styles.add(ParagraphStyle(
    "KeyPoint", parent=styles["Normal"], fontSize=10, leading=13,
    backColor=HexColor("#d4edda"), borderWidth=1, borderColor=HexColor("#28a745"),
    borderPadding=8, spaceAfter=12,
))

def make_table(headers, rows, col_widths=None):
    data = [headers] + rows
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, MED_BG),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LIGHT_BG]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t

def ascii_diagram(text):
    return Preformatted(text, styles["CodeBlock"])

def build():
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=25*mm, bottomMargin=20*mm,
    )
    story = []
    W = A4[0] - 40*mm  # usable width

    # ══════════════════════════════════════════════════════════════
    # COVER PAGE
    # ══════════════════════════════════════════════════════════════
    story.append(Spacer(1, 80))
    story.append(Paragraph("HyperLiquid Trading Bot", styles["DocTitle"]))
    story.append(Paragraph("System Architecture & Operations Manual", styles["DocSubtitle"]))
    story.append(Spacer(1, 30))
    story.append(Paragraph(
        "A personal trading instrument for one petroleum engineer that trades "
        "<b>with the dumb-bot reality</b> -- anticipating obvious moves, fading "
        "bot overshoot -- instead of betting on the market being a fair discounting mechanism.",
        styles["Body"],
    ))
    story.append(Spacer(1, 20))

    stats = [
        ["Metric", "Value"],
        ["Total Python LOC", "~127,000"],
        ["Daemon Iterators", "38"],
        ["Telegram Commands", "52"],
        ["Agent Tools", "41"],
        ["Strategy Archetypes", "24"],
        ["Engine Modules", "58"],
        ["Test Cases", "3,104"],
        ["Production Tier", "WATCH (mainnet, launchd-managed)"],
    ]
    story.append(make_table(stats[0], stats[1:], col_widths=[W*0.4, W*0.6]))
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} AEST",
        ParagraphStyle("DateLine", parent=styles["Normal"], fontSize=9, alignment=TA_CENTER, textColor=grey),
    ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # TABLE OF CONTENTS
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("Table of Contents", styles["SectionHead"]))
    toc = [
        "1. System Overview & Philosophy",
        "2. Architecture Diagram",
        "3. The Daemon Tick Engine",
        "4. Iterator Inventory (all 38)",
        "5. Telegram Bot & AI Agent",
        "6. Context Engine v2 (NEW)",
        "7. Lab Engine (NEW)",
        "8. Architect Engine (NEW)",
        "9. Oil Bot Pattern System (Sub-systems 1-6)",
        "10. Risk Management & Protection Chain",
        "11. Data Flow & Storage",
        "12. CLI Commands Reference",
        "13. Kill Switches & Config",
        "14. Operator Checklist",
        "15. Glossary",
    ]
    for item in toc:
        story.append(Paragraph(item, styles["Body"]))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 1. SYSTEM OVERVIEW
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("1. System Overview & Philosophy", styles["SectionHead"]))
    story.append(Paragraph(
        "The HyperLiquid Bot is a personal trading instrument that turns petroleum-engineering "
        "domain knowledge into structured signals that bot-driven markets cannot read. "
        "Markets are ~80% bots reacting to known information. The system exploits this by "
        "positioning ahead of obvious moves, then fading the bot overcorrection.",
        styles["Body"],
    ))

    story.append(Paragraph("The Five Promises", styles["SubHead"]))
    promises = [
        ["#", "Promise", "How"],
        ["1", "Capture every idea before it evaporates", "Telegram catch surface, 60s to structured input"],
        ["2", "Encode petroleum-engineering edge as data bots can't read", "Supply ledger, bot classifier, catalyst ingestion"],
        ["3", "Trade with the bot reality, not against it", "Bot-pattern system, anticipate + fade overshoot"],
        ["4", "Protect real capital", "Mandatory SL+TP, drawdown circuit breakers, per-asset autonomy"],
        ["5", "Learn from every closed trade", "Lesson corpus, autoresearch, journal -- append-only forever"],
    ]
    story.append(make_table(promises[0], promises[1:], col_widths=[W*0.05, W*0.35, W*0.6]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Authority Model", styles["SubHead"]))
    story.append(Paragraph(
        "Per-asset authority via <font face='Courier'>common/authority.py</font>: <b>agent</b> (autonomous), "
        "<b>manual</b> (human approval), or <b>off</b> (no trading). Default: manual. "
        "Persisted in <font face='Courier'>data/authority.json</font>. "
        "The system NEVER trades without explicit authority delegation per asset.",
        styles["Body"],
    ))

    story.append(Paragraph("Tier System", styles["SubHead"]))
    tiers = [
        ["Tier", "What It Does", "Kills Switches Active?"],
        ["WATCH", "Monitor, alert, shadow-trade. No real orders.", "Sub-system 5 in shadow mode"],
        ["REBALANCE", "Execute conviction-based sizing, guard stops, profit locks", "Full execution enabled"],
        ["OPPORTUNISTIC", "REBALANCE + radar-driven opportunistic entries", "All systems live"],
    ]
    story.append(make_table(tiers[0], tiers[1:], col_widths=[W*0.2, W*0.45, W*0.35]))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 2. ARCHITECTURE DIAGRAM
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("2. Architecture Diagram", styles["SectionHead"]))
    story.append(Paragraph(
        "The system has four layers: Interface (Telegram + CLI), Brain (AI Agent), "
        "Daemon (tick engine with 38 iterators), and Data (append-only stores).",
        styles["Body"],
    ))

    arch_diagram = """
+=====================================================================+
|                        INTERFACE LAYER                                |
|  +------------------+  +------------------+  +-------------------+   |
|  |   Telegram Bot   |  |    CLI (hl ...)   |  |  Claude Code IDE  |   |
|  |  52 commands      |  |  17 subcommands   |  |  (brain)          |   |
|  |  /status /market  |  |  hl lab           |  |  session-token    |   |
|  |  /lab /architect  |  |  hl architect     |  |  auth             |   |
|  +--------+---------+  +--------+---------+  +---------+---------+   |
|           |                      |                      |             |
+===========|======================|======================|=============+
            |                      |                      |
+===========v======================v======================v=============+
|                          AI AGENT LAYER                               |
|  +------------------+  +------------------+  +-------------------+   |
|  | Context Engine   |  |  Agent Runtime   |  |   Agent Tools     |   |
|  | v2 (intent       |  |  system prompt   |  |   41 tools        |   |
|  |  classify +      |  |  + lessons       |  |   READ auto-exec  |   |
|  |  enrich)         |  |  + live context  |  |   WRITE approval  |   |
|  +------------------+  +------------------+  +-------------------+   |
+=====================================================================+
            |
+===========v==========================================================+
|                      DAEMON TICK ENGINE                               |
|  clock.py -- 120s tick -- launchd-managed -- circuit breaker          |
|                                                                       |
|  WATCH tier (38 iterators):                                           |
|  +-----------+ +----------+ +----------+ +-----------+ +---------+  |
|  |account    | |market    | |thesis    | |radar      | |news     |  |
|  |collector  | |structure | |engine    | |           | |ingest   |  |
|  +-----------+ +----------+ +----------+ +-----------+ +---------+  |
|  +-----------+ +----------+ +----------+ +-----------+ +---------+  |
|  |supply     | |heatmap   | |bot       | |oil_bot    | |auto     |  |
|  |ledger     | |          | |classifier| |pattern    | |research |  |
|  +-----------+ +----------+ +----------+ +-----------+ +---------+  |
|  +-----------+ +----------+ +----------+ +-----------+ +---------+  |
|  |lab        | |architect | |lesson    | |entry      | |memory   |  |
|  |(NEW)      | |(NEW)     | |author    | |critic     | |backup   |  |
|  +-----------+ +----------+ +----------+ +-----------+ +---------+  |
|                                                                       |
|  REBALANCE adds: execution_engine, exchange_protection, guard,        |
|                  rebalancer, profit_lock, catalyst_deleverage          |
|  OPPORTUNISTIC adds: radar (active mode), pulse                       |
+=====================================================================+
            |
+===========v==========================================================+
|                         DATA LAYER                                    |
|  +-------------+ +--------------+ +-------------+ +--------------+  |
|  |data/thesis/ | |data/research/| |data/strategy/| |data/memory/  |  |
|  |  JSON state | |  evaluations | |  proposals   | |  memory.db   |  |
|  |  per market | |  learnings   | |  experiments | |  backups/    |  |
|  +-------------+ +--------------+ +-------------+ +--------------+  |
|  +-------------+ +--------------+ +-------------+ +--------------+  |
|  |data/news/   | |data/supply/  | |data/heatmap/ | |data/daemon/  |  |
|  |  catalysts  | |  state.json  | |  zones.jsonl | |  journal     |  |
|  |  RSS feeds  | |  disruptions | |  cascades    | |  state.json  |  |
|  +-------------+ +--------------+ +-------------+ +--------------+  |
+=====================================================================+
"""
    story.append(ascii_diagram(arch_diagram))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 3. DAEMON TICK ENGINE
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("3. The Daemon Tick Engine", styles["SectionHead"]))
    story.append(Paragraph(
        "The daemon is a Hummingbot-inspired tick engine. Every 120 seconds it runs all "
        "registered iterators in order. Each iterator receives a <font face='Courier'>TickContext</font> "
        "containing live account state, positions, and a shared alert/order queue.",
        styles["Body"],
    ))

    daemon_flow = """
  launchd (macOS)
       |
       v
  clock.py :: Clock.run()
       |
       +-- for each tick (120s):
       |     |
       |     +-- 1. Check control file for commands (pause/resume/tier-change)
       |     |
       |     +-- 2. Build TickContext (account state, positions, alerts=[])
       |     |
       |     +-- 3. For each iterator in tier order:
       |     |        iterator.tick(ctx)
       |     |        -> may append Alerts to ctx.alerts
       |     |        -> may append OrderIntents to ctx.orders
       |     |
       |     +-- 4. Execute queued OrderIntents (REBALANCE+ only)
       |     |        -> conviction sizing, exchange API calls
       |     |
       |     +-- 5. Persist state to data/daemon/state.json
       |     |
       |     +-- 6. Send alerts via Telegram
       |
       +-- HealthWindow: 10 errors / 900s = circuit breaker
"""
    story.append(ascii_diagram(daemon_flow))
    story.append(Spacer(1, 10))

    story.append(Paragraph(
        "<b>Key safety features:</b> Single-instance enforcement via PID file + pgrep scan. "
        "HealthWindow circuit breaker (10 errors in 15 min = stop). Risk gate states: "
        "OPEN / COOLDOWN / CLOSED. HWM auto-resets when flat to prevent phantom drawdowns.",
        styles["CalloutBox"],
    ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 4. ITERATOR INVENTORY
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("4. Iterator Inventory (all 38)", styles["SectionHead"]))
    story.append(Paragraph(
        "Every iterator follows the same interface: <font face='Courier'>on_start(ctx)</font>, "
        "<font face='Courier'>tick(ctx)</font>, <font face='Courier'>on_stop()</font>. "
        "Iterators are pure Python -- they read data, compute, and emit alerts/orders.",
        styles["Body"],
    ))

    iter_data = [
        ["Iterator", "Category", "Purpose", "Tier"],
        ["account_collector", "Core", "Inject live account state into TickContext", "ALL"],
        ["connector", "Core", "Exchange API adapter (DirectHLProxy)", "ALL"],
        ["market_structure", "Intel", "Pre-compute technicals (EMA, RSI, ADX, ATR)", "ALL"],
        ["thesis_engine", "Intel", "Read thesis JSON files into context", "ALL"],
        ["radar", "Intel", "Opportunity scanner -- find setups", "W/O"],
        ["pulse", "Intel", "Capital inflow detector", "W/O"],
        ["news_ingest", "OilBot #1", "RSS/iCal feeds to structured catalysts", "ALL"],
        ["supply_ledger", "OilBot #2", "Physical oil disruption aggregator", "ALL"],
        ["heatmap", "OilBot #3", "Stop/liquidity zone detection", "ALL"],
        ["bot_classifier", "OilBot #4", "Classify moves as bot/informed/mixed", "ALL"],
        ["oil_botpattern", "OilBot #5", "Strategy engine (only legal short path)", "ALL*"],
        ["oil_botpattern_tune", "OilBot #6 L1", "Bounded auto-tune (5 params)", "ALL*"],
        ["oil_botpattern_reflect", "OilBot #6 L2", "Weekly structural proposals", "ALL*"],
        ["oil_botpattern_patternlib", "OilBot #6 L3", "Pattern library growth", "ALL"],
        ["oil_botpattern_shadow", "OilBot #6 L4", "Counterfactual shadow eval", "ALL*"],
        ["execution_engine", "Execution", "Conviction-based order sizing", "R/O"],
        ["exchange_protection", "Safety", "Mandatory SL near liquidation", "R/O"],
        ["guard", "Safety", "Trailing stops + profit protection", "R/O"],
        ["liquidation_monitor", "Safety", "Tiered cushion alerts", "ALL"],
        ["protection_audit", "Safety", "Verify every position has SL", "ALL"],
        ["risk", "Safety", "Drawdown circuit breakers", "R/O"],
        ["profit_lock", "Safety", "Lock profits at thresholds", "R/O"],
        ["funding_tracker", "Monitor", "Cumulative funding cost tracker", "ALL"],
        ["brent_rollover_monitor", "Monitor", "T-7/T-3/T-1 contract roll alerts", "ALL"],
        ["catalyst_deleverage", "Execution", "Deleverage on catalyst events", "R/O"],
        ["rebalancer", "Execution", "Portfolio rebalancing", "R/O"],
        ["apex_advisor", "Intel", "Multi-slot autonomous advisor (dry-run)", "W"],
        ["autoresearch", "Learning", "Karpathy-style evaluation loop (30min)", "ALL"],
        ["lesson_author", "Learning", "Closed-position to lesson candidate", "ALL"],
        ["entry_critic", "Learning", "Grade every new entry", "ALL"],
        ["memory_consolidation", "Maint", "Compress old events hourly", "ALL"],
        ["memory_backup", "Maint", "Hourly atomic DB snapshots", "ALL"],
        ["action_queue", "Maint", "Daily operator ritual nudges", "ALL"],
        ["journal", "Record", "Structured trade journal", "ALL"],
        ["lab", "NEW", "Strategy development pipeline", "ALL*"],
        ["architect", "NEW", "Mechanical self-improvement (12h)", "ALL*"],
        ["telegram", "Interface", "Telegram bot polling loop", "ALL"],
    ]
    story.append(make_table(iter_data[0], iter_data[1:], col_widths=[W*0.18, W*0.1, W*0.47, W*0.07]))
    story.append(Paragraph(
        "<i>W=WATCH, R=REBALANCE, O=OPPORTUNISTIC. * = has kill switch (ships OFF)</i>",
        styles["BodySmall"],
    ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 5. TELEGRAM BOT & AI AGENT
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("5. Telegram Bot & AI Agent", styles["SectionHead"]))
    story.append(Paragraph(
        "Telegram is the primary interface. 52 slash commands are deterministic (fixed code, no AI). "
        "Free-text messages route to the AI agent. The agent has 41 tools (READ auto-execute, WRITE with approval).",
        styles["Body"],
    ))

    ai_flow = """
  User sends message to Telegram
       |
       +-- Starts with /? ----YES----> Deterministic command handler
       |                                (zero AI, zero cost)
       NO
       |
       v
  telegram_agent.py :: handle_ai_message()
       |
       +-- 1. Build system prompt (AGENT.md + SOUL.md)
       +-- 2. Build live context (account, positions, thesis, signals)
       +-- 3. Pre-fetch data by keyword (existing _prefetch_for_message)
       +-- 4. Context Engine v2: classify intent, enrich with additional
       |      data (bot classifier, supply, evaluations, proposals) [NEW]
       +-- 5. Load chat history (last 20 messages)
       +-- 6. Inject top-5 relevant lessons from corpus
       +-- 7. Call LLM (Anthropic session token or OpenRouter)
       +-- 8. Tool-calling loop (up to 12 iterations):
       |      - Native function calling (paid models)
       |      - Text-based [TOOL: name {args}] (free models)
       |      - Python code blocks (AST-parsed, free models)
       +-- 9. Send response to Telegram
"""
    story.append(ascii_diagram(ai_flow))

    story.append(Paragraph("Model Selection", styles["SubHead"]))
    story.append(Paragraph(
        "Default: <font face='Courier'>claude-haiku-4-5</font> (cheapest). "
        "User selects via <font face='Courier'>/models</font> command. "
        "Fallback chain: Gemma 27B (free) -> Llama 3.3 70B (free) -> StepFun (free) -> DeepSeek (free). "
        "<b>CRITICAL: Session tokens ONLY. Never API keys (costs would bankrupt user).</b>",
        styles["Body"],
    ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 6. CONTEXT ENGINE v2
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("6. Context Engine v2 (NEW)", styles["SectionHead"]))
    story.append(Paragraph(
        "The Context Engine upgrades the keyword-based prefetch with multi-signal intent "
        "classification and additional data sources. It runs BEFORE the LLM sees the message, "
        "ensuring the model has relevant data without needing to call tools.",
        styles["Body"],
    ))

    story.append(Paragraph("Intent Classification", styles["SubHead"]))
    intent_data = [
        ["Intent", "Triggers", "Data Fetched"],
        ["position_query", "position, portfolio, holding, long/short", "Positions, thesis, guard state"],
        ["market_analysis", "analysis, outlook, technical, setup", "Bot classifier, supply, catalysts, learnings"],
        ["performance_review", "how did we do, pnl, profit, returns", "Evaluations, trade history, metrics"],
        ["trade_planning", "should I, plan, add, scale, trim", "Positions, thesis, signals, bot classifier"],
        ["risk_check", "risk, liquidation, cushion, drawdown", "Positions, liquidation distances, exposure"],
        ["system_health", "status, health, daemon, error", "Daemon state, proposals, issues"],
        ["catalyst_query", "catalyst, news, opec, eia, event", "Calendar, upcoming catalysts"],
        ["signal_check", "signal, rsi, radar, pulse", "Signal snapshots, radar scores"],
        ["self_improvement", "learn, improve, tune, reflect", "Evaluations, proposals, lab experiments"],
    ]
    story.append(make_table(intent_data[0], intent_data[1:], col_widths=[W*0.18, W*0.35, W*0.47]))

    story.append(Paragraph("New Data Sources (vs existing prefetch)", styles["SubHead"]))
    new_sources = [
        ["Source", "File", "When Fetched"],
        ["Bot classifier results", "data/research/bot_patterns.jsonl", "market_analysis, trade_planning"],
        ["Supply disruptions", "data/supply/state.json", "Oil market queries"],
        ["Autoresearch evaluations", "data/research/evaluations/*.json", "performance_review, system_health"],
        ["Pending proposals", "data/strategy/*_proposals.jsonl", "system_health, self_improvement"],
        ["Calendar/catalysts", "data/news/catalysts.jsonl", "catalyst_query, market_analysis"],
        ["Recent learnings", "data/research/learnings.md", "market_analysis, trade_planning"],
        ["Lab experiments", "data/lab/experiments.json", "system_health, self_improvement"],
    ]
    story.append(make_table(new_sources[0], new_sources[1:], col_widths=[W*0.22, W*0.42, W*0.36]))

    story.append(Paragraph(
        "<b>Anti-pollution:</b> Each block has a relevance score (0-1). Blocks are sorted by score "
        "and fitted within a token budget (800 tokens default). Low-relevance data is dropped, "
        "not injected. The existing keyword prefetch (2000 char cap) runs first; the Context Engine "
        "adds supplementary data only when the intent warrants it.",
        styles["KeyPoint"],
    ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 7. LAB ENGINE
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("7. Lab Engine (NEW)", styles["SectionHead"]))
    story.append(Paragraph(
        "The Lab Engine is an autonomous strategy development pipeline. It discovers strategy "
        "candidates for a market, backtests them, paper-trades them, and graduates them for "
        "human approval before production deployment.",
        styles["Body"],
    ))

    lab_flow = """
  DISCOVER              HYPOTHESIS           BACKTEST
  Profile market   -->  Create experiment  -->  Run against
  (vol, trend,          with archetype          historical data
   bot-driven?)         params                  (backtest_engine.py)
       |                     |                       |
       |                     |              Pass thresholds?
       |                     |              Sharpe >= 0.8
       |                     |              Win rate >= 40%
       |                     |              Drawdown <= 15%
       |                     |                   |
       v                     v                   v
  PAPER_TRADE           GRADUATED            PRODUCTION
  Live validation  -->  Alert user via  -->  Human promotes
  (24h minimum)         Telegram             Params FROZEN
                                             Becomes signal
                                             in matrix
"""
    story.append(ascii_diagram(lab_flow))

    story.append(Paragraph("Strategy Archetypes", styles["SubHead"]))
    arch_data = [
        ["Archetype", "Description", "Suitable Markets"],
        ["momentum_breakout", "Breakout on strong momentum with ATR stops", "Trending, high volatility"],
        ["mean_reversion", "Fade overextended moves (RSI + Bollinger)", "Range-bound, low volatility"],
        ["bot_fade", "Fade bot-driven overcorrections", "Bot-driven, event-driven"],
        ["catalyst_anticipation", "Position ahead of known catalysts", "Event-driven, oil"],
        ["trend_following", "Follow trends with trailing stops", "Trending"],
    ]
    story.append(make_table(arch_data[0], arch_data[1:], col_widths=[W*0.22, W*0.42, W*0.36]))

    story.append(Paragraph(
        "<b>Signal Matrix:</b> Multiple graduated strategies can run per market. When multiple "
        "strategies agree on direction, conviction increases. This is the 'neural network' of "
        "trading logic -- each strategy is a signal, and alignment = higher confidence.",
        styles["KeyPoint"],
    ))

    story.append(Paragraph("Commands", styles["SubHead"]))
    lab_cmds = [
        ["Command", "What It Does"],
        ["hl lab status", "Show all experiments grouped by status"],
        ["hl lab discover BRENTOIL", "Profile market, create matching experiments"],
        ["hl lab create BTC momentum_breakout", "Manually create an experiment"],
        ["hl lab backtest exp-abc123", "Run backtest for an experiment"],
        ["hl lab promote exp-abc123", "Promote graduated experiment to production"],
        ["hl lab retire exp-abc123", "Retire an experiment"],
        ["/lab", "Telegram: show status"],
        ["/lab discover BRENTOIL", "Telegram: discover + create"],
        ["/lab promote exp-abc123", "Telegram: promote to production"],
    ]
    story.append(make_table(lab_cmds[0], lab_cmds[1:], col_widths=[W*0.4, W*0.6]))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 8. ARCHITECT ENGINE
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("8. Architect Engine (NEW)", styles["SectionHead"]))
    story.append(Paragraph(
        "The Architect Engine closes the loop between problem detection and fix proposals. "
        "It runs every 12 hours using pure Python pattern matching -- zero AI calls, zero API costs. "
        "It reads autoresearch evaluations, detects recurring patterns, and generates concrete "
        "fix proposals that require human approval.",
        styles["Body"],
    ))

    arch_flow = """
  Every 12 hours (daemon iterator)                    On-demand (CLI/Telegram)
       |                                                     |
       v                                                     v
  DETECT (pure Python)                              hl architect detect
  Read data/research/evaluations/*.json             /architect detect
  Read data/daemon/issues.jsonl
       |
       v
  PATTERN MATCH (rules, not AI)
  - noise_exits > thesis_exits for 3+ evals?  --> finding
  - sizing_alignment < 50% for 3+ evals?      --> finding
  - funding_efficiency < 30% for 3+ evals?    --> finding
  - catalyst_timing < 40% for 3+ evals?       --> finding
  - recurring issue category 3+ times?         --> finding
       |
       v
  HYPOTHESIZE (deterministic)
  Each finding type has a known remediation:
  - noise_exits     --> widen weekend stop distance
  - sizing_drift    --> recalibrate conviction bands
  - funding_drag    --> add funding-cost exit trigger
  - catalyst_timing --> increase pre-positioning window
       |
       v
  PROPOSE --> Telegram alert
  /architect proposals     -- list pending
  /architect approve <id>  -- approve (human required)
  /architect reject <id>   -- reject
"""
    story.append(ascii_diagram(arch_flow))

    story.append(Paragraph(
        "<b>Cost model:</b> The Architect iterator is pure Python file reads + pattern matching. "
        "It never calls an LLM. It never makes API requests. Default cadence is 12 hours. "
        "AI-assisted deep analysis is available on-demand via Claude Code (the brain), not via the iterator.",
        styles["CalloutBox"],
    ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 9. OIL BOT PATTERN SYSTEM
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("9. Oil Bot Pattern System (Sub-systems 1-6)", styles["SectionHead"]))
    story.append(Paragraph(
        "The Oil Bot Pattern System is the core trading strategy. It has 6 sub-systems "
        "that form a pipeline from data ingestion to self-improvement.",
        styles["Body"],
    ))

    oilbot_flow = """
  Sub-system 1: NEWS INGEST          Sub-system 2: SUPPLY LEDGER
  RSS/iCal feeds --> catalysts.jsonl  catalysts + /disrupt --> state.json
       |                                    |
       v                                    v
  Sub-system 3: HEATMAP              Sub-system 4: BOT CLASSIFIER
  L2 book depth --> zones.jsonl       catalysts + supply + candles
  OI/funding --> cascades.jsonl       --> bot_patterns.jsonl
       |                                    |
       +------------------------------------+
       |
       v
  Sub-system 5: STRATEGY ENGINE (oil_botpattern)
  The ONLY place where shorting BRENTOIL/CL is legal.
  Chain: gate checks --> conviction sizing --> OrderIntent
  Kill switches: enabled=false, short_legs_enabled=false
  Drawdown breakers: 3% daily / 8% weekly / 15% monthly
       |
       v
  Sub-system 6: SELF-IMPROVEMENT (4 layers)
  L1: oil_botpattern_tune     -- bounded auto-tune (5 params, +/-5%, 24h rate limit)
  L2: oil_botpattern_reflect  -- weekly structural proposals (human approval)
  L3: oil_botpattern_patternlib -- pattern library growth (novel signatures)
  L4: oil_botpattern_shadow   -- counterfactual shadow evaluation
"""
    story.append(ascii_diagram(oilbot_flow))

    story.append(Paragraph("Sub-system 5 Gate Chain", styles["SubHead"]))
    story.append(Paragraph(
        "Every potential trade passes through a chain of hard gates before an OrderIntent is emitted. "
        "Failure at any gate = no trade. The gates are: master kill switch, instrument enabled, "
        "direction allowed (long-only on oil unless short_legs_enabled), drawdown circuit breaker, "
        "thesis conflict lockout (24h), and sizing sanity check.",
        styles["Body"],
    ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 10. RISK MANAGEMENT
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("10. Risk Management & Protection Chain", styles["SectionHead"]))

    risk_layers = """
  Layer 1: EXCHANGE-SIDE (cannot be bypassed)
  Every position MUST have SL + TP on exchange.
  protection_audit iterator verifies every tick.

  Layer 2: GUARD (trailing stops)
  ATR-based trailing stops that tighten as profit grows.
  Profit lock: step-function protection at thresholds.

  Layer 3: DRAWDOWN BREAKERS
  3% daily / 8% weekly / 15% monthly drawdown = risk gate CLOSED.
  HWM auto-resets when flat (no positions).

  Layer 4: LIQUIDATION MONITOR
  Tiered alerts: info at 20%, warning at 15%, critical at 10%.
  6.5% cushion at 11x leverage is NORMAL (not an alert).

  Layer 5: CONVICTION SIZING
  Position size = f(conviction, account_equity, leverage_cap).
  Druckenmiller-style: big when conviction is high, tiny when low.
  Start small, scale in as thesis confirms.

  Layer 6: AUTHORITY MODEL
  Per-asset: agent / manual / off.
  No trading without explicit delegation.
"""
    story.append(ascii_diagram(risk_layers))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 11. DATA FLOW
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("11. Data Flow & Storage", styles["SectionHead"]))
    story.append(Paragraph(
        "All data is append-only (per NORTH_STAR P9). Historical oracles are never deleted. "
        "Key data stores:",
        styles["Body"],
    ))

    data_stores = [
        ["Path", "Format", "Written By", "Read By"],
        ["data/thesis/*.json", "JSON", "User via Claude Code", "thesis_engine, agent, prefetch"],
        ["data/research/evaluations/", "JSON", "autoresearch (30min)", "architect, agent, prefetch"],
        ["data/research/learnings.md", "Markdown", "autoresearch", "agent, context_engine"],
        ["data/research/bot_patterns.jsonl", "JSONL", "bot_classifier", "oil_botpattern, context_engine"],
        ["data/news/catalysts.jsonl", "JSONL", "news_ingest", "catalyst_deleverage, prefetch"],
        ["data/supply/state.json", "JSON", "supply_ledger", "context_engine, agent"],
        ["data/heatmap/zones.jsonl", "JSONL", "heatmap", "prefetch, agent"],
        ["data/strategy/oil_botpattern_*.jsonl", "JSONL", "sub-system 5+6", "selftune commands"],
        ["data/lab/experiments.json", "JSON", "lab_engine", "lab iterator, context_engine"],
        ["data/architect/proposals.json", "JSON", "architect_engine", "architect iterator"],
        ["data/memory/memory.db", "SQLite", "lesson_author, agent", "lesson search, agent"],
        ["data/daemon/chat_history.jsonl", "JSONL", "telegram_agent", "agent (last 20)"],
        ["data/daemon/journal.jsonl", "JSONL", "journal iterator", "autoresearch, reflect"],
        ["data/config/*.json", "JSON", "User/selftune", "All iterators (kill switches)"],
    ]
    story.append(make_table(data_stores[0], data_stores[1:], col_widths=[W*0.28, W*0.08, W*0.28, W*0.36]))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 12. CLI COMMANDS
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("12. CLI Commands Reference", styles["SectionHead"]))

    cli_cmds = [
        ["Command", "Purpose"],
        ["hl status", "Show positions, PnL, risk state"],
        ["hl account", "Show HL account state"],
        ["hl trade", "Place a single manual order"],
        ["hl guard status/stop", "Guard trailing stop system"],
        ["hl radar scan", "Screen HL perps for setups"],
        ["hl pulse scan", "Detect capital inflow"],
        ["hl apex status", "APEX multi-slot trading status"],
        ["hl reflect summary", "Performance review"],
        ["hl journal show", "Trade journal"],
        ["hl backtest run", "Run strategy backtest"],
        ["hl daemon start", "Start daemon tick engine"],
        ["hl telegram start", "Start Telegram bot"],
        ["hl lab status/discover/backtest/promote", "Strategy development pipeline"],
        ["hl architect status/detect/proposals/approve", "Mechanical self-improvement"],
        ["hl keys list/add/remove", "Key management"],
        ["hl markets search/list", "Browse HL perpetual contracts"],
        ["hl data fetch", "Historical data management"],
        ["hl wallet", "Encrypted keystore"],
        ["hl setup check", "Environment validation"],
    ]
    story.append(make_table(cli_cmds[0], cli_cmds[1:], col_widths=[W*0.45, W*0.55]))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 13. KILL SWITCHES
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("13. Kill Switches & Configuration", styles["SectionHead"]))
    story.append(Paragraph(
        "Every trading system ships with kill switches OFF. Enable only after testing. "
        "Config files are in <font face='Courier'>data/config/</font>.",
        styles["Body"],
    ))

    kills = [
        ["Config File", "Key", "Default", "What It Controls"],
        ["oil_botpattern.json", "enabled", "false", "Sub-system 5 strategy engine"],
        ["oil_botpattern.json", "short_legs_enabled", "false", "Oil shorting (the only legal path)"],
        ["oil_botpattern_tune.json", "enabled", "false", "L1 bounded auto-tune"],
        ["oil_botpattern_reflect.json", "enabled", "false", "L2 weekly structural proposals"],
        ["oil_botpattern_patternlib.json", "enabled", "false", "L3 pattern library growth"],
        ["oil_botpattern_shadow.json", "enabled", "false", "L4 counterfactual shadow eval"],
        ["lab.json", "enabled", "false", "Lab Engine strategy pipeline"],
        ["architect.json", "enabled", "false", "Architect Engine self-improvement"],
        ["news_ingest.json", "enabled", "true", "RSS/iCal catalyst ingestion"],
        ["supply_ledger.json", "enabled", "true", "Supply disruption tracking"],
        ["heatmap.json", "enabled", "true", "Liquidity zone detection"],
        ["bot_classifier.json", "enabled", "true", "Bot-pattern classification"],
        ["entry_critic.json", "enabled", "true", "Trade entry grading"],
        ["lesson_author.json", "enabled", "true", "Trade lesson generation"],
        ["memory_backup.json", "interval_hours", "1", "Memory DB backup frequency"],
    ]
    story.append(make_table(kills[0], kills[1:], col_widths=[W*0.28, W*0.18, W*0.1, W*0.44]))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 14. OPERATOR CHECKLIST
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("14. Operator Checklist", styles["SectionHead"]))
    story.append(Paragraph(
        "Things Chris should check regularly. The <font face='Courier'>/nudge</font> command "
        "surfaces overdue items automatically.",
        styles["Body"],
    ))

    story.append(Paragraph("Daily", styles["SubHead"]))
    daily = [
        ["Task", "Command", "What to Look For"],
        ["Check positions", "/status", "Unexpected positions, missing SL/TP"],
        ["Review alerts", "(Telegram alerts)", "Any critical severity alerts"],
        ["Check daemon health", "/health or daemon state", "Circuit breaker status, error count"],
        ["Review thesis freshness", "/thesis", "Stale theses (>7 days without update)"],
    ]
    story.append(make_table(daily[0], daily[1:], col_widths=[W*0.25, W*0.3, W*0.45]))

    story.append(Paragraph("Weekly", styles["SubHead"]))
    weekly = [
        ["Task", "Command", "What to Look For"],
        ["Brutal review", "/brutalreviewai", "Deep audit of trading state + codebase"],
        ["Check proposals", "/selftuneproposals + /architect proposals", "Pending proposals to approve/reject"],
        ["Review learnings", "data/research/learnings.md", "Autoresearch findings, patterns"],
        ["Check lab experiments", "/lab", "Any graduated experiments to review"],
        ["Review catalyst calendar", "/catalysts", "Upcoming events requiring positioning"],
    ]
    story.append(make_table(weekly[0], weekly[1:], col_widths=[W*0.25, W*0.35, W*0.4]))

    story.append(Paragraph("Monthly / Quarterly", styles["SubHead"]))
    monthly = [
        ["Task", "Command", "What to Look For"],
        ["Memory restore drill", "See wiki/operations/", "Verify backup/restore works"],
        ["Thesis deep refresh", "Claude Code session", "Update conviction, targets, invalidation"],
        ["Performance review", "/reflect + Claude Code", "Win rate, Sharpe, drawdown analysis"],
        ["Kill switch audit", "data/config/*.json", "Which systems should be enabled/disabled"],
    ]
    story.append(make_table(monthly[0], monthly[1:], col_widths=[W*0.25, W*0.3, W*0.45]))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # 15. GLOSSARY
    # ══════════════════════════════════════════════════════════════
    story.append(Paragraph("15. Glossary", styles["SectionHead"]))

    glossary = [
        ["Term", "Definition"],
        ["Iterator", "A daemon component that runs every tick (120s). Pure Python, no I/O."],
        ["TickContext", "Shared state passed to every iterator: account, positions, alerts, orders."],
        ["OrderIntent", "A proposed trade that the execution engine will size and submit."],
        ["Thesis", "A JSON file in data/thesis/ encoding conviction, direction, TP, SL, invalidation."],
        ["Conviction", "A 0-1 score representing confidence in a trade thesis."],
        ["Guard", "Trailing stop system that protects open positions."],
        ["HWM", "High Water Mark -- tracked for drawdown circuit breakers."],
        ["Kill Switch", "A config flag (enabled: false) that completely disables a system."],
        ["Shadow Mode", "Running a strategy without real orders (paper trading)."],
        ["Graduation", "When a lab experiment passes all thresholds and is ready for production."],
        ["Finding", "An architect-detected recurring pattern (e.g., noise exits dominant)."],
        ["Proposal", "A concrete fix generated from a finding, requiring human approval."],
        ["Bot Classifier", "Sub-system 4: classifies market moves as bot-driven, informed, or mixed."],
        ["Supply Ledger", "Sub-system 2: aggregates active physical oil supply disruptions."],
        ["Heatmap", "Sub-system 3: detects liquidity zones and liquidation cascades."],
        ["AEST", "Australian Eastern Standard Time (UTC+10, no DST). All schedules in Brisbane local."],
        ["xyz perps", "HyperLiquid xyz clearinghouse perps. Need dex='xyz' in all API calls."],
        ["Session Token", "OAuth token for Anthropic API. NEVER use API keys (cost control)."],
    ]
    story.append(make_table(glossary[0], glossary[1:], col_widths=[W*0.2, W*0.8]))

    # Build
    doc.build(story)
    print(f"PDF written to {OUTPUT}")


if __name__ == "__main__":
    build()
