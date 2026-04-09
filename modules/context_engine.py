"""Context Engine — pre-LLM context assembly for Telegram and any AI interface.

The problem: when a user sends "how's my oil position?", the LLM currently
gets just that raw text with ZERO context. No positions, no thesis, no
market data, no recent trades.

The fix: before the LLM sees anything, this engine:
  1. Classifies the message intent (position query, market analysis, system health, etc.)
  2. Based on intent, fetches relevant data from all existing sources
  3. Assembles a structured context document
  4. Returns it ready for the LLM

This uses the WorkflowEngine to compose fetch steps dynamically —
a position question fetches positions + thesis + recent P&L,
while a market question fetches prices + candles + radar scores.

The LLM is FORCED to consume relevant data. Not by prompt engineering,
but by literally putting the data in front of it before it answers.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests

from modules.workflow_engine import WorkflowContext, WorkflowEngine, WorkflowStep

log = logging.getLogger("context_engine")

HL_API = "https://api.hyperliquid.xyz/info"
MAIN_ADDR = "0x80B5801ce295C4D469F4c0C2e7E17bd84dF0F205"

# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

INTENT_KEYWORDS = {
    "position_query": [
        "position", "trade", "exposure", "long", "short", "pnl", "profit",
        "loss", "entry", "stop", "liquidation", "liq", "upnl",
    ],
    "market_analysis": [
        "price", "chart", "trend", "momentum", "support", "resistance",
        "volume", "oi", "open interest", "funding", "squeeze", "breakout",
        "technical", "analysis", "market", "bullish", "bearish",
    ],
    "strategy_query": [
        "strategy", "backtest", "radar", "pulse", "apex", "signal",
        "opportunity", "scan", "lab", "experiment",
    ],
    "system_health": [
        "status", "daemon", "error", "bug", "issue", "health", "running",
        "circuit", "breaker", "tier", "gate", "risk",
    ],
    "thesis_query": [
        "thesis", "conviction", "direction", "why", "reasoning", "evidence",
        "invalidation", "bull case", "bear case",
    ],
    "performance_review": [
        "review", "reflect", "performance", "win rate", "sharpe",
        "drawdown", "improvement", "learn", "mistake", "how did",
        "last week", "last month", "results", "track record",
    ],
    "general": [],  # fallback
}

# Which data to fetch per intent
INTENT_DATA_NEEDS: Dict[str, List[str]] = {
    "position_query": [
        "fetch_positions", "fetch_account", "fetch_thesis",
        "fetch_recent_trades", "fetch_guard_state",
    ],
    "market_analysis": [
        "fetch_prices", "fetch_thesis", "fetch_radar_latest",
        "fetch_liquidity_regime",
    ],
    "strategy_query": [
        "fetch_positions", "fetch_radar_latest", "fetch_lab_status",
        "fetch_strategies",
    ],
    "system_health": [
        "fetch_account", "fetch_issues", "fetch_daemon_status",
        "fetch_liquidity_regime",
    ],
    "thesis_query": [
        "fetch_thesis", "fetch_positions", "fetch_learnings",
    ],
    "performance_review": [
        "fetch_recent_trades", "fetch_learnings", "fetch_reflect_latest",
        "fetch_positions",
    ],
    "general": [
        "fetch_account", "fetch_positions", "fetch_thesis",
        "fetch_liquidity_regime",
    ],
}


def classify_intent(message: str) -> str:
    """Classify message intent based on keyword matching."""
    text = message.lower()
    scores: Dict[str, int] = {}
    for intent, keywords in INTENT_KEYWORDS.items():
        scores[intent] = sum(1 for kw in keywords if kw in text)
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "general"
    return best


# ---------------------------------------------------------------------------
# Workflow steps — each fetches one data domain
# ---------------------------------------------------------------------------

class ClassifyIntentStep(WorkflowStep):
    name = "classify_intent"
    inputs = {"user_message"}
    outputs = {"intent", "intent_steps"}

    def execute(self, ctx: WorkflowContext) -> None:
        msg = ctx.get("user_message", "")
        intent = classify_intent(msg)
        steps = INTENT_DATA_NEEDS.get(intent, INTENT_DATA_NEEDS["general"])
        ctx.set("intent", intent)
        ctx.set("intent_steps", steps)
        log.info("Intent: %s (message: %s)", intent, msg[:60])


class FetchPositionsStep(WorkflowStep):
    name = "fetch_positions"
    outputs = {"positions_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        positions = []
        for dex in ["", "xyz"]:
            payload = {"type": "clearinghouseState", "user": MAIN_ADDR}
            if dex:
                payload["dex"] = dex
            try:
                state = requests.post(HL_API, json=payload, timeout=8).json()
                for p in state.get("assetPositions", []):
                    pos = p.get("position", {})
                    pos["_dex"] = dex or "native"
                    positions.append(pos)
            except Exception as e:
                log.debug("Position fetch (%s) failed: %s", dex or "native", e)

        if positions:
            lines = []
            for pos in positions:
                coin = pos.get("coin", "?")
                size = pos.get("szi", "0")
                entry = pos.get("entryPx", "0")
                upnl = pos.get("unrealizedPnl", "0")
                lev = pos.get("leverage", {})
                liq = pos.get("liquidationPx", "N/A")
                lev_val = lev.get("value", "?") if isinstance(lev, dict) else lev
                lines.append(
                    f"  {coin}: size={size} entry=${entry} "
                    f"uPnL=${upnl} lev={lev_val}x liq=${liq}"
                )
            ctx.set("positions_context", "POSITIONS:\n" + "\n".join(lines))
        else:
            ctx.set("positions_context", "POSITIONS: None open")


class FetchAccountStep(WorkflowStep):
    name = "fetch_account"
    outputs = {"account_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        parts = []
        total = 0.0
        for dex in ["", "xyz"]:
            payload = {"type": "clearinghouseState", "user": MAIN_ADDR}
            if dex:
                payload["dex"] = dex
            try:
                state = requests.post(HL_API, json=payload, timeout=8).json()
                val = float(state.get("marginSummary", {}).get("accountValue", 0))
                label = dex or "native"
                parts.append(f"  {label}: ${val:,.2f}")
                total += val
            except Exception:
                pass

        # Spot
        try:
            spot = requests.post(HL_API, json={"type": "spotClearinghouseState", "user": MAIN_ADDR}, timeout=8).json()
            for b in spot.get("balances", []):
                t = float(b.get("total", 0))
                if t > 0.01:
                    coin = b["coin"]
                    parts.append(f"  spot {coin}: ${t:,.2f}" if coin == "USDC" else f"  spot {coin}: {t:.4f}")
                    if coin == "USDC":
                        total += t
        except Exception:
            pass

        parts.insert(0, f"ACCOUNT (total ~${total:,.2f}):")
        ctx.set("account_context", "\n".join(parts))


class FetchThesisStep(WorkflowStep):
    name = "fetch_thesis"
    outputs = {"thesis_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        thesis_dir = Path("data/thesis")
        if not thesis_dir.exists():
            ctx.set("thesis_context", "THESIS: No thesis files found")
            return

        lines = ["THESIS STATE:"]
        for f in sorted(thesis_dir.glob("*_state.json")):
            try:
                data = json.loads(f.read_text())
                market = data.get("market", f.stem)
                direction = data.get("direction", "?")
                conviction = data.get("conviction", 0)
                summary = data.get("thesis_summary", "")[:200]
                age_h = 0
                last_eval = data.get("last_evaluation_ts", 0)
                if last_eval:
                    age_h = (time.time() * 1000 - last_eval) / 3_600_000
                lines.append(
                    f"  {market}: {direction} conviction={conviction:.2f} "
                    f"age={age_h:.1f}h"
                )
                if summary:
                    lines.append(f"    {summary}")
                # Invalidation conditions
                inv = data.get("invalidation_conditions", [])
                if inv:
                    lines.append(f"    Invalidation: {'; '.join(inv[:3])}")
            except Exception:
                pass

        ctx.set("thesis_context", "\n".join(lines) if len(lines) > 1 else "THESIS: No active theses")


class FetchPricesStep(WorkflowStep):
    name = "fetch_prices"
    outputs = {"prices_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        try:
            mids = requests.post(HL_API, json={"type": "allMids"}, timeout=8).json()
            # Get the markets we care about
            watchlist = ["BTC", "ETH", "SOL"]
            xyz_markets = ["xyz:BRENTOIL", "xyz:GOLD", "xyz:NATGAS", "xyz:SP500"]

            lines = ["PRICES:"]
            for coin in watchlist:
                if coin in mids:
                    lines.append(f"  {coin}: ${float(mids[coin]):,.2f}")

            for coin in xyz_markets:
                try:
                    book = requests.post(HL_API, json={"type": "l2Book", "coin": coin}, timeout=5).json()
                    levels = book.get("levels", [])
                    if len(levels) >= 2 and levels[0] and levels[1]:
                        mid = (float(levels[0][0]["px"]) + float(levels[1][0]["px"])) / 2
                        lines.append(f"  {coin}: ${mid:,.2f}")
                except Exception:
                    pass

            ctx.set("prices_context", "\n".join(lines))
        except Exception as e:
            ctx.set("prices_context", f"PRICES: fetch error: {e}")


class FetchLearningsStep(WorkflowStep):
    name = "fetch_learnings"
    outputs = {"learnings_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        path = Path("data/research/learnings.md")
        if not path.exists():
            ctx.set("learnings_context", "LEARNINGS: No learnings file")
            return
        text = path.read_text()
        # Take last 2000 chars (most recent learnings)
        if len(text) > 2000:
            text = "...\n" + text[-2000:]
        ctx.set("learnings_context", f"RECENT LEARNINGS:\n{text}")


class FetchRecentTradesStep(WorkflowStep):
    name = "fetch_recent_trades"
    outputs = {"trades_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        path = Path("data/cli/trades.jsonl")
        if not path.exists():
            ctx.set("trades_context", "TRADES: No trade history")
            return
        lines = path.read_text().strip().splitlines()
        recent = lines[-10:]  # last 10 trades
        trades = []
        for line in recent:
            try:
                t = json.loads(line)
                trades.append(
                    f"  {t.get('side','?')} {t.get('coin','?')} "
                    f"sz={t.get('sz','?')} @ ${t.get('px','?')} "
                    f"pnl=${t.get('pnl', '?')}"
                )
            except Exception:
                pass
        ctx.set("trades_context", "RECENT TRADES:\n" + "\n".join(trades) if trades else "TRADES: None recent")


class FetchIssuesStep(WorkflowStep):
    name = "fetch_issues"
    outputs = {"issues_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        try:
            from common.issues import get_open_issues
            issues = get_open_issues()
            if not issues:
                ctx.set("issues_context", "ISSUES: None open")
                return
            lines = [f"OPEN ISSUES ({len(issues)}):"]
            for i in issues[:10]:
                lines.append(f"  [{i.severity}] {i.title}")
                if i.description:
                    lines.append(f"    {i.description[:100]}")
            ctx.set("issues_context", "\n".join(lines))
        except Exception as e:
            ctx.set("issues_context", f"ISSUES: load error: {e}")


class FetchLiquidityRegimeStep(WorkflowStep):
    name = "fetch_liquidity_regime"
    outputs = {"liquidity_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        weekend = now.weekday() >= 5
        after_hours = now.hour >= 22 or now.hour < 6
        if weekend and after_hours:
            regime = "DANGEROUS (weekend + after hours)"
        elif weekend:
            regime = "WEEKEND (thin liquidity)"
        elif after_hours:
            regime = "LOW (after hours)"
        else:
            regime = "NORMAL"
        ctx.set("liquidity_context", f"LIQUIDITY REGIME: {regime} ({now.strftime('%a %H:%M UTC')})")


class FetchGuardStateStep(WorkflowStep):
    name = "fetch_guard_state"
    outputs = {"guard_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        guard_dir = Path("data/guard")
        if not guard_dir.exists():
            ctx.set("guard_context", "GUARD: No guard state")
            return
        lines = ["GUARD STATE:"]
        for f in guard_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                instrument = data.get("instrument", f.stem)
                trailing = data.get("trailing_stop_price", "N/A")
                floor = data.get("floor_price", "N/A")
                lines.append(f"  {instrument}: trail=${trailing} floor=${floor}")
            except Exception:
                pass
        ctx.set("guard_context", "\n".join(lines) if len(lines) > 1 else "GUARD: No active guards")


class FetchDaemonStatusStep(WorkflowStep):
    name = "fetch_daemon_status"
    outputs = {"daemon_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        pid_file = Path("data/daemon/daemon.pid")
        state_file = Path("data/daemon/state.json")
        parts = ["DAEMON:"]

        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                # Check if process is alive
                os.kill(pid, 0)
                parts.append(f"  Running (PID {pid})")
            except (OSError, ValueError):
                parts.append("  Not running (stale PID file)")
        else:
            parts.append("  Not running")

        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
                parts.append(f"  Tier: {state.get('tier', '?')}")
                parts.append(f"  Ticks: {state.get('tick_count', 0)}")
                parts.append(f"  Trades: {state.get('total_trades', 0)}")
            except Exception:
                pass

        ctx.set("daemon_context", "\n".join(parts))


class FetchRadarLatestStep(WorkflowStep):
    name = "fetch_radar_latest"
    outputs = {"radar_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        radar_dir = Path("data/radar")
        if not radar_dir.exists():
            ctx.set("radar_context", "RADAR: No scan results")
            return

        # Find most recent scan
        scans = sorted(radar_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not scans:
            ctx.set("radar_context", "RADAR: No scan results")
            return

        try:
            data = json.loads(scans[0].read_text())
            opps = data.get("opportunities", [])
            age_min = (time.time() - scans[0].stat().st_mtime) / 60
            lines = [f"RADAR (last scan {age_min:.0f}m ago, {len(opps)} opportunities):"]
            for opp in opps[:5]:
                lines.append(
                    f"  {opp.get('instrument','?')}: score={opp.get('final_score',0)} "
                    f"direction={opp.get('direction','?')}"
                )
            ctx.set("radar_context", "\n".join(lines))
        except Exception:
            ctx.set("radar_context", "RADAR: parse error")


class FetchReflectLatestStep(WorkflowStep):
    name = "fetch_reflect_latest"
    outputs = {"reflect_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        reflect_dir = Path("data/reflect")
        if not reflect_dir.exists():
            ctx.set("reflect_context", "REFLECT: No reports")
            return

        reports = sorted(reflect_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not reports:
            ctx.set("reflect_context", "REFLECT: No reports")
            return

        text = reports[0].read_text()
        if len(text) > 1500:
            text = text[:1500] + "\n..."
        ctx.set("reflect_context", f"LATEST REFLECT REPORT:\n{text}")


class FetchLabStatusStep(WorkflowStep):
    name = "fetch_lab_status"
    outputs = {"lab_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        lab_file = Path("data/lab/experiments.json")
        if not lab_file.exists():
            ctx.set("lab_context", "LAB: No experiments")
            return
        try:
            experiments = json.loads(lab_file.read_text())
            lines = [f"LAB ({len(experiments)} experiments):"]
            for exp in experiments[-5:]:
                lines.append(
                    f"  {exp.get('market','?')}:{exp.get('strategy','?')} "
                    f"stage={exp.get('stage','?')} score={exp.get('score',0):.2f}"
                )
            ctx.set("lab_context", "\n".join(lines))
        except Exception:
            ctx.set("lab_context", "LAB: parse error")


class FetchStrategiesStep(WorkflowStep):
    name = "fetch_strategies"
    outputs = {"strategies_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        roster_file = Path("data/daemon/roster.json")
        if not roster_file.exists():
            ctx.set("strategies_context", "STRATEGIES: No roster")
            return
        try:
            roster = json.loads(roster_file.read_text())
            slots = roster.get("slots", {})
            lines = [f"ACTIVE STRATEGIES ({len(slots)}):"]
            for name, slot in slots.items():
                paused = " (PAUSED)" if slot.get("paused") else ""
                lines.append(
                    f"  {name}: {slot.get('instrument','?')} "
                    f"tick={slot.get('tick_interval',0)}s{paused}"
                )
            ctx.set("strategies_context", "\n".join(lines))
        except Exception:
            ctx.set("strategies_context", "STRATEGIES: roster parse error")


class AssemblePromptStep(WorkflowStep):
    """Final step: assemble all fetched context into a structured prompt."""

    name = "assemble_prompt"
    inputs = {"user_message", "intent"}
    outputs = {"assembled_context"}

    def execute(self, ctx: WorkflowContext) -> None:
        intent = ctx.get("intent", "general")
        user_msg = ctx.get("user_message", "")

        sections = []
        sections.append(f"INTENT: {intent}")
        sections.append(f"TIME: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
        sections.append("")

        # Gather all *_context keys in a sensible order
        context_order = [
            "account_context", "positions_context", "guard_context",
            "thesis_context", "prices_context", "liquidity_context",
            "radar_context", "lab_context", "strategies_context",
            "trades_context", "learnings_context", "reflect_context",
            "issues_context", "daemon_context",
        ]
        for key in context_order:
            val = ctx.get(key)
            if val:
                sections.append(val)
                sections.append("")

        sections.append(f"USER MESSAGE: {user_msg}")

        ctx.set("assembled_context", "\n".join(sections))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_context_engine() -> WorkflowEngine:
    """Create a WorkflowEngine pre-loaded with all context-fetching steps."""
    engine = WorkflowEngine()
    engine.register(ClassifyIntentStep())
    engine.register(FetchPositionsStep())
    engine.register(FetchAccountStep())
    engine.register(FetchThesisStep())
    engine.register(FetchPricesStep())
    engine.register(FetchLearningsStep())
    engine.register(FetchRecentTradesStep())
    engine.register(FetchIssuesStep())
    engine.register(FetchLiquidityRegimeStep())
    engine.register(FetchGuardStateStep())
    engine.register(FetchDaemonStatusStep())
    engine.register(FetchRadarLatestStep())
    engine.register(FetchReflectLatestStep())
    engine.register(FetchLabStatusStep())
    engine.register(FetchStrategiesStep())
    engine.register(AssemblePromptStep())
    return engine


def assemble_context(user_message: str) -> str:
    """One-call API: classify intent, fetch relevant data, return assembled context.

    This is what the Telegram bot calls instead of passing raw text to an LLM.
    """
    engine = build_context_engine()

    # Step 1: classify intent
    intent_ctx = engine.run_sequence(
        ["classify_intent"],
        initial={"user_message": user_message},
    )
    intent = intent_ctx.get("intent", "general")
    steps_needed = intent_ctx.get("intent_steps", INTENT_DATA_NEEDS["general"])

    # Step 2: fetch all relevant data + assemble
    all_steps = steps_needed + ["assemble_prompt"]
    result = engine.run_sequence(
        all_steps,
        initial={
            "user_message": user_message,
            "intent": intent,
            "intent_steps": steps_needed,
        },
    )

    return result.get("assembled_context", f"(context assembly failed)\n\nUSER MESSAGE: {user_message}")
