"""Hand-curated iterator descriptions for the Control Panel.

Auto-extraction from docstrings handles most iterators, but a handful have
docstrings that are too technical or too brief to show operators directly.
This module provides the override map — edit here without touching API code.

Each entry key is the exact iterator name (matching daemon/tiers.py).
Fields:
  description      — 1 sentence, operator-friendly, plain English
  purpose          — 3-5 sentences explaining why it exists, what it watches,
                     what it produces, what happens when it fires
  kill_switch_impact — honest statement of what STOPS working if turned off
  inputs           — list of data sources read
  outputs          — list of data files / alerts / state writes
  category         — Trading | Safety | Intelligence | Self-improvement | Operations

Any iterator NOT in this map gets auto-generated from its Python docstring.
"""

from __future__ import annotations

ITERATOR_DESCRIPTIONS: dict[str, dict] = {
    # ── Core Infrastructure ────────────────────────────────────────────────────
    "account_collector": {
        "description": "Takes a full account snapshot every 5 minutes and tracks your high-water mark and drawdown.",
        "purpose": (
            "Fetches live positions from both the native HyperLiquid and xyz clearinghouses, "
            "then computes your current high-water mark (best equity ever reached) and how far "
            "below it you are now (drawdown %). It writes a timestamped JSON snapshot to disk so "
            "every AI evaluation is grounded in current account state rather than stale numbers. "
            "Without it, the AI and most risk monitors are flying blind."
        ),
        "kill_switch_impact": (
            "Every AI evaluation loses live account context. Drawdown tracking stops. "
            "The liquidation monitor and portfolio risk monitor will still run, but they "
            "won't have the high-water mark reference. Risk alerts become less accurate."
        ),
        "inputs": ["HyperLiquid API (native + xyz positions)", "data/daemon/state.json"],
        "outputs": ["data/snapshots/account_YYYYMMDD_HHMMSS.json", "TickContext (snapshot_ref, account_drawdown_pct, high_water_mark)"],
        "category": "Operations",
    },

    "connector": {
        "description": "Fetches live market prices and candles each tick and makes them available to every other iterator.",
        "purpose": (
            "This is the data ingestion layer. Every tick it polls HyperLiquid for current "
            "mark prices, open interest, and candle data for all tracked instruments. "
            "Nothing else runs correctly without it — thesis engine, execution engine, "
            "risk monitors and signal generators all read prices from the context this iterator fills."
        ),
        "kill_switch_impact": (
            "Every price-dependent iterator fails silently. No market prices means no signals, "
            "no risk calculations, no liquidation monitoring. The daemon keeps running but is "
            "effectively blind to market conditions."
        ),
        "inputs": ["HyperLiquid API (prices, candles, OI, funding)"],
        "outputs": ["TickContext (prices, candles, positions, funding rates)"],
        "category": "Operations",
    },

    "telegram": {
        "description": "Delivers queued alerts and notifications to your Telegram chat.",
        "purpose": (
            "At the end of each tick, every other iterator appends alerts to a shared queue. "
            "This iterator drains that queue and sends each message to your Telegram chat. "
            "It is the final step in the alert delivery chain — without it, alerts accumulate "
            "in memory and are silently discarded at tick end."
        ),
        "kill_switch_impact": (
            "ALL alerts go silent — no liquidation warnings, no price move alerts, no thesis "
            "challenges, no trade notifications, nothing. The daemon keeps running and making "
            "decisions, but you receive zero feedback. This is the most dangerous iterator to disable."
        ),
        "inputs": ["TickContext alert queue (populated by all other iterators)"],
        "outputs": ["Telegram messages to configured chat"],
        "category": "Operations",
    },

    # ── Safety ────────────────────────────────────────────────────────────────
    "liquidation_monitor": {
        "description": "Watches every open position each tick and sends tiered alerts as you approach liquidation.",
        "purpose": (
            "Computes how much of your initial margin cushion is left on each position. "
            "At entry this is 100%; at liquidation it reaches 0%. It fires escalating "
            "Telegram alerts at 50%, 30%, and 15% remaining cushion so you have time to "
            "act before the exchange force-closes you. "
            "This is your first warning system before the hard stop fires."
        ),
        "kill_switch_impact": (
            "You lose all margin-burn warnings. You won't know a position is drifting toward "
            "liquidation until the exchange closes it for you. The exchange stop (exchange_protection) "
            "is still there as a last resort, but you lose all advance warning."
        ),
        "inputs": ["TickContext positions", "TickContext prices"],
        "outputs": ["Telegram alerts (tiered severity)", "TickContext alert queue"],
        "category": "Safety",
    },

    "exchange_protection": {
        "description": "Places a 'don't get liquidated' stop-loss order on the exchange just above your liquidation price.",
        "purpose": (
            "This is ruin prevention, not a trading stop. It places an exchange-level trigger "
            "order at liquidation_price × 1.02 (2% buffer). If the bot is offline, loses "
            "connectivity, or crashes, the exchange will still close your position before "
            "full liquidation. It has exactly one job: ensure the account never gets wiped. "
            "It does NOT manage take-profit or conviction-based sizing."
        ),
        "kill_switch_impact": (
            "Your positions have no exchange-side stop. If the daemon crashes or loses internet "
            "while a position is open and moves against you hard, the exchange will liquidate "
            "the full position with no buffer. This is the single most critical safety net. "
            "Only disable in WATCH tier (where no live positions are opened)."
        ),
        "inputs": ["TickContext positions", "TickContext prices", "HyperLiquid API (existing trigger orders)"],
        "outputs": ["Exchange trigger orders (placed/updated via API)", "Telegram alerts on sync"],
        "category": "Safety",
    },

    "guard": {
        "description": "Ratchets your stop-loss upward as a position profits — a trailing stop that tightens as you win.",
        "purpose": (
            "Once a position is profitable, Guard moves the exchange stop-loss upward to lock "
            "in gains. It never moves the stop down. When the price retraces to the guard floor, "
            "it queues a close order. This is the second line of defense after exchange_protection: "
            "exchange_protection sets a static floor at entry, guard raises it dynamically. "
            "Think of it as the difference between 'survive' and 'keep profits'."
        ),
        "kill_switch_impact": (
            "Trailing stops stop updating. Winning positions that retrace will only be caught "
            "by the original static stop (exchange_protection). You'll give back more profit "
            "than necessary before a position closes."
        ),
        "inputs": ["TickContext positions", "TickContext prices", "modules/guard_bridge.py state"],
        "outputs": ["Exchange trigger order updates", "Close order queue", "Telegram alerts"],
        "category": "Safety",
    },

    "protection_audit": {
        "description": "Checks every open position each tick to confirm it has a valid exchange stop — fires a critical alert if one is missing.",
        "purpose": (
            "Purely defensive monitor — it never writes to the exchange. Each cycle it fetches "
            "existing trigger orders and cross-checks them against open positions. If any position "
            "lacks an exchange-side stop it fires a CRITICAL Telegram alert immediately. "
            "This catches coordination failures where exchange_protection or guard failed to set a stop. "
            "It is the safety net behind the safety net."
        ),
        "kill_switch_impact": (
            "Silent failures in exchange_protection or guard go undetected. A position could "
            "be open with no stop and you'd never know until something bad happened."
        ),
        "inputs": ["HyperLiquid API (existing trigger orders)", "TickContext positions"],
        "outputs": ["CRITICAL Telegram alerts (only on missing stops)"],
        "category": "Safety",
    },

    "risk": {
        "description": "Runs a chain of risk checks (drawdown, loss streak, volatility) and sets a global risk gate that blocks new trades during dangerous conditions.",
        "purpose": (
            "Implements the composable ProtectionChain pattern: multiple independent risk checks "
            "each vote OPEN/COOLDOWN/CLOSED. The worst vote wins. Checks include daily drawdown "
            "limits, consecutive loss streaks, and volatility spikes. When the gate is CLOSED "
            "or COOLDOWN, the execution engine refuses to open new positions. "
            "This is the circuit breaker that prevents a bad run from becoming an account wipe."
        ),
        "kill_switch_impact": (
            "All circuit breakers are disabled. The bot will keep opening new positions during "
            "drawdowns, loss streaks, and volatility spikes. Combined losses can compound rapidly. "
            "Do not disable this unless you are debugging risk logic in a mock environment."
        ),
        "inputs": ["data/config/risk_caps.json", "TickContext (equity, positions)", "data/daemon/state.json"],
        "outputs": ["TickContext risk_gate (OPEN / COOLDOWN / CLOSED)", "Telegram alerts on state changes"],
        "category": "Safety",
    },

    "portfolio_risk_monitor": {
        "description": "Watches your total dollar risk across all positions and alerts when you're near the cumulative cap.",
        "purpose": (
            "Sums (distance to stop-loss × position size) across every open position and "
            "compares it to total account equity. This is the portfolio-level risk budget — "
            "separate from per-position liquidation monitoring. The rule: don't risk more than "
            "a set percentage of equity across all positions simultaneously. "
            "Fires Telegram warnings at 70% of cap and critical alerts at 100%."
        ),
        "kill_switch_impact": (
            "You lose visibility into aggregate risk. Individual positions might each look "
            "safe, but combined they could risk far more than intended. No alert will warn you."
        ),
        "inputs": ["TickContext positions", "TickContext prices", "data/config/portfolio_risk_monitor.json"],
        "outputs": ["Telegram alerts (warning + critical)", "TickContext alert queue"],
        "category": "Safety",
    },

    "profit_lock": {
        "description": "Sweeps a percentage of realized profits to reduce position size and protect gains.",
        "purpose": (
            "After a position closes profitably, this iterator tracks cumulative realized P&L "
            "and when a threshold is hit, queues a reduce-only order to bank some of the gain. "
            "Because HyperLiquid doesn't support programmatic vault transfers yet, profit locking "
            "works by partially closing the most profitable position. "
            "Configurable sweep percentage (default 25% of realized profits above threshold)."
        ),
        "kill_switch_impact": (
            "Realized profits are not automatically protected. A winning streak followed by "
            "a drawdown could give back gains that could have been locked. Low urgency to keep "
            "enabled in WATCH tier since no live trading happens there."
        ),
        "inputs": ["data/research/journal.jsonl (closed trades)", "TickContext positions"],
        "outputs": ["Reduce-only OrderIntents", "data/daemon/profit_locks.jsonl", "Telegram alerts"],
        "category": "Safety",
    },

    "liquidity": {
        "description": "Detects low-liquidity periods (weekends, after-hours) and adjusts position sizing down.",
        "purpose": (
            "Low-liquidity windows (weekends, 22:00–06:00 UTC) see 60-80% lower volume, "
            "higher slippage, and frequent stop hunts. This iterator classifies the current "
            "regime and injects a multiplier into TickContext that the execution engine uses "
            "to size down during dangerous hours. "
            "NOTE: removed from all tiers 2026-04-17 due to excessive noise (73% of all alerts) — "
            "static helper still callable via LiquidityIterator.get_regime_multipliers()."
        ),
        "kill_switch_impact": (
            "Positions sized without liquidity adjustment. During weekends and off-hours, "
            "slippage and stop hunts become more likely. Currently not active in any tier."
        ),
        "inputs": ["System time (UTC)", "TickContext prices"],
        "outputs": ["TickContext liquidity_regime multiplier"],
        "category": "Safety",
    },

    # ── Trading ───────────────────────────────────────────────────────────────
    "execution_engine": {
        "description": "The main trading engine: reads AI conviction scores and sizes/opens positions accordingly — DISABLED by default.",
        "purpose": (
            "This is the thesis-driven execution path. It reads conviction scores from thesis "
            "files (written by the AI scheduled task) and sizes positions using Druckenmiller-style "
            "conviction bands: higher conviction → larger position. It enforces stop-loss and "
            "take-profit discipline. Only runs in REBALANCE and OPPORTUNISTIC tiers. "
            "DISABLED BY DEFAULT — enable only when you want the robot trading autonomously."
        ),
        "kill_switch_impact": (
            "Thesis-driven autonomous trading stops. No new positions are opened or sized "
            "based on AI conviction. You can still trade manually via Telegram commands. "
            "This is the intended state in WATCH tier."
        ),
        "inputs": ["TickContext thesis_states (from thesis_engine)", "TickContext risk_gate (from risk)", "data/config/execution_engine.json"],
        "outputs": ["OrderIntents (queued for exchange execution)", "Telegram trade alerts", "data/daemon/journal/"],
        "category": "Trading",
    },

    "rebalancer": {
        "description": "Runs registered strategies on each tick to rebalance position sizes toward target allocations.",
        "purpose": (
            "Each registered strategy implements an on_tick() method. The rebalancer calls "
            "each one and processes any resulting OrderIntents. Currently used for the oil "
            "bot-pattern strategy rung ladder and any future registered strategies. "
            "Only active in REBALANCE and OPPORTUNISTIC tiers."
        ),
        "kill_switch_impact": (
            "Strategy-driven position rebalancing stops. Positions stay at their current "
            "size regardless of conviction changes. The strategy roster keeps ticking but "
            "produces no exchange actions."
        ),
        "inputs": ["TickContext (prices, positions, risk_gate)", "Registered strategy roster"],
        "outputs": ["OrderIntents (passed to exchange execution layer)"],
        "category": "Trading",
    },

    "catalyst_deleverage": {
        "description": "Automatically reduces position size before known high-volatility events (EIA reports, OPEC meetings, expiry dates).",
        "purpose": (
            "Accepts a list of CatalystEvents with dates and pre-event windows (e.g. reduce "
            "48 hours before an EIA report). When you enter the window, it queues a reduce-only "
            "order to cut exposure by the configured percentage. This prevents a scheduled "
            "news event from blowing out a leveraged position before you can react. "
            "After the event window passes, you can re-size manually or let the conviction engine do it."
        ),
        "kill_switch_impact": (
            "No automatic deleverage before scheduled events. EIA reports, OPEC decisions, "
            "and futures expiry dates arrive at full leverage. You must manually reduce exposure "
            "before each event or accept the volatility risk."
        ),
        "inputs": ["data/daemon/external_catalyst_events.json", "TickContext positions"],
        "outputs": ["Reduce-only OrderIntents", "Telegram alerts (pre-event warnings)"],
        "category": "Trading",
    },

    "apex_advisor": {
        "description": "Scans radar signals and pulse data each tick to propose (or execute) high-confidence trade ideas.",
        "purpose": (
            "Reads radar_opportunities and pulse_signals generated by the radar and pulse "
            "iterators, runs them through the ApexEngine, and outputs trade proposals. "
            "In DRY-RUN mode (default) it sends proposals to Telegram for your review — "
            "no trades are placed. In LIVE mode (enable via apex_executor.json) it converts "
            "proposals to real OrderIntents. This is signal-driven trading, distinct from "
            "the thesis-driven execution_engine path."
        ),
        "kill_switch_impact": (
            "Signal-driven trade proposals stop appearing in Telegram. The radar and pulse "
            "iterators still run and generate signals, but nobody acts on them. "
            "In dry-run mode this just means lost visibility; in live mode it stops automated signal trading."
        ),
        "inputs": ["data/research/signals.jsonl (radar + pulse output)", "data/config/apex_executor.json"],
        "outputs": ["Telegram trade proposals (dry-run) OR OrderIntents (live)", "TickContext alert queue"],
        "category": "Trading",
    },

    "oil_botpattern": {
        "description": "The oil bot-pattern strategy engine — the ONLY place in the codebase where shorting oil is legal.",
        "purpose": (
            "Sub-system 5 of the Oil Bot-Pattern Strategy. Reads outputs of sub-systems 1-4 "
            "(news catalysts, supply state, liquidity heatmap, bot classifier) plus current "
            "thesis conviction and funding costs, then runs a multi-gate decision chain. "
            "In shadow mode (WATCH tier) it logs decisions but places no orders. "
            "In live mode (REBALANCE+) it opens long or short oil positions with Druckenmiller-style "
            "conviction sizing. Two master kill switches must BOTH be on for any short to fire."
        ),
        "kill_switch_impact": (
            "All oil bot-pattern trades stop. The strategy engine still ticks (in shadow mode in WATCH) "
            "but emits no OrderIntents. Sub-systems 1-4 keep running and collecting data. "
            "Oil positions opened by other paths (thesis engine, manual) are unaffected."
        ),
        "inputs": ["data/news/catalysts.jsonl", "data/supply/state.json", "data/heatmap/", "data/research/bot_patterns.jsonl", "data/config/oil_botpattern.json"],
        "outputs": ["data/strategy/oil_botpattern_journal.jsonl", "data/strategy/oil_botpattern_state.json", "OrderIntents (REBALANCE+ only)", "Telegram alerts"],
        "category": "Trading",
    },

    # ── Intelligence ──────────────────────────────────────────────────────────
    "thesis_engine": {
        "description": "Loads the latest AI conviction scores from thesis files into the tick context so trading decisions are AI-informed.",
        "purpose": (
            "This is the bridge between the AI scheduled task (which writes thesis state files) "
            "and the execution engine (which reads them). Each tick it loads thesis files from "
            "disk and injects them into TickContext.thesis_states. Handles staleness: conviction "
            "tapers linearly after 7 days and reaches minimum after 14 days. "
            "Without it, the execution engine uses default (zero) conviction."
        ),
        "kill_switch_impact": (
            "The execution engine operates with zero conviction for all markets. "
            "No thesis-informed position sizing. The AI's research stops influencing trade size."
        ),
        "inputs": ["data/thesis/*_state.json (AI-written thesis files)"],
        "outputs": ["TickContext thesis_states", "TickContext effective_conviction per market"],
        "category": "Intelligence",
    },

    "thesis_challenger": {
        "description": "Watches incoming news catalysts and immediately alerts you when something directly contradicts your open thesis.",
        "purpose": (
            "Pure Python, zero AI calls. Runs every 5 minutes. Pattern-matches new catalyst "
            "headlines against invalidation conditions defined in each thesis file. "
            "When a catalyst matches an invalidation rule (e.g. 'ceasefire announced' when your "
            "BRENTOIL thesis depends on supply disruption) it fires a CRITICAL Telegram alert immediately. "
            "This is your early warning for thesis-breaking news."
        ),
        "kill_switch_impact": (
            "Thesis invalidation alerts go silent. News that should trigger a position review "
            "passes undetected. You may hold a position through conditions that explicitly "
            "invalidate your original thesis."
        ),
        "inputs": ["data/news/catalysts.jsonl", "data/thesis/*_state.json (invalidation_conditions field)"],
        "outputs": ["CRITICAL Telegram alerts", "TickContext alert queue"],
        "category": "Intelligence",
    },

    "thesis_updater": {
        "description": "Uses Claude Haiku to classify incoming news and automatically nudge thesis conviction up or down.",
        "purpose": (
            "Runs every 5 minutes. Reads new catalysts, sends them to Haiku for severity "
            "classification (1-10), then applies tiered conviction adjustments: small nudges "
            "for routine news, large moves for critical events (severity 9-10 triggers instant "
            "defensive mode). Guardrails limit how much conviction can shift per event (±15%) "
            "and per day (±30%). Weekend news is dampened by 50%."
        ),
        "kill_switch_impact": (
            "Thesis conviction never auto-adjusts. News events — including critical ones — "
            "don't propagate to thesis files. The AI scheduled task can still update conviction "
            "manually, but the fast (5-minute) reaction loop is gone."
        ),
        "inputs": ["data/news/catalysts.jsonl", "data/thesis/*_state.json", "Claude Haiku API (via session token)"],
        "outputs": ["data/thesis/*_state.json (updated conviction)", "data/thesis/audit.jsonl", "data/thesis/news_log.jsonl"],
        "category": "Intelligence",
    },

    "news_ingest": {
        "description": "Polls RSS feeds and news sources every 60 seconds and writes structured catalyst events to disk.",
        "purpose": (
            "Sub-system 1 of the Oil Bot-Pattern Strategy. Reads configured RSS feeds for "
            "oil, geopolitics, and macro news. For each new headline it runs NLP severity "
            "scoring (1-10) and writes catalysts to data/news/catalysts.jsonl. "
            "This file is the primary input for thesis_challenger, thesis_updater, supply_ledger, "
            "bot_classifier, and catalyst_deleverage. It is the top of the information funnel."
        ),
        "kill_switch_impact": (
            "No new news enters the system. Thesis challenger stops catching invalidating events. "
            "Thesis updater can't adjust conviction. Supply ledger can't detect new disruptions. "
            "Bot classifier loses catalyst context. The entire news-driven decision layer goes stale."
        ),
        "inputs": ["Configured RSS feeds (oil, geopolitics, macro)", "data/calendar/brent_rollover.json"],
        "outputs": ["data/news/headlines.jsonl", "data/news/catalysts.jsonl"],
        "category": "Intelligence",
    },

    "supply_ledger": {
        "description": "Tracks active physical oil supply disruptions and maintains a running supply state score for the strategy engine.",
        "purpose": (
            "Sub-system 2 of the Oil Bot-Pattern Strategy. Watches catalysts.jsonl for "
            "physical_damage, shipping_attack, and chokepoint_blockade events, extracts "
            "Disruption records, and periodically recomputes a SupplyState score. "
            "The oil_botpattern strategy uses this score as a key input to its gate chain. "
            "Manual disruptions can also be added via the /disrupt Telegram command."
        ),
        "kill_switch_impact": (
            "Supply disruption state goes stale. The oil bot-pattern strategy's supply gate "
            "uses an outdated or empty supply score. New physical disruptions (pipeline attacks, "
            "chokepoint closures) won't feed into trade decisions."
        ),
        "inputs": ["data/news/catalysts.jsonl", "data/supply/manual_disruptions.jsonl (Telegram /disrupt command)"],
        "outputs": ["data/supply/state.json", "data/supply/disruptions.jsonl"],
        "category": "Intelligence",
    },

    "heatmap": {
        "description": "Maps where large buy and sell orders are clustered in the order book, and detects liquidation cascades.",
        "purpose": (
            "Sub-system 3 of the Oil Bot-Pattern Strategy. Polls HyperLiquid L2 order book "
            "data for configured oil instruments, clusters resting liquidity into price zones, "
            "and monitors open interest + funding changes for liquidation cascade signatures. "
            "The oil_botpattern strategy uses zone data for entry timing. "
            "Also used by the chart overlay page to display liquidity zones visually."
        ),
        "kill_switch_impact": (
            "Liquidity zone data goes stale. The oil bot-pattern strategy loses order-book "
            "context for entry timing. Chart overlays stop updating. Cascade alerts go silent."
        ),
        "inputs": ["HyperLiquid API (l2Book, metaAndAssetCtxs)", "data/config/heatmap.json"],
        "outputs": ["data/heatmap/zones.jsonl", "data/heatmap/cascades.jsonl", "Telegram alerts (cascade detections)"],
        "category": "Intelligence",
    },

    "bot_classifier": {
        "description": "Classifies recent oil price moves as bot-driven, informed, mixed, or unclear — identifies whether algos are pushing price.",
        "purpose": (
            "Sub-system 4 of the Oil Bot-Pattern Strategy. Combines catalyst events (#1), "
            "supply state (#2), liquidation cascades (#3), and raw candle + ATR data to "
            "classify the nature of each significant move. This classification feeds the "
            "oil_botpattern strategy engine's gate chain. "
            "Purely heuristic — no ML, no LLM. Results written to data/research/bot_patterns.jsonl."
        ),
        "kill_switch_impact": (
            "Bot pattern data goes stale. The oil bot-pattern strategy (#5) loses its "
            "most important input and will likely skip its gate chain (pattern gate fails). "
            "You lose visibility into whether institutional bots or genuine flows are driving oil moves."
        ),
        "inputs": ["data/news/catalysts.jsonl", "data/supply/state.json", "data/heatmap/cascades.jsonl", "TickContext candles", "data/config/bot_classifier.json"],
        "outputs": ["data/research/bot_patterns.jsonl", "Telegram alerts (significant patterns)"],
        "category": "Intelligence",
    },

    "radar": {
        "description": "Scans all tracked markets for emerging trade opportunities using technical analysis, then stores them for the apex_advisor.",
        "purpose": (
            "Wraps the RadarEngine to run a multi-instrument opportunity scan each tick. "
            "Looks for momentum, structure, and confluence signals across BTC, BRENTOIL, GOLD, SILVER. "
            "When a significant opportunity is detected it writes a signal to data/research/signals.jsonl "
            "and the apex_advisor picks it up within the same tick. "
            "Active in WATCH and OPPORTUNISTIC tiers — read-only, no trade execution."
        ),
        "kill_switch_impact": (
            "Signal-driven trade proposals from apex_advisor stop appearing. "
            "Radar opportunities accumulate nowhere. The apex_advisor has no inputs to work from. "
            "Thesis-driven execution (execution_engine) is unaffected."
        ),
        "inputs": ["TickContext prices, candles (from connector)", "TickContext market_snapshots (from market_structure_iter)"],
        "outputs": ["data/research/signals.jsonl", "TickContext radar_opportunities"],
        "category": "Intelligence",
    },

    "pulse": {
        "description": "Detects capital inflow momentum — measures whether 'smart money' is positioning before a move.",
        "purpose": (
            "Wraps the PulseEngine to detect momentum and capital flow signals. Tracks whether "
            "volume, OI, and price acceleration patterns suggest institutional accumulation. "
            "Persists signals to data/research/signals.jsonl (same file as radar, different type tag). "
            "The apex_advisor reads both radar and pulse signals. "
            "Read-only, active in WATCH and OPPORTUNISTIC."
        ),
        "kill_switch_impact": (
            "Pulse-type signals (momentum/flow) disappear from the apex_advisor feed. "
            "Radar signals still reach it. You lose the capital inflow detection layer of "
            "the apex signal stack."
        ),
        "inputs": ["TickContext prices, candles (from connector)", "data/research/signals.jsonl (read for history)"],
        "outputs": ["data/research/signals.jsonl (pulse signals appended)", "TickContext pulse_signals"],
        "category": "Intelligence",
    },

    "market_structure_iter": {
        "description": "Pre-computes technical indicators (RSI, ATR, structure levels) every 5 minutes so other iterators don't repeat the work.",
        "purpose": (
            "Runs after connector (needs prices) and before thesis_engine and execution_engine. "
            "Computes ATR, RSI, support/resistance levels, and market structure labels for every "
            "tracked instrument. Writes results to TickContext.market_snapshots. "
            "The 5-minute cadence (not every 60s tick) keeps compute overhead manageable — "
            "indicators don't change meaningfully on 60-second intervals."
        ),
        "kill_switch_impact": (
            "Downstream iterators compute their own technicals (slower, inconsistent) or "
            "fail gracefully with None values. Entry critic, execution engine, and apex advisor "
            "all degrade in quality without pre-computed market structure."
        ),
        "inputs": ["TickContext candles (from connector)", "TickContext prices"],
        "outputs": ["TickContext market_snapshots (ATR, RSI, structure levels per instrument)"],
        "category": "Intelligence",
    },

    "brent_rollover_monitor": {
        "description": "Alerts you at 7, 3, and 1 day before each Brent futures contract rolls — important for managing xyz:BRENTOIL positions.",
        "purpose": (
            "HyperLiquid's xyz:BRENTOIL perpetual tracks ICE Brent futures. During contract "
            "rollover (when the front-month contract expires), the Brent benchmark can price "
            "dislocate from physical, causing unusual funding rates and price gaps. "
            "This iterator reads a user-maintained calendar and fires T-7, T-3, and T-1 alerts "
            "so you can reduce exposure or prepare ahead of the roll."
        ),
        "kill_switch_impact": (
            "No rollover warnings. Brent contract expiry arrives without notice. "
            "Unusual funding or price dislocations during roll periods will catch you by surprise."
        ),
        "inputs": ["data/calendar/brent_rollover.json (user-maintained calendar)"],
        "outputs": ["Telegram alerts (T-7, T-3, T-1 warnings)", "TickContext alert queue"],
        "category": "Intelligence",
    },

    "price_move_alert": {
        "description": "Sends an alert when any tracked market moves more than a configurable threshold in 5 minutes, 1 hour, or 24 hours.",
        "purpose": (
            "Monitors tracked markets (core positions + watchlist) across three time windows. "
            "Each window can be configured with either a flat percentage threshold or an "
            "ATR-relative threshold (e.g. alert at 1.5× ATR in 5 minutes). "
            "Fires Telegram alerts so you know when market conditions are moving fast enough "
            "to review your position even outside a scheduled check-in."
        ),
        "kill_switch_impact": (
            "Big price move alerts go silent. You won't receive proactive notification when "
            "a market makes a significant move outside your check-in schedule. "
            "Your open positions are still monitored for liquidation — just not big-move context."
        ),
        "inputs": ["TickContext prices, candles (from connector)", "data/config/price_move_alert.json", "data/config/watchlist.json"],
        "outputs": ["Telegram alerts", "TickContext alert queue"],
        "category": "Intelligence",
    },

    "funding_tracker": {
        "description": "Tracks the cumulative funding fees paid on each position — shows your real cost of holding leveraged perps.",
        "purpose": (
            "HyperLiquid perpetuals charge or pay funding every hour. For leveraged oil and "
            "BTC positions, this adds up fast. The tracker estimates each payment on a "
            "throttled schedule and maintains a running tally. "
            "The oil_botpattern strategy reads funding history to decide whether funding cost "
            "has consumed enough of a long's theoretical edge to warrant closing."
        ),
        "kill_switch_impact": (
            "Cumulative funding cost tracking stops. The oil_botpattern funding exit gate "
            "will use stale data. You lose the running cost-of-carry view on open positions."
        ),
        "inputs": ["HyperLiquid API (funding rates)", "TickContext positions"],
        "outputs": ["data/daemon/funding_tracker.jsonl", "TickContext funding_costs"],
        "category": "Intelligence",
    },

    # ── Self-Improvement ───────────────────────────────────────────────────────
    "autoresearch": {
        "description": "Reviews past trade execution quality every 30 minutes and files findings to improve future decisions.",
        "purpose": (
            "Runs a Karpathy-style learning loop: evaluates trade execution across sizing "
            "alignment, stop quality, funding efficiency, and catalyst timing. "
            "Files structured research findings that the AI reads during its next scheduled "
            "evaluation. This is how the system learns from its own mistakes without human input. "
            "Runs every 30 minutes for faster iteration than a daily loop."
        ),
        "kill_switch_impact": (
            "Autonomous execution quality review stops. The learning loop stalls — "
            "past mistakes are not systematically reviewed or filed. The AI's next "
            "evaluation has less quality feedback to draw from."
        ),
        "inputs": ["data/research/journal.jsonl (closed trades)", "TickContext positions, equity"],
        "outputs": ["data/research/autoresearch_*.jsonl", "Telegram alerts (significant findings)"],
        "category": "Self-improvement",
    },

    "journal": {
        "description": "Detects when positions close and writes a full trade journal entry with entry/exit/P&L/SL/TP details.",
        "purpose": (
            "Tracks positions across ticks. When a position disappears or flips direction it "
            "creates a JournalEntry with complete trade context and persists it via JournalGuard. "
            "Also writes tick snapshots for post-mortem replay. "
            "This is the source of truth for closed trades — lesson_author, autoresearch, "
            "and the /journal command all read from here."
        ),
        "kill_switch_impact": (
            "Closed trades are not recorded. The lesson layer (lesson_author → lesson_consumer) "
            "has nothing to work from. Autoresearch loses its closed-trade feed. "
            "/journal commands return stale data."
        ),
        "inputs": ["TickContext positions (tick-over-tick comparison)", "TickContext prices"],
        "outputs": ["data/research/journal.jsonl", "data/daemon/journal/ticks-YYYYMMDD.jsonl (snapshots)"],
        "category": "Self-improvement",
    },

    "lesson_author": {
        "description": "Detects closed positions and assembles the raw material (trade details, thesis snapshot, notes) for a post-mortem lesson — no AI calls.",
        "purpose": (
            "Purely deterministic — no LLM. Watches journal.jsonl for new closed trades "
            "and assembles a structured candidate file containing: the JournalEntry, "
            "the active thesis snapshot at trade time, and relevant learnings. "
            "Writes the candidate to data/daemon/lesson_candidates/ where lesson_consumer "
            "picks it up and calls the AI to write the actual post-mortem."
        ),
        "kill_switch_impact": (
            "No lesson candidate files are created. Lesson_consumer has nothing to process. "
            "The post-mortem loop stalls at the first stage. Past trades generate no lessons."
        ),
        "inputs": ["data/research/journal.jsonl", "data/thesis/*_state.json", "data/memory/learnings.md"],
        "outputs": ["data/daemon/lesson_candidates/*.json"],
        "category": "Self-improvement",
    },

    "lesson_consumer": {
        "description": "Picks up lesson candidate files and calls Claude to write a structured post-mortem, then saves it to the lessons database.",
        "purpose": (
            "Wedge 6 of the trade lesson layer. Scans lesson_candidates/ for pending files "
            "written by lesson_author and calls the agent to author a structured post-mortem "
            "for each one. The authored lesson is persisted to the FTS5 lessons table in "
            "data/memory/memory.db where the AI can search it via the /lessons command. "
            "Ships with kill switch OFF — AI costs real tokens."
        ),
        "kill_switch_impact": (
            "Lesson candidate files accumulate unprocessed. No new post-mortems are authored. "
            "The AI's searchable lessons database stops growing. "
            "The lesson_author iterator is unaffected and will keep creating candidates."
        ),
        "inputs": ["data/daemon/lesson_candidates/*.json", "Claude AI (session token)"],
        "outputs": ["data/memory/memory.db (lessons table, FTS5 indexed)", "Telegram alerts (lesson authored)"],
        "category": "Self-improvement",
    },

    "entry_critic": {
        "description": "Grades every new trade entry on sizing, direction, catalyst timing, liquidity, and funding — immediately, with no AI.",
        "purpose": (
            "Watches positions each tick and fires a deterministic critique the first time "
            "a new position fingerprint appears. Grades are: GREAT / GOOD / MIXED ENTRY / "
            "RISKY with specific reasons. Persists to data/research/entry_critiques.jsonl "
            "and fires a Telegram alert. The lesson layer uses the critique when authoring "
            "the post-mortem later."
        ),
        "kill_switch_impact": (
            "Entry quality grades stop being issued. You won't see immediate feedback on "
            "new positions. The lesson layer still works but loses entry critique context "
            "for its post-mortems."
        ),
        "inputs": ["TickContext positions (new entry detection)", "TickContext market_snapshots (ATR, RSI)", "data/thesis/*_state.json"],
        "outputs": ["data/research/entry_critiques.jsonl", "Telegram alerts (per new entry)"],
        "category": "Self-improvement",
    },

    "memory_consolidation": {
        "description": "Compresses old memory events into bounded summaries every hour so the AI's context stays manageable as history grows.",
        "purpose": (
            "The memory database grows continuously as events, observations, and action_log "
            "entries accumulate. Without consolidation the AI would need to read an ever-growing "
            "corpus. This iterator runs hourly and merges older events into compact summaries, "
            "keeping context size bounded. Runs infrequently to avoid wasting cycles."
        ),
        "kill_switch_impact": (
            "Memory grows unbounded. Over time (weeks/months) the AI's context fills with "
            "raw events rather than summaries. Retrieval quality degrades. "
            "No immediate impact, but the problem compounds over time."
        ),
        "inputs": ["data/memory/memory.db (events table)"],
        "outputs": ["data/memory/memory.db (consolidated summaries written, old events pruned)"],
        "category": "Self-improvement",
    },

    "memory_backup": {
        "description": "Takes an atomic hourly snapshot of the lessons database — your only backup against database corruption.",
        "purpose": (
            "The entire lessons corpus, consolidated events, observations, and action log "
            "live in one SQLite file. A single corrupt write or accidental delete loses "
            "everything. This iterator runs hourly and writes an atomic copy to "
            "data/snapshots/memory_backup_*.db. Keeps the last N backups (configurable)."
        ),
        "kill_switch_impact": (
            "No backups are taken. The memory database is a single point of failure with "
            "no protection. A crash, schema migration error, or accidental delete permanently "
            "destroys all lessons, consolidated events, and the action log."
        ),
        "inputs": ["data/memory/memory.db"],
        "outputs": ["data/snapshots/memory_backup_YYYYMMDD_HHMMSS.db"],
        "category": "Self-improvement",
    },

    "action_queue": {
        "description": "Daily sweep of your operator ritual queue — checks pending tasks, lesson reviews, and backup health.",
        "purpose": (
            "Runs once per day inside the daemon clock. Reads the action queue ledger "
            "(data/research/action_queue.jsonl), auto-updates fields it can verify "
            "(pending lesson count from DB, backup freshness from file mtime), and fires "
            "a Telegram digest of items due for review. "
            "This is the mechanism behind the /nudge Telegram command."
        ),
        "kill_switch_impact": (
            "Daily operator digest stops. Pending lesson reviews, backup health checks, "
            "and other ritual items won't prompt you automatically. "
            "The /nudge command still works on demand."
        ),
        "inputs": ["data/research/action_queue.jsonl", "data/memory/memory.db (lesson count)", "data/snapshots/ (backup mtime)"],
        "outputs": ["Telegram daily digest", "Updated action_queue.jsonl (auto-fields)"],
        "category": "Operations",
    },

    # ── Oil Bot Self-Tune (sub-system 6) ──────────────────────────────────────
    "oil_botpattern_tune": {
        "description": "Automatically fine-tunes the oil bot-pattern strategy parameters within safe bounds based on closed trade results.",
        "purpose": (
            "Sub-system 6 Layer 1. Watches closed oil_botpattern trades and the decision "
            "journal, then makes small bounded adjustments to strategy parameters (entry "
            "thresholds, conviction multipliers) when the data supports it. "
            "Each parameter has a rate limit (max N changes per week) and a hard min/max range. "
            "Changes are logged to an audit trail. Ships with kill switch OFF."
        ),
        "kill_switch_impact": (
            "Bounded auto-tune stops. The oil_botpattern strategy parameters stay fixed "
            "at their last values. Sub-system 5 still trades; it just won't self-calibrate."
        ),
        "inputs": ["data/research/journal.jsonl (oil_botpattern trades)", "data/strategy/oil_botpattern_journal.jsonl", "data/config/oil_botpattern.json"],
        "outputs": ["data/config/oil_botpattern.json (updated params)", "data/strategy/oil_botpattern_tune_audit.jsonl"],
        "category": "Self-improvement",
    },

    "oil_botpattern_reflect": {
        "description": "Weekly structural review of the oil bot-pattern strategy — proposes rule changes for your approval before anything is applied.",
        "purpose": (
            "Sub-system 6 Layer 2. Runs once per week. Reads closed-trade stream and "
            "decision journal to detect structural patterns the L1 bounded tune can't fix: "
            "e.g. 'all shorts in contango markets lose money' or 'false-positive rate doubles "
            "during rollover week'. Appends StructuralProposal records to a proposals JSONL "
            "and fires a Telegram warning. L2 NEVER auto-applies — all proposals start "
            "status=pending and require /selftune review."
        ),
        "kill_switch_impact": (
            "Weekly structural proposals stop being generated. Systematic patterns that "
            "L1 auto-tune can't address accumulate undetected. Manual review is still "
            "possible but won't have automated proposals to prompt it."
        ),
        "inputs": ["data/research/journal.jsonl", "data/strategy/oil_botpattern_journal.jsonl"],
        "outputs": ["data/strategy/oil_botpattern_proposals.jsonl (status=pending)", "Telegram alerts"],
        "category": "Self-improvement",
    },

    "oil_botpattern_patternlib": {
        "description": "Grows a library of recurring bot-pattern signatures from live data — identifies patterns that appear consistently enough to trade.",
        "purpose": (
            "Sub-system 6 Layer 3. Watches data/research/bot_patterns.jsonl for new "
            "classification records, detects novel signatures (classification + direction + "
            "confidence band + signals), and tallies their occurrences in a rolling window. "
            "When a signature crosses min_occurrences, it writes a PatternCandidate to "
            "bot_pattern_candidates.jsonl for the strategy engine to use. "
            "Purely observational — never places trades."
        ),
        "kill_switch_impact": (
            "The pattern candidate library stops growing. The oil_botpattern strategy "
            "loses access to newly discovered recurring patterns. "
            "Existing patterns in the library are unaffected."
        ),
        "inputs": ["data/research/bot_patterns.jsonl (from bot_classifier)"],
        "outputs": ["data/research/bot_pattern_candidates.jsonl"],
        "category": "Self-improvement",
    },

    "oil_botpattern_shadow": {
        "description": "Runs 'what would have happened' counterfactual replays on approved strategy proposals before they go live.",
        "purpose": (
            "Sub-system 6 Layer 4. Scans oil_botpattern_proposals.jsonl for approved (but "
            "not yet live-tested) proposals. For each one, replays the proposal's rule change "
            "against the recent decision + trade window to estimate its impact: win rate "
            "change, sizing effect, risk-adjusted return delta. Writes a ShadowEval record "
            "and attaches it to the proposal. This is the last gate before a structural "
            "proposal gets merged into config."
        ),
        "kill_switch_impact": (
            "Shadow evaluation stops. Approved proposals can still be merged manually "
            "but won't have counterfactual validation. You lose the 'simulate before applying' "
            "safety check on structural strategy changes."
        ),
        "inputs": ["data/strategy/oil_botpattern_proposals.jsonl (approved proposals)", "data/research/journal.jsonl", "data/strategy/oil_botpattern_journal.jsonl"],
        "outputs": ["data/strategy/oil_botpattern_shadow_evals.jsonl", "Updated proposals (shadow_eval field)"],
        "category": "Self-improvement",
    },

    # ── Operations ────────────────────────────────────────────────────────────
    "lab": {
        "description": "Runs the strategy development pipeline — advances experiments from backtest to paper trading to graduated status.",
        "purpose": (
            "Drives the Lab Engine: checks which experiments are ready to advance, fires "
            "Telegram alerts on graduation events, and collects paper trading signals for "
            "active paper experiments. Ships with enabled=false — zero production impact "
            "unless explicitly turned on. Registered in all tiers (read-only + paper only, "
            "no real orders ever)."
        ),
        "kill_switch_impact": (
            "Strategy experiment progression stops. Experiments already in the pipeline "
            "stay at their current stage. No real trading is affected — the lab is "
            "entirely sandboxed from live execution."
        ),
        "inputs": ["Lab Engine experiment registry", "TickContext prices (for paper trading)"],
        "outputs": ["Telegram graduation alerts", "Paper trading signal records"],
        "category": "Operations",
    },
}

