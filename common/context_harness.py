"""Context harness — relevance-scored, token-budgeted prompt assembler.

Inspired by Claude Code's tiered context architecture:
  - Static sections (cached globally) vs dynamic sections (per-session)
  - Micro-compaction when approaching budget limits
  - Relevance ranking: recent > active position > historical

This module replaces the flat dump in scheduled_check.py. Instead of
dumping everything and hoping it fits, it:
  1. Scores each context block by relevance
  2. Assigns to tiers: CRITICAL (always), RELEVANT (if room), BACKGROUND (last)
  3. Assembles within a token budget
  4. Returns a compact string ready for prompt injection

Usage:
    from common.context_harness import build_thesis_context

    # For the scheduled AI task that writes thesis files:
    context = build_thesis_context(
        market="xyz:BRENTOIL",
        account_state={...},     # from HL API
        market_snapshot=snap,    # from Mission 1
        token_budget=4000,       # ~4000 tokens max for context
    )
    # context is a string ready to inject into the AI prompt

Design principle: the AI should be able to read the context top-to-bottom
and make a conviction decision without scrolling back. Most important
information first, diminishing importance as you read down.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("context_harness")

# Approximate tokens per character (conservative — real tokenizers vary)
CHARS_PER_TOKEN = 4

# Tier definitions — what percentage of budget each tier gets
TIER_BUDGET_PCT = {
    "critical": 0.40,   # always included: alerts, position, market snapshot
    "relevant": 0.35,   # included if room: thesis state, recent events, learnings
    "background": 0.25, # included last: historical summaries, research notes
}


@dataclass
class ContextBlock:
    """One block of context to potentially include in the prompt."""
    name: str
    content: str
    tier: str           # "critical", "relevant", "background"
    relevance: float    # 0.0-1.0, used to sort within tier
    char_count: int = 0

    def __post_init__(self):
        self.char_count = len(self.content)

    @property
    def estimated_tokens(self) -> int:
        return self.char_count // CHARS_PER_TOKEN


@dataclass
class AssembledContext:
    """Result of context assembly."""
    text: str
    blocks_included: List[str]
    blocks_dropped: List[str]
    total_chars: int
    estimated_tokens: int
    budget_used_pct: float


def build_thesis_context(
    market: str,
    account_state: Optional[Dict] = None,
    market_snapshot_text: Optional[str] = None,
    current_thesis: Optional[Dict] = None,
    alerts: Optional[List[str]] = None,
    token_budget: int = 4000,
    db_path: str = "data/memory/memory.db",
) -> AssembledContext:
    """Build a relevance-scored, token-budgeted context for thesis generation.

    This is the main entry point. It replaces the flat dump in scheduled_check.py.

    Args:
        market: Target market (e.g. "xyz:BRENTOIL", "BTC-PERP")
        account_state: Dict with equity, positions, etc.
        market_snapshot_text: Pre-rendered market structure text (from Mission 1)
        current_thesis: Current thesis state dict (for staleness check)
        alerts: Critical alerts that must always be included
        token_budget: Max tokens for the assembled context
        db_path: Path to memory SQLite database

    Returns:
        AssembledContext with the final text and assembly metadata.
    """
    blocks: List[ContextBlock] = []

    # ── CRITICAL TIER: always included ────────────────────────

    # 1. Alerts (highest priority — safety-critical)
    if alerts:
        blocks.append(ContextBlock(
            name="alerts",
            content="⚠️ ALERTS:\n" + "\n".join(f"  - {a}" for a in alerts),
            tier="critical",
            relevance=1.0,
        ))

    # 2. Current position state (you need to know where you are to decide where to go)
    if account_state:
        pos_text = _render_position_state(market, account_state)
        if pos_text:
            blocks.append(ContextBlock(
                name="position",
                content=pos_text,
                tier="critical",
                relevance=0.95,
            ))

    # 3. Market structure snapshot (pre-computed technicals from Mission 1)
    if market_snapshot_text:
        blocks.append(ContextBlock(
            name="market_structure",
            content=market_snapshot_text,
            tier="critical",
            relevance=0.90,
        ))

    # 4. Time context (compact — day of week, trading hours, upcoming events)
    time_ctx = _render_time_context()
    blocks.append(ContextBlock(
        name="time",
        content=time_ctx,
        tier="critical",
        relevance=0.85,
    ))

    # ── RELEVANT TIER: included if room ───────────────────────

    # 5. Current thesis state (so the AI knows its own prior conviction)
    if current_thesis:
        thesis_text = _render_current_thesis(current_thesis)
        blocks.append(ContextBlock(
            name="current_thesis",
            content=thesis_text,
            tier="relevant",
            relevance=0.85,
        ))

    # 6. Memory context (recent events + summarized history + learnings)
    try:
        from common.memory_consolidator import get_consolidated_context
        mem_ctx = get_consolidated_context(market, days=60, max_chars=1500, db_path=db_path)
        if mem_ctx:
            blocks.append(ContextBlock(
                name="memory",
                content=mem_ctx,
                tier="relevant",
                relevance=0.75,
            ))
    except Exception as e:
        log.debug("Memory consolidator unavailable: %s", e)

    # 7. Active observations (programmatic state snapshots)
    try:
        from common.memory_consolidator import get_active_observations
        obs = get_active_observations(market, max_items=5, db_path=db_path)
        if obs:
            obs_lines = [f"ACTIVE OBSERVATIONS ({market}):"]
            for o in obs:
                obs_lines.append(f"  [P{o['priority']}][{o['category']}] {o['title']}")
                if o.get("body"):
                    obs_lines.append(f"    {o['body'][:100]}")
            blocks.append(ContextBlock(
                name="observations",
                content="\n".join(obs_lines),
                tier="relevant",
                relevance=0.70,
            ))
    except Exception as e:
        log.debug("Observations unavailable: %s", e)

    # 8. Recent autoresearch learnings (last chunk of learnings.md)
    learnings_text = _load_recent_learnings(max_chars=800)
    if learnings_text:
        blocks.append(ContextBlock(
            name="autoresearch",
            content=f"EXECUTION LEARNINGS (recent):\n{learnings_text}",
            tier="relevant",
            relevance=0.65,
        ))

    # ── BACKGROUND TIER: included last ────────────────────────

    # 9. Market research README (long-lived thesis context)
    research_text = _load_market_research(market, max_chars=1000)
    if research_text:
        blocks.append(ContextBlock(
            name="research",
            content=research_text,
            tier="background",
            relevance=0.60,
        ))

    # 10. Open issues
    issues_text = _load_open_issues(max_items=5)
    if issues_text:
        blocks.append(ContextBlock(
            name="issues",
            content=issues_text,
            tier="background",
            relevance=0.40,
        ))

    # ── ASSEMBLE within budget ────────────────────────────────
    return _assemble(blocks, token_budget)


def build_multi_market_context(
    markets: List[str],
    account_state: Optional[Dict] = None,
    market_snapshots: Optional[Dict[str, str]] = None,
    token_budget: int = 6000,
    db_path: str = "data/memory/memory.db",
) -> AssembledContext:
    """Build context covering multiple markets (e.g. for the scheduled check).

    Uses a shared account state block + per-market sections with proportional budgets.
    """
    blocks: List[ContextBlock] = []

    # Shared: account overview
    if account_state:
        acc_text = _render_account_overview(account_state)
        blocks.append(ContextBlock(
            name="account",
            content=acc_text,
            tier="critical",
            relevance=1.0,
        ))

    # Time context
    blocks.append(ContextBlock(
        name="time",
        content=_render_time_context(),
        tier="critical",
        relevance=0.95,
    ))

    # Per-market sections (scaled relevance by position size or thesis conviction)
    for i, market in enumerate(markets):
        # Market snapshot
        if market_snapshots and market in market_snapshots:
            blocks.append(ContextBlock(
                name=f"snapshot_{market}",
                content=market_snapshots[market],
                tier="critical",
                relevance=0.90 - i * 0.05,
            ))

        # Memory context (smaller budget per market in multi-market mode)
        try:
            from common.memory_consolidator import get_consolidated_context
            mem = get_consolidated_context(market, days=30, max_chars=800, db_path=db_path)
            if mem:
                blocks.append(ContextBlock(
                    name=f"memory_{market}",
                    content=mem,
                    tier="relevant",
                    relevance=0.75 - i * 0.05,
                ))
        except Exception:
            pass

    # Shared: learnings
    learnings = _load_recent_learnings(max_chars=600)
    if learnings:
        blocks.append(ContextBlock(
            name="learnings",
            content=f"EXECUTION LEARNINGS:\n{learnings}",
            tier="relevant",
            relevance=0.60,
        ))

    return _assemble(blocks, token_budget)


# ═══════════════════════════════════════════════════════════════════════════════
# Assembly engine
# ═══════════════════════════════════════════════════════════════════════════════

def _assemble(blocks: List[ContextBlock], token_budget: int) -> AssembledContext:
    """Assemble blocks into a single context string within token budget.

    Strategy: include all critical, then relevant sorted by relevance,
    then background sorted by relevance. Stop when budget is exhausted.
    """
    char_budget = token_budget * CHARS_PER_TOKEN

    # Sort blocks: critical first, then by relevance within tier
    tier_order = {"critical": 0, "relevant": 1, "background": 2}
    sorted_blocks = sorted(
        blocks,
        key=lambda b: (tier_order.get(b.tier, 9), -b.relevance),
    )

    included: List[ContextBlock] = []
    dropped: List[str] = []
    used_chars = 0

    for block in sorted_blocks:
        if used_chars + block.char_count <= char_budget:
            included.append(block)
            used_chars += block.char_count
        else:
            # For critical tier, try to include a truncated version
            if block.tier == "critical":
                remaining = char_budget - used_chars
                if remaining > 100:
                    truncated = ContextBlock(
                        name=block.name,
                        content=block.content[:remaining - 20] + "\n[...truncated]",
                        tier=block.tier,
                        relevance=block.relevance,
                    )
                    included.append(truncated)
                    used_chars += truncated.char_count
                else:
                    dropped.append(f"{block.name}({block.estimated_tokens}t)")
            else:
                dropped.append(f"{block.name}({block.estimated_tokens}t)")

    # Join with separator
    parts = [b.content for b in included]
    text = "\n---\n".join(parts)

    return AssembledContext(
        text=text,
        blocks_included=[b.name for b in included],
        blocks_dropped=dropped,
        total_chars=len(text),
        estimated_tokens=len(text) // CHARS_PER_TOKEN,
        budget_used_pct=round(len(text) / char_budget * 100, 1) if char_budget > 0 else 0,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Renderers — convert raw data into compact text blocks
# ═══════════════════════════════════════════════════════════════════════════════

def _render_position_state(market: str, account_state: Dict) -> str:
    """Render current position for a market from account state."""
    lines = [f"POSITION ({market}):"]

    # Extract position info (handle various formats from scheduled_check)
    # Check for market-specific position data
    market_key = market.lower().replace(":", "_").replace("-", "_")

    # Try brentoil-specific format
    pos = account_state.get(market_key) or account_state.get("brentoil")
    if pos and isinstance(pos, dict):
        lines.append(f"  Size: {pos.get('size', 0)} @ ${pos.get('entry', 0):.2f}")
        lines.append(f"  Current: ${pos.get('current_price', 0):.2f} | uPnL: ${pos.get('upnl', 0):.2f}")
        if pos.get("liq_price"):
            lines.append(f"  Liq: ${pos['liq_price']:.2f} ({pos.get('liq_dist_pct', '?')}% away) | Lev: {pos.get('leverage', '?')}x")
        lines.append(f"  SL: {'✓' if pos.get('has_sl') else '✗ NONE'} | TP: {'✓' if pos.get('has_tp') else '✗ NONE'}")
        if pos.get("funding_rate") is not None:
            lines.append(f"  Funding: {pos['funding_rate']:.5f} ({pos.get('funding_annualized_pct', '?')}% ann)")
        return "\n".join(lines)

    # Generic account format
    acc = account_state.get("account", {})
    if acc:
        lines.append(f"  Equity: ${acc.get('total_equity', 0):,.2f}")
        if acc.get("native_equity"):
            lines.append(f"  Native: ${acc['native_equity']:,.2f} | xyz: ${acc.get('xyz_equity', 0):,.2f}")
        return "\n".join(lines)

    return ""


def _render_account_overview(account_state: Dict) -> str:
    """Render compact account overview for multi-market context."""
    acc = account_state.get("account", {})
    if not acc:
        return "ACCOUNT: no data"

    lines = [
        f"ACCOUNT: ${acc.get('total_equity', 0):,.2f} equity",
    ]
    if account_state.get("drawdown_pct"):
        lines[0] += f" (drawdown: {account_state['drawdown_pct']}%)"

    # Positions
    positions = account_state.get("positions", [])
    if positions:
        lines.append("POSITIONS:")
        for p in positions:
            direction = "LONG" if p["size"] > 0 else "SHORT"
            upnl_sign = "+" if p["upnl"] >= 0 else ""
            line = f"  {p['coin']} {direction} {abs(p['size']):.1f} @ ${p['entry']:,.2f} | uPnL {upnl_sign}${p['upnl']:,.2f} | {p['leverage']}x"
            if p.get("liq") and p["liq"] != "N/A":
                line += f" | liq ${float(p['liq']):,.2f}"
            lines.append(line)
    else:
        lines.append("POSITIONS: none")

    # Alerts
    for alert in account_state.get("alerts", []):
        lines.append(f"  ⚠️ {alert}")

    return "\n".join(lines)


def _render_time_context() -> str:
    """Compact time context — day, trading hours, session info."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now_utc = datetime.now(ZoneInfo("UTC"))
    now_et = datetime.now(ZoneInfo("America/New_York"))

    day_name = now_utc.strftime("%A")
    is_weekend = now_utc.weekday() >= 5

    lines = [
        f"TIME: {now_utc.strftime('%Y-%m-%d %H:%M')} UTC ({now_et.strftime('%H:%M')} ET) {day_name}",
    ]

    if is_weekend:
        lines.append("  ⚠️ WEEKEND — thin liquidity, wider stops, reduced leverage")

    # Oil market hours: Sun 6PM ET — Fri 5PM ET
    oil_open = not (now_et.weekday() == 5 or  # Saturday
                    (now_et.weekday() == 4 and now_et.hour >= 17) or  # Friday after 5PM
                    (now_et.weekday() == 6 and now_et.hour < 18))  # Sunday before 6PM
    if not oil_open:
        lines.append("  OIL MARKET: CLOSED")

    return "\n".join(lines)


