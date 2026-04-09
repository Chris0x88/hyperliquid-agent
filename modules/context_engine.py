"""Context Engine v2 — intent-aware data assembly for Telegram AI messages.

Upgrades the keyword-based _prefetch_for_message in telegram_agent.py with:
  1. Multi-signal intent classification (not just keyword match)
  2. Relevance scoring to avoid prompt pollution
  3. Additional data sources: bot classifier, supply disruptions, calendar,
     autoresearch evaluations, performance metrics, active proposals
  4. Budget-aware truncation — most relevant data first

This module is pure computation + file reads. No API calls, no AI calls.
It reads from local cached data that the daemon already maintains.

Usage:
    from modules.context_engine import classify_intent, assemble_context
    intent = classify_intent(user_text)
    context_str = assemble_context(intent, account_state, market_snapshots)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger("context_engine")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════════════════════════════════
# 1. INTENT CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class MessageIntent:
    """Classified intent from a user message."""
    primary: str                    # Main intent category
    markets: List[str] = field(default_factory=list)  # Detected market references
    topics: Set[str] = field(default_factory=set)      # Detected topic tags
    confidence: float = 0.0         # 0-1 classification confidence
    raw_text: str = ""

    @property
    def needs_positions(self) -> bool:
        return self.primary in ("position_query", "performance_review", "risk_check", "trade_planning")

    @property
    def needs_thesis(self) -> bool:
        return self.primary in ("market_analysis", "trade_planning", "thesis_update", "position_query")

    @property
    def needs_signals(self) -> bool:
        return self.primary in ("market_analysis", "trade_planning", "signal_check")

    @property
    def needs_catalysts(self) -> bool:
        return self.primary in ("market_analysis", "trade_planning", "catalyst_query")

    @property
    def needs_performance(self) -> bool:
        return self.primary in ("performance_review", "system_health")

    @property
    def needs_bot_classifier(self) -> bool:
        return self.primary in ("market_analysis", "trade_planning")

    @property
    def needs_supply(self) -> bool:
        return self.primary in ("market_analysis", "trade_planning") and any(
            m in ("BRENTOIL", "CL") for m in self.markets
        )

    @property
    def needs_proposals(self) -> bool:
        return self.primary in ("system_health", "self_improvement")

    @property
    def needs_health(self) -> bool:
        return self.primary in ("system_health",)


# Intent patterns: (keywords, intent_name, base_confidence)
# Order matters — first match with highest confidence wins
_INTENT_PATTERNS: List[Tuple[List[str], str, float]] = [
    # Performance review
    (["how did we do", "how are we doing", "performance", "pnl today",
      "daily pnl", "weekly pnl", "win rate", "track record", "history",
      "how much", "profit", "loss", "returns"], "performance_review", 0.85),

    # Risk check
    (["risk", "liquidation", "liq price", "cushion", "drawdown",
      "exposure", "margin", "leverage"], "risk_check", 0.85),

    # System health
    (["status", "health", "daemon", "iterator", "error", "issue",
      "broken", "proposal", "tune", "selftune", "improve"], "system_health", 0.80),

    # Market analysis
    (["what do you think", "analysis", "outlook", "forecast",
      "technical", "chart", "setup", "opportunity", "buy",
      "sell", "entry", "market", "move", "momentum", "trend"], "market_analysis", 0.75),

    # Trade planning
    (["should i", "should we", "plan", "strategy", "size",
      "add", "scale", "trim", "close", "adjust", "rebalance"], "trade_planning", 0.80),

    # Position query
    (["position", "portfolio", "what am i", "what are we",
      "holding", "long", "short", "open"], "position_query", 0.85),

    # Thesis update
    (["thesis", "conviction", "invalidation", "target",
      "take profit", "stop loss"], "thesis_update", 0.80),

    # Catalyst query
    (["catalyst", "news", "event", "calendar", "schedule",
      "opec", "eia", "fed", "fomc", "report", "data release"], "catalyst_query", 0.85),

    # Signal check
    (["signal", "rsi", "ema", "macd", "adx", "atr",
      "radar", "pulse", "heatmap", "liquidity zone"], "signal_check", 0.80),

    # Self improvement
    (["learn", "improve", "tune", "reflect", "lesson",
      "adapt", "optimize"], "self_improvement", 0.75),
]

# Market keyword → canonical coin
_MARKET_KEYWORDS: Dict[str, str] = {
    "oil": "BRENTOIL", "brent": "BRENTOIL", "brentoil": "BRENTOIL",
    "wti": "BRENTOIL", "cl": "BRENTOIL", "crude": "BRENTOIL",
    "btc": "BTC", "bitcoin": "BTC",
    "gold": "GOLD", "silver": "SILVER",
    "natgas": "NATGAS", "gas": "NATGAS",
}


def classify_intent(text: str) -> MessageIntent:
    """Classify a user message into an intent with detected markets and topics.

    Multi-signal: checks multiple pattern groups and picks the best match.
    Falls back to 'general' if nothing matches strongly.
    """
    text_lower = " " + text.lower() + " "

    # Detect markets
    markets: List[str] = []
    for kw, coin in _MARKET_KEYWORDS.items():
        # Pad with spaces for word-boundary matching on short keywords
        padded = f" {kw} "
        if padded in text_lower and coin not in markets:
            markets.append(coin)

    # Score each intent pattern
    best_intent = "general"
    best_confidence = 0.0
    matched_count = 0

    for keywords, intent_name, base_conf in _INTENT_PATTERNS:
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits == 0:
            continue
        # Confidence increases with more keyword hits, up to base_conf
        conf = min(base_conf, 0.3 + (hits * 0.15))
        if conf > best_confidence:
            best_confidence = conf
            best_intent = intent_name
            matched_count = hits

    # Detect topics for backward compatibility with existing prefetch
    topics: Set[str] = set()
    topic_keywords = {
        "position": "positions", "pnl": "positions", "trade": "positions",
        "fund": "funding", "funding": "funding",
        "thesis": "thesis", "conviction": "thesis",
        "signal": "signals", "technical": "signals",
        "catalyst": "catalysts", "news": "catalysts", "event": "catalysts",
        "heatmap": "zones", "liquidity": "zones",
        "lesson": "lessons", "review": "lessons",
        "risk": "risk", "liquidation": "risk",
        "status": "health", "daemon": "health",
    }
    for kw, tag in topic_keywords.items():
        if kw in text_lower:
            topics.add(tag)

    return MessageIntent(
        primary=best_intent,
        markets=markets,
        topics=topics,
        confidence=best_confidence,
        raw_text=text,
    )


# ═══════════════════════════════════════════════════════════════════════
# 2. CONTEXT ASSEMBLY — data source fetchers
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ContextBlock:
    """A scored, budget-aware block of context data."""
    tag: str            # e.g. "POSITION BRENTOIL", "BOT_CLASSIFIER"
    text: str           # rendered text
    relevance: float    # 0-1, higher = more important
    tokens_est: int     # estimated token count (chars / 4)

    @property
    def priority_score(self) -> float:
        """Higher = include first."""
        return self.relevance


def _est_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 chars."""
    return max(1, len(text) // 4)


def _fetch_bot_classifier(markets: List[str]) -> Optional[ContextBlock]:
    """Recent bot classifier results for detected markets."""
    try:
        bp_path = _PROJECT_ROOT / "data" / "research" / "bot_patterns.jsonl"
        if not bp_path.exists():
            return None

        from collections import deque
        tail = deque(maxlen=50)
        with bp_path.open() as fh:
            for ln in fh:
                if ln.strip():
                    tail.append(ln)

        market_filter = {m.replace("xyz:", "").upper() for m in markets} if markets else None
        recent: List[dict] = []
        for ln in reversed(tail):
            try:
                entry = json.loads(ln)
            except Exception:
                continue
            inst = entry.get("instrument", "").replace("xyz:", "").upper()
            if market_filter and inst not in market_filter:
                continue
            recent.append(entry)
            if len(recent) >= 3:
                break

        if not recent:
            return None

        lines = []
        for bp in recent:
            classification = bp.get("classification", "?")
            confidence = bp.get("confidence", 0)
            direction = bp.get("direction", "?")
            signals_used = bp.get("signals_used", [])
            lines.append(
                f"  {bp.get('instrument', '?')}: {classification} (conf={confidence:.0%}) "
                f"dir={direction} signals={','.join(signals_used[:4])}"
            )

        text = "[BOT CLASSIFIER — recent move classifications]\n" + "\n".join(lines)
        return ContextBlock(tag="BOT_CLASSIFIER", text=text, relevance=0.7, tokens_est=_est_tokens(text))
    except Exception as e:
        log.debug("bot_classifier fetch failed: %s", e)
        return None


def _fetch_supply_disruptions() -> Optional[ContextBlock]:
    """Active supply disruptions from the supply ledger."""
    try:
        state_path = _PROJECT_ROOT / "data" / "supply" / "state.json"
        if not state_path.exists():
            return None
        state = json.loads(state_path.read_text())
        disruptions = state.get("active_disruptions", [])
        if not disruptions:
            return None

        total_bpd = sum(d.get("estimated_bpd", 0) for d in disruptions)
        lines = [f"[SUPPLY DISRUPTIONS] {len(disruptions)} active, total impact: {total_bpd:,.0f} bpd"]
        for d in disruptions[:5]:
            region = d.get("region", "?")
            bpd = d.get("estimated_bpd", 0)
            source = d.get("source", "?")
            lines.append(f"  {region}: {bpd:,.0f} bpd ({source})")

        text = "\n".join(lines)
        return ContextBlock(tag="SUPPLY", text=text, relevance=0.8, tokens_est=_est_tokens(text))
    except Exception as e:
        log.debug("supply fetch failed: %s", e)
        return None


def _fetch_recent_evaluations(limit: int = 2) -> Optional[ContextBlock]:
    """Latest autoresearch evaluation summaries."""
    try:
        eval_dir = _PROJECT_ROOT / "data" / "research" / "evaluations"
        if not eval_dir.exists():
            return None

        eval_files = sorted(eval_dir.glob("*.json"), reverse=True)[:limit]
        if not eval_files:
            return None

        lines = ["[RECENT EVALUATIONS — autoresearch findings]"]
        for ef in eval_files:
            try:
                ev = json.loads(ef.read_text())
                ts_human = ev.get("timestamp_human", ef.stem)
                sizing = ev.get("sizing_alignment_score", 0)
                stop_quality = ev.get("stop_quality_notes", "")[:80]
                catalyst = ev.get("catalyst_timing_score", 0)
                lines.append(f"  {ts_human}: sizing={sizing:.0%} catalyst={catalyst:.0%}")
                if stop_quality:
                    lines.append(f"    stops: {stop_quality}")
            except Exception:
                continue

        if len(lines) <= 1:
            return None

        text = "\n".join(lines)
        return ContextBlock(tag="EVALUATIONS", text=text, relevance=0.6, tokens_est=_est_tokens(text))
    except Exception as e:
        log.debug("evaluations fetch failed: %s", e)
        return None


def _fetch_active_proposals() -> Optional[ContextBlock]:
    """Pending selftune proposals awaiting approval."""
    try:
        proposals_path = _PROJECT_ROOT / "data" / "strategy" / "oil_botpattern_proposals.jsonl"
        if not proposals_path.exists():
            return None

        pending = []
        with proposals_path.open() as fh:
            for ln in fh:
                if not ln.strip():
                    continue
                try:
                    p = json.loads(ln)
                except Exception:
                    continue
                if p.get("status") == "pending":
                    pending.append(p)

        if not pending:
            return None

        lines = [f"[PENDING PROPOSALS] {len(pending)} awaiting your approval"]
        for p in pending[:3]:
            pid = p.get("proposal_id", "?")
            ptype = p.get("proposal_type", "?")
            desc = p.get("description", "")[:80]
            lines.append(f"  {pid}: [{ptype}] {desc}")

        text = "\n".join(lines)
        return ContextBlock(tag="PROPOSALS", text=text, relevance=0.5, tokens_est=_est_tokens(text))
    except Exception as e:
        log.debug("proposals fetch failed: %s", e)
        return None


def _fetch_calendar_context() -> Optional[ContextBlock]:
    """Upcoming calendar events from CalendarContext / catalysts."""
    try:
        # Check for calendar context file
        cal_path = _PROJECT_ROOT / "data" / "daemon" / "calendar_context.json"
        if cal_path.exists():
            cal = json.loads(cal_path.read_text())
            events = cal.get("upcoming", [])
            if events:
                lines = ["[CALENDAR — upcoming events]"]
                now = time.time()
                for ev in events[:5]:
                    ev_ts = ev.get("timestamp", 0)
                    if ev_ts and ev_ts < now - 3600:  # skip >1h old
                        continue
                    title = ev.get("title", "?")[:60]
                    ev_time = ev.get("time_str", "?")
                    impact = ev.get("impact", "?")
                    lines.append(f"  {ev_time} [{impact}] {title}")
                if len(lines) > 1:
                    text = "\n".join(lines)
                    return ContextBlock(tag="CALENDAR", text=text, relevance=0.75, tokens_est=_est_tokens(text))

        # Fallback: upcoming catalysts from news ingest
        cat_path = _PROJECT_ROOT / "data" / "news" / "catalysts.jsonl"
        if not cat_path.exists():
            return None

        now = time.time()
        upcoming = []
        from collections import deque
        tail = deque(maxlen=200)
        with cat_path.open() as fh:
            for ln in fh:
                if ln.strip():
                    tail.append(ln)

        for ln in tail:
            try:
                ev = json.loads(ln)
            except Exception:
                continue
            ev_date_str = ev.get("event_date", "")
            if ev_date_str:
                try:
                    from datetime import datetime, timezone
                    ev_dt = datetime.fromisoformat(ev_date_str.replace("Z", "+00:00"))
                    ev_ts = ev_dt.timestamp()
                    if ev_ts > now - 3600:  # upcoming or within last hour
                        upcoming.append((ev_ts, ev))
                except Exception:
                    pass

        if not upcoming:
            return None

        upcoming.sort(key=lambda x: x[0])
        lines = ["[UPCOMING CATALYSTS]"]
        for _, ev in upcoming[:4]:
            cat = f"  {ev.get('event_date', '?')[:16]} [{ev.get('category', '?')}] sev={ev.get('severity', '?')}"
            rat = ev.get("rationale", "")[:60]
            if rat:
                cat += f" — {rat}"
            lines.append(cat)

        text = "\n".join(lines)
        return ContextBlock(tag="CALENDAR", text=text, relevance=0.7, tokens_est=_est_tokens(text))
    except Exception as e:
        log.debug("calendar fetch failed: %s", e)
        return None


def _fetch_recent_learnings(limit: int = 3) -> Optional[ContextBlock]:
    """Most recent learnings from autoresearch."""
    try:
        learnings_path = _PROJECT_ROOT / "data" / "research" / "learnings.md"
        if not learnings_path.exists():
            return None

        content = learnings_path.read_text()
        if not content.strip():
            return None

        # Take last N entries (separated by --- or ##)
        sections = [s.strip() for s in content.split("---") if s.strip()]
        if not sections:
            sections = [s.strip() for s in content.split("##") if s.strip()]

        recent = sections[-limit:] if sections else []
        if not recent:
            return None

        text = "[RECENT LEARNINGS — from autoresearch]\n" + "\n".join(
            s[:150] for s in recent
        )
        return ContextBlock(tag="LEARNINGS", text=text, relevance=0.55, tokens_est=_est_tokens(text))
    except Exception as e:
        log.debug("learnings fetch failed: %s", e)
        return None


def _fetch_lab_experiments() -> Optional[ContextBlock]:
    """Active lab experiments if lab engine is running."""
    try:
        lab_path = _PROJECT_ROOT / "data" / "lab" / "experiments.json"
        if not lab_path.exists():
            return None

        experiments = json.loads(lab_path.read_text())
        if not experiments:
            return None

        active = [e for e in experiments if e.get("status") in ("backtesting", "paper_trading")]
        graduated = [e for e in experiments if e.get("status") == "graduated"]

        if not active and not graduated:
            return None

        lines = ["[LAB EXPERIMENTS]"]
        for e in active[:3]:
            lines.append(f"  {e.get('id', '?')}: {e.get('strategy', '?')} on {e.get('market', '?')} — {e.get('status', '?')}")
        for e in graduated[:2]:
            sharpe = e.get("metrics", {}).get("sharpe", 0)
            lines.append(f"  GRADUATED: {e.get('strategy', '?')} on {e.get('market', '?')} (sharpe={sharpe:.2f})")

        text = "\n".join(lines)
        return ContextBlock(tag="LAB", text=text, relevance=0.5, tokens_est=_est_tokens(text))
    except Exception as e:
        log.debug("lab fetch failed: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════════════
# 3. CONTEXT ASSEMBLY — scored, budgeted
# ═══════════════════════════════════════════════════════════════════════

def assemble_context(
    intent: MessageIntent,
    account_state: dict,
    market_snapshots: dict,
    token_budget: int = 800,
) -> str:
    """Assemble context blocks based on intent, sorted by relevance, within budget.

    This produces the ADDITIONAL context that supplements the existing
    _prefetch_for_message output in telegram_agent.py. It adds data sources
    that the existing prefetch doesn't cover.

    Returns a formatted string, or "" if nothing relevant was found.
    """
    blocks: List[ContextBlock] = []

    # Fetch blocks based on intent needs
    if intent.needs_bot_classifier:
        b = _fetch_bot_classifier(intent.markets)
        if b:
            blocks.append(b)

    if intent.needs_supply:
        b = _fetch_supply_disruptions()
        if b:
            blocks.append(b)

    if intent.needs_performance:
        b = _fetch_recent_evaluations()
        if b:
            blocks.append(b)

    if intent.needs_proposals:
        b = _fetch_active_proposals()
        if b:
            blocks.append(b)

    if intent.needs_catalysts:
        b = _fetch_calendar_context()
        if b:
            blocks.append(b)

    # Always try learnings for trade-related intents
    if intent.primary in ("market_analysis", "trade_planning", "performance_review"):
        b = _fetch_recent_learnings()
        if b:
            blocks.append(b)

    # Lab experiments for system health / self improvement
    if intent.primary in ("system_health", "self_improvement"):
        b = _fetch_lab_experiments()
        if b:
            blocks.append(b)

    if not blocks:
        return ""

    # Sort by relevance (highest first) and apply token budget
    blocks.sort(key=lambda b: b.priority_score, reverse=True)

    included: List[str] = []
    tokens_used = 0
    for block in blocks:
        if tokens_used + block.tokens_est > token_budget:
            # Try to fit a truncated version
            remaining = token_budget - tokens_used
            if remaining > 50:
                truncated = block.text[:remaining * 4]  # rough char estimate
                included.append(truncated + "\n[... truncated]")
                tokens_used += remaining
            break
        included.append(block.text)
        tokens_used += block.tokens_est

    if not included:
        return ""

    header = f"--- ENRICHED CONTEXT (intent={intent.primary}, {tokens_used}t) ---"
    return header + "\n" + "\n".join(included)