# ── Category map (for iterators not in the curated list above) ─────────────
# Used as a fallback when building the full iterator list from docstrings.
CATEGORY_FALLBACK: dict[str, str] = {
    "account_collector": "Operations",
    "connector": "Operations",
    "telegram": "Operations",
    "action_queue": "Operations",
    "memory_backup": "Self-improvement",
    "lab": "Operations",
    "liquidation_monitor": "Safety",
    "exchange_protection": "Safety",
    "guard": "Safety",
    "protection_audit": "Safety",
    "risk": "Safety",
    "portfolio_risk_monitor": "Safety",
    "profit_lock": "Safety",
    "liquidity": "Safety",
    "execution_engine": "Trading",
    "rebalancer": "Trading",
    "catalyst_deleverage": "Trading",
    "apex_advisor": "Trading",
    "oil_botpattern": "Trading",
    "thesis_engine": "Intelligence",
    "thesis_challenger": "Intelligence",
    "thesis_updater": "Intelligence",
    "news_ingest": "Intelligence",
    "supply_ledger": "Intelligence",
    "heatmap": "Intelligence",
    "bot_classifier": "Intelligence",
    "radar": "Intelligence",
    "pulse": "Intelligence",
    "market_structure_iter": "Intelligence",
    "market_structure": "Intelligence",
    "brent_rollover_monitor": "Intelligence",
    "price_move_alert": "Intelligence",
    "funding_tracker": "Intelligence",
    "autoresearch": "Self-improvement",
    "journal": "Self-improvement",
    "lesson_author": "Self-improvement",
    "lesson_consumer": "Self-improvement",
    "entry_critic": "Self-improvement",
    "memory_consolidation": "Self-improvement",
    "oil_botpattern_tune": "Self-improvement",
    "oil_botpattern_reflect": "Self-improvement",
    "oil_botpattern_patternlib": "Self-improvement",
    "oil_botpattern_shadow": "Self-improvement",
}