def _render_current_thesis(thesis: Dict) -> str:
    """Compact rendering of current thesis for self-reference."""
    lines = [
        f"CURRENT THESIS:",
        f"  Direction: {thesis.get('direction', '?')} | "
        f"Conviction: {thesis.get('conviction', '?'):.2f} "
        f"(effective: {thesis.get('effective_conviction', '?'):.2f}) | "
        f"Age: {thesis.get('age_hours', '?'):.1f}h",
    ]
    if thesis.get("stale"):
        lines.append("  ⚠️ THESIS IS STALE — needs refresh")
    return "\n".join(lines)


def _load_recent_learnings(max_chars: int = 800) -> str:
    """Load most recent learnings from learnings.md, bounded."""
    path = "data/research/learnings.md"
    if not os.path.exists(path):
        return ""
    try:
        content = open(path).read()
        if not content.strip():
            return ""

        # Find the last N entries that fit in budget
        entries = content.split("## ")
        if len(entries) <= 1:
            return content[:max_chars]

        # Take most recent entries that fit
        result_parts = []
        budget = max_chars
        for entry in reversed(entries[1:]):  # skip header
            entry_text = "## " + entry.strip()
            if budget - len(entry_text) < 0:
                break
            result_parts.insert(0, entry_text)
            budget -= len(entry_text)

        return "\n".join(result_parts)
    except Exception:
        return ""


def _load_market_research(market: str, max_chars: int = 1000) -> str:
    """Load market research README if it exists."""
    from pathlib import Path

    slug = market.replace(":", "_").replace("-", "_").lower()
    readme_path = Path(f"data/research/markets/{slug}/README.md")

    if not readme_path.exists():
        return ""

    try:
        content = readme_path.read_text()
        if len(content) > max_chars:
            content = content[:max_chars - 20] + "\n[...truncated]"
        return f"RESEARCH ({market}):\n{content}"
    except Exception:
        return ""


def _load_open_issues(max_items: int = 5) -> str:
    """Load open issues if the module exists."""
    try:
        from common.issues import get_open_issues
        issues = get_open_issues()
        if not issues:
            return ""
        lines = ["OPEN ISSUES:"]
        for iss in issues[:max_items]:
            lines.append(f"  [{iss.severity}] {iss.title}")
        return "\n".join(lines)
    except Exception:
        return ""
