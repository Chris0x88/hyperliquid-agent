"""ThesisUpdater — Haiku-powered news classifier + thesis conviction adjuster.

Flow:
  1. Read new catalysts from catalysts.jsonl
  2. Call Haiku to classify impact (0-10 score, affected markets, direction)
  3. Optionally fetch full article if Haiku requests it (pass 2)
  4. Tiered response based on Haiku score:
     - MINOR (0-3): log only
     - MODERATE (4-6): conviction ±0.05-0.10
     - MAJOR (7-8): conviction ±0.10-0.15, tighten stops
     - CRITICAL (9-10): INSTANT defensive mode OR conviction boost (direction-aware)
  5. For MODERATE/MAJOR: price data can upgrade tier (never downgrade)
  6. Apply guardrails, update thesis file, log audit

Key principles:
  - CRITICAL news acts IMMEDIATELY — no waiting for price confirmation
  - Direction-aware: news AGAINST position = defensive, news FOR position = strengthen
  - User writes thesis content; this system only adjusts conviction mechanically
  - No direction changes — only user can flip long/short/flat

Kill switch: data/config/thesis_updater.json → enabled: false
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("thesis_updater")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class HaikuClassification:
    """Haiku's impact assessment of a news headline."""
    impact_score: int            # 0-10
    affected_markets: list[str]  # ["xyz:BRENTOIL", "BTC-PERP"]
    direction_hint: str          # "bullish" | "bearish" | "mixed" | "unclear"
    summary: str                 # one-line factual summary
    need_full_article: bool = False
    raw_response: str = ""       # original Haiku text for debugging


@dataclass
class ConvictionChange:
    """Audit record for a single conviction adjustment."""
    timestamp: str
    catalyst_id: str
    headline: str
    market: str
    haiku_impact_score: int
    haiku_direction: str
    tier: str                    # MINOR | MODERATE | MAJOR | CRITICAL
    conviction_before: float
    conviction_after: float
    delta_requested: float
    delta_applied: float
    guardrail_hit: str           # "" | "per_event_cap" | "24h_cap" | "boundary" | "direction_block"
    evidence_side: str           # "for" | "against"
    evidence_text: str
    defensive_mode: bool = False
    guard_override: str = ""
    price_change_pct: float = 0.0
    volume_ratio: float = 0.0


@dataclass
class NewsLogEntry:
    """Log entry for all classified news (including MINOR)."""
    timestamp: str
    catalyst_id: str
    headline: str
    category: str
    haiku_impact_score: int
    haiku_direction: str
    haiku_summary: str
    tier: str
    affected_markets: list[str]
    full_article_fetched: bool = False


# ---------------------------------------------------------------------------
# Haiku integration
# ---------------------------------------------------------------------------

HAIKU_SYSTEM_PROMPT = """You are a financial news classifier for a trading system.
Rate the headline's potential market impact. Do NOT make trading decisions — just assess significance.

Return ONLY valid JSON with this exact schema:
{
  "impact_score": <int 0-10>,
  "affected_markets": [<list of affected markets from: "BTC-PERP", "xyz:BRENTOIL", "xyz:GOLD", "xyz:SILVER">],
  "direction_hint": "<bullish|bearish|mixed|unclear>",
  "summary": "<one-line factual summary>",
  "need_full_article": <true|false>
}

Scoring guide:
  0-3: Irrelevant or minor impact (routine data, background noise)
  4-6: Moderate impact (policy shifts, production changes, sanctions)
  7-8: Major impact (OPEC surprise, major strike, sanctions escalation)
  9-10: Market-defining (war declaration/ceasefire, Hormuz open/close, major deal collapse)

{macro_context}

Thesis markets: BTC-PERP, xyz:BRENTOIL, xyz:GOLD, xyz:SILVER.
"""


def build_haiku_prompt(
    title: str,
    excerpt: str,
    category: str,
    macro_context: str,
    full_article_text: str | None = None,
) -> list[dict]:
    """Build messages for Haiku classification call."""
    system = HAIKU_SYSTEM_PROMPT.replace("{macro_context}", macro_context)

    content = f"Headline: {title}\nCategory: {category}\n"
    if full_article_text:
        content += f"\nFull article text:\n{full_article_text[:3000]}"
    else:
        content += f"Excerpt: {excerpt}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]


def parse_haiku_response(text: str) -> HaikuClassification | None:
    """Parse Haiku's JSON response into a classification.

    Robust to common Haiku output patterns:
    - Bare JSON
    - ```json ... ``` code fences (with or without trailing prose)
    - JSON preceded by preamble text
    - Trailing prose after the JSON object
    """
    if not text or not text.strip():
        log.warning("Failed to parse Haiku response: empty response — raw: %r", text[:200])
        return None

    try:
        # Strategy 1: strip code fences if present (handles both clean fences
        # and fences with trailing prose after the closing ```)
        cleaned = text.strip()
        if "```" in cleaned:
            # Extract content between opening and closing fence
            fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", cleaned)
            if fence_match:
                cleaned = fence_match.group(1).strip()
            else:
                # Opening fence but no closing — strip the opening and use rest
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned).strip()

        # Strategy 2: extract the first {...} object (tolerates leading preamble
        # and trailing prose after the JSON object)
        obj_match = re.search(r"\{[\s\S]*\}", cleaned)
        if obj_match:
            cleaned = obj_match.group(0)

        data = json.loads(cleaned)
        return HaikuClassification(
            impact_score=max(0, min(10, int(data.get("impact_score", 0)))),
            affected_markets=data.get("affected_markets", []),
            direction_hint=data.get("direction_hint", "unclear"),
            summary=data.get("summary", ""),
            need_full_article=data.get("need_full_article", False),
            raw_response=text,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        log.warning(
            "Failed to parse Haiku response: %s — raw response: %r",
            e,
            text[:500],
        )
        return None


# ---------------------------------------------------------------------------
# Article fetching (pass 2)
# ---------------------------------------------------------------------------

def fetch_article_text(url: str, timeout: int = 15) -> str | None:
    """Fetch and strip HTML from a URL. Returns cleaned text or None."""
    try:
        import requests
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (trading-bot-news-classifier)"},
        )
        resp.raise_for_status()
        # Basic HTML strip — no dependency
        text = re.sub(r"<script[^>]*>.*?</script>", "", resp.text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:3000] if text else None
    except Exception as e:
        log.warning("Failed to fetch article %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# Tier determination
# ---------------------------------------------------------------------------

def determine_tier(haiku_score: int) -> str:
    """Determine response tier from Haiku impact score."""
    if haiku_score >= 9:
        return "CRITICAL"
    if haiku_score >= 7:
        return "MAJOR"
    if haiku_score >= 4:
        return "MODERATE"
    return "MINOR"


def adjust_tier_with_price(
    tier: str,
    price_change_pct: float,
    volume_ratio: float,
) -> str:
    """For MODERATE/MAJOR, price data can UPGRADE tier (never downgrade)."""
    if tier == "CRITICAL":
        return "CRITICAL"  # already max, no price check needed
    if tier == "MAJOR":
        if price_change_pct > 5.0 or volume_ratio > 3.0:
            return "CRITICAL"
        return "MAJOR"
    if tier == "MODERATE":
        if price_change_pct > 3.0:
            return "MAJOR"
        return "MODERATE"
    return "MINOR"


def compute_conviction_delta(
    tier: str,
    haiku_score: int,
    news_direction: str,
    thesis_direction: str,
) -> tuple[float, str]:
    """Compute conviction delta and evidence side.

    Returns (delta, side) where:
      - delta > 0 means INCREASE conviction (news supports position)
      - delta < 0 means DECREASE conviction (news challenges position)
      - side is "for" or "against"
    """
    if tier == "MINOR":
        return 0.0, ""

    # Determine if news helps or hurts the position
    news_helps = _news_helps_position(news_direction, thesis_direction)

    # Base delta from tier
    if tier == "CRITICAL":
        base = 0.15
    elif tier == "MAJOR":
        base = 0.12
    else:  # MODERATE
        # Scale within tier based on haiku_score
        base = 0.05 + (haiku_score - 4) * 0.017  # 0.05 at 4, ~0.10 at 7

    if news_helps:
        return +base, "for"
    else:
        return -base, "against"


def _news_helps_position(news_direction: str, thesis_direction: str) -> bool:
    """Does the news support or challenge the position?"""
    if news_direction == "unclear" or news_direction == "mixed":
        return False  # treat uncertain news as slightly negative (conservative)
    if thesis_direction == "flat":
        return False  # no position to help
    # bullish news + long thesis = helps
    # bearish news + short thesis = helps
    # bullish news + short thesis = hurts
    # bearish news + long thesis = hurts
    if news_direction == "bullish" and thesis_direction == "long":
        return True
    if news_direction == "bearish" and thesis_direction == "short":
        return True
    return False


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

def apply_guardrails(
    requested_delta: float,
    current_conviction: float,
    rolling_24h_delta: float,
    max_per_event: float = 0.15,
    max_per_24h: float = 0.30,
    weekend: bool = False,
    weekend_factor: float = 0.5,
) -> tuple[float, str]:
    """Apply guardrails to a conviction delta.

    Returns (clamped_delta, guardrail_hit).
    """
    delta = requested_delta

    # Weekend dampening
    if weekend:
        delta *= weekend_factor

    # Per-event cap
    guardrail = ""
    if abs(delta) > max_per_event:
        delta = max_per_event if delta > 0 else -max_per_event
        guardrail = "per_event_cap"

    # 24h rolling cap
    remaining_budget = max_per_24h - abs(rolling_24h_delta)
    if remaining_budget <= 0:
        return 0.0, "24h_cap"
    if abs(delta) > remaining_budget:
        delta = remaining_budget if delta > 0 else -remaining_budget
        guardrail = guardrail or "24h_cap"

    # Conviction bounds [0, 1]
    new_conviction = current_conviction + delta
    if new_conviction > 1.0:
        delta = 1.0 - current_conviction
        guardrail = guardrail or "boundary"
    elif new_conviction < 0.0:
        delta = -current_conviction
        guardrail = guardrail or "boundary"

    return delta, guardrail


def is_weekend() -> bool:
    """Check if current time is Saturday or Sunday UTC."""
    return datetime.now(timezone.utc).weekday() >= 5


# ---------------------------------------------------------------------------
# Thesis Update Engine
# ---------------------------------------------------------------------------

class ThesisUpdaterEngine:
    """Stateful engine that classifies catalysts and updates thesis files."""

    def __init__(
        self,
        config_path: str = "data/config/thesis_updater.json",
        call_haiku_fn=None,
    ):
        self._config_path = Path(config_path)
        self._config: dict = {}
        self._call_haiku = call_haiku_fn  # injected: (messages) -> str
        self._catalysts_offset: int = 0
        self._processed_ids: set[str] = set()
        self._cooldowns: dict[str, float] = {}  # category → last_processed_ts
        self._deep_fetch_count_hour: int = 0
        self._deep_fetch_hour_start: float = 0.0
        self._last_archive_check: float = 0.0
        self._consecutive_parse_failures: int = 0
        self._parse_failure_alert_threshold: int = 3

    def reload_config(self) -> dict:
        if self._config_path.exists():
            try:
                self._config = json.loads(self._config_path.read_text())
            except Exception:
                self._config = {}
        return self._config

    @property
    def enabled(self) -> bool:
        return self._config.get("enabled", False)

    def load_audit_ids(self) -> None:
        """Rebuild processed IDs from audit trail."""
        audit_path = Path(self._config.get("audit_jsonl", "data/thesis/audit.jsonl"))
        if not audit_path.exists():
            return
        try:
            for line in audit_path.read_text().strip().split("\n"):
                if line.strip():
                    entry = json.loads(line)
                    self._processed_ids.add(entry.get("catalyst_id", ""))
        except Exception as e:
            log.warning("Failed to load audit IDs: %s", e)

    def get_rolling_24h_delta(self, market: str) -> float:
        """Sum of all conviction deltas for a market in the last 24 hours."""
        audit_path = Path(self._config.get("audit_jsonl", "data/thesis/audit.jsonl"))
        if not audit_path.exists():
            return 0.0
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        total = 0.0
        try:
            for line in audit_path.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("market") == market and entry.get("timestamp", "") >= cutoff:
                    total += entry.get("delta_applied", 0.0)
        except Exception:
            pass
        return total

    def load_new_catalysts(self) -> list[dict]:
        """Load catalysts added since last check."""
        cat_path = Path(self._config.get("catalysts_jsonl", "data/news/catalysts.jsonl"))
        if not cat_path.exists():
            return []
        try:
            lines = cat_path.read_text().strip().split("\n")
            new_lines = lines[self._catalysts_offset:]
            self._catalysts_offset = len(lines)
            return [json.loads(l) for l in new_lines if l.strip()]
        except Exception as e:
            log.warning("Failed to load catalysts: %s", e)
            return []

    def load_all_catalysts(self) -> list[dict]:
        """Load all catalysts (for initial scan)."""
        cat_path = Path(self._config.get("catalysts_jsonl", "data/news/catalysts.jsonl"))
        if not cat_path.exists():
            return []
        try:
            lines = cat_path.read_text().strip().split("\n")
            self._catalysts_offset = len(lines)
            return [json.loads(l) for l in lines if l.strip()]
        except Exception:
            return []

    def load_headline(self, headline_id: str) -> dict | None:
        """Look up a headline by ID."""
        hl_path = Path(self._config.get("headlines_jsonl", "data/news/headlines.jsonl"))
        if not hl_path.exists():
            return None
        try:
            for line in hl_path.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                h = json.loads(line)
                if h.get("id") == headline_id:
                    return h
        except Exception:
            pass
        return None

    def load_thesis(self, market: str) -> dict | None:
        """Load a thesis state file."""
        thesis_dir = Path(self._config.get("thesis_dir", "data/thesis"))
        slug = market.replace(":", "_").replace("-", "_").lower()
        path = thesis_dir / f"{slug}_state.json"
        if not path.exists():
            # Try variations
            for f in thesis_dir.glob("*_state.json"):
                try:
                    data = json.loads(f.read_text())
                    if data.get("market") == market:
                        return data
                except Exception:
                    continue
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def save_thesis(self, thesis: dict) -> None:
        """Save thesis state file (atomic write + backup)."""
        thesis_dir = Path(self._config.get("thesis_dir", "data/thesis"))
        thesis_dir.mkdir(parents=True, exist_ok=True)
        market = thesis.get("market", "unknown")
        slug = market.replace(":", "_").replace("-", "_").lower()
        path = thesis_dir / f"{slug}_state.json"
        tmp_path = path.with_suffix(".tmp")

        data = json.dumps(thesis, indent=2, default=str)
        tmp_path.write_text(data)
        tmp_path.rename(path)

        # Best-effort backup
        backup_dir = thesis_dir.parent / (thesis_dir.name + "_backup")
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"{slug}_state.json"
            backup_tmp = backup_path.with_suffix(".tmp")
            backup_tmp.write_text(data)
            backup_tmp.rename(backup_path)
        except Exception:
            pass

    def is_in_cooldown(self, category: str) -> bool:
        """Check if a category is within its cooldown window."""
        last = self._cooldowns.get(category)
        if last is None:
            return False
        cooldown_s = self._config.get("cooldown_minutes_default", 60) * 60
        return (time.time() - last) < cooldown_s

    def classify_catalyst(
        self,
        catalyst: dict,
        headline: dict | None,
    ) -> HaikuClassification | None:
        """Call Haiku to classify a catalyst. Returns classification or None."""
        if not self._call_haiku:
            log.warning("No Haiku call function configured")
            return None

        title = (headline or {}).get("title", "")
        excerpt = (headline or {}).get("body_excerpt", "")
        category = catalyst.get("category", "")
        macro_ctx = self._config.get(
            "macro_context",
            "Current dominant macro driver is the US-Iran war and oil supply.",
        )

        messages = build_haiku_prompt(title, excerpt, category, macro_ctx)
        try:
            response_text = self._call_haiku(messages)
            classification = parse_haiku_response(response_text)

            if classification is None:
                self._consecutive_parse_failures += 1
                if self._consecutive_parse_failures >= self._parse_failure_alert_threshold:
                    log.warning(
                        "ALERT: %d consecutive Haiku parse failures — "
                        "model output may have regressed. Last raw response: %r",
                        self._consecutive_parse_failures,
                        response_text[:500] if response_text else "",
                    )
            else:
                self._consecutive_parse_failures = 0

            # Pass 2: fetch full article if requested
            if classification and classification.need_full_article and headline:
                article_text = self._try_deep_fetch(headline)
                if article_text:
                    messages2 = build_haiku_prompt(
                        title, excerpt, category, macro_ctx,
                        full_article_text=article_text,
                    )
                    response_text2 = self._call_haiku(messages2)
                    classification2 = parse_haiku_response(response_text2)
                    if classification2:
                        classification = classification2

            return classification
        except Exception as e:
            log.warning("Haiku classification failed: %s", e)
            return None

    def _try_deep_fetch(self, headline: dict) -> str | None:
        """Fetch full article if within rate limit."""
        now = time.time()
        if now - self._deep_fetch_hour_start > 3600:
            self._deep_fetch_hour_start = now
            self._deep_fetch_count_hour = 0

        max_per_hour = self._config.get("deep_fetch_max_per_hour", 5)
        if self._deep_fetch_count_hour >= max_per_hour:
            return None

        url = headline.get("url", "")
        if not url:
            return None

        article_text = fetch_article_text(url)
        if article_text:
            self._deep_fetch_count_hour += 1
            # Save article for reference
            articles_dir = Path(self._config.get("articles_dir", "data/news/articles"))
            articles_dir.mkdir(parents=True, exist_ok=True)
            article_path = articles_dir / f"{headline['id']}.txt"
            try:
                article_path.write_text(article_text)
            except Exception:
                pass
        return article_text

    def process_catalyst(
        self,
        catalyst: dict,
        headline: dict | None,
        classification: HaikuClassification,
        price_data: dict | None = None,
    ) -> list[ConvictionChange]:
        """Process a classified catalyst. Returns list of conviction changes."""
        cat_id = catalyst.get("id", "")
        if cat_id in self._processed_ids:
            return []

        changes = []

        # Determine base tier
        tier = determine_tier(classification.impact_score)

        # For MODERATE/MAJOR, check price data for tier upgrade
        if tier in ("MODERATE", "MAJOR") and price_data:
            for market in classification.affected_markets:
                mdata = price_data.get(market, {})
                tier = adjust_tier_with_price(
                    tier,
                    mdata.get("price_change_pct", 0.0),
                    mdata.get("volume_ratio", 0.0),
                )

        # Log the news (all tiers including MINOR)
        self._log_news(catalyst, headline, classification, tier)

        if tier == "MINOR":
            return []

        # Process each affected market
        for market in classification.affected_markets:
            thesis = self.load_thesis(market)
            if not thesis:
                log.info("No thesis for market %s, skipping", market)
                continue

            thesis_direction = thesis.get("direction", "flat")
            current_conviction = thesis.get("conviction", 0.5)

            # Compute conviction delta
            delta, side = compute_conviction_delta(
                tier,
                classification.impact_score,
                classification.direction_hint,
                thesis_direction,
            )

            if abs(delta) < 0.001:
                continue

            # Get rolling 24h delta for this market
            rolling = self.get_rolling_24h_delta(market)

            # Apply guardrails
            clamped_delta, guardrail = apply_guardrails(
                delta,
                current_conviction,
                rolling,
                max_per_event=self._config.get("max_delta_per_event", 0.15),
                max_per_24h=self._config.get("max_delta_per_24h", 0.30),
                weekend=is_weekend(),
                weekend_factor=self._config.get("weekend_dampening_factor", 0.5),
            )

            if abs(clamped_delta) < 0.001:
                continue

            new_conviction = round(current_conviction + clamped_delta, 4)

            # Determine if defensive mode is needed
            defensive = False
            guard_override = ""
            news_hurts = not _news_helps_position(
                classification.direction_hint, thesis_direction
            )
            if tier == "CRITICAL" and news_hurts:
                defensive = True
                guard_override = "phase2_tight"
                # Also halve leverage
                current_lev = thesis.get("recommended_leverage", 5.0)
                thesis["recommended_leverage"] = round(current_lev / 2, 1)
                current_wk_cap = thesis.get("weekend_leverage_cap", 3.0)
                thesis["weekend_leverage_cap"] = round(current_wk_cap / 2, 1)

            # Build evidence text
            headline_title = (headline or {}).get("title", "unknown")
            evidence_text = f"[AUTO] {classification.summary} — {headline_title}"

            # Update thesis
            thesis["conviction"] = new_conviction
            thesis["last_evaluation_ts"] = int(time.time() * 1000)

            # Append evidence
            evidence_entry = {
                "timestamp": int(time.time() * 1000),
                "source": "news_auto",
                "summary": evidence_text,
                "weight": min(1.0, classification.impact_score / 10.0),
                "url": (headline or {}).get("url", ""),
                "exit_cause": "",
            }
            evidence_list = f"evidence_{side}" if side else "evidence_against"
            if evidence_list not in thesis:
                thesis[evidence_list] = []
            thesis[evidence_list].append(evidence_entry)

            # Save thesis
            try:
                self.save_thesis(thesis)
            except Exception as e:
                log.error("Failed to save thesis for %s: %s", market, e)
                continue

            # Build audit record
            price_info = (price_data or {}).get(market, {})
            change = ConvictionChange(
                timestamp=datetime.now(timezone.utc).isoformat(),
                catalyst_id=catalyst.get("id", ""),
                headline=headline_title,
                market=market,
                haiku_impact_score=classification.impact_score,
                haiku_direction=classification.direction_hint,
                tier=tier,
                conviction_before=current_conviction,
                conviction_after=new_conviction,
                delta_requested=delta,
                delta_applied=clamped_delta,
                guardrail_hit=guardrail,
                evidence_side=side,
                evidence_text=evidence_text,
                defensive_mode=defensive,
                guard_override=guard_override,
                price_change_pct=price_info.get("price_change_pct", 0.0),
                volume_ratio=price_info.get("volume_ratio", 0.0),
            )
            changes.append(change)

            # Write audit
            self._write_audit(change)

        # Mark processed
        self._processed_ids.add(catalyst.get("id", ""))
        self._cooldowns[catalyst.get("category", "")] = time.time()

        return changes

    def _log_news(
        self,
        catalyst: dict,
        headline: dict | None,
        classification: HaikuClassification,
        tier: str,
    ) -> None:
        """Log all classified news to news_log.jsonl."""
        log_path = Path(self._config.get("news_log_jsonl", "data/thesis/news_log.jsonl"))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = NewsLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            catalyst_id=catalyst.get("id", ""),
            headline=(headline or {}).get("title", ""),
            category=catalyst.get("category", ""),
            haiku_impact_score=classification.impact_score,
            haiku_direction=classification.direction_hint,
            haiku_summary=classification.summary,
            tier=tier,
            affected_markets=classification.affected_markets,
        )
        try:
            with open(log_path, "a") as f:
                f.write(json.dumps(asdict(entry)) + "\n")
        except Exception as e:
            log.warning("Failed to write news log: %s", e)

    def _write_audit(self, change: ConvictionChange) -> None:
        """Append a conviction change to the audit trail."""
        audit_path = Path(self._config.get("audit_jsonl", "data/thesis/audit.jsonl"))
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(audit_path, "a") as f:
                f.write(json.dumps(asdict(change)) + "\n")
        except Exception as e:
            log.warning("Failed to write audit: %s", e)

    def format_alert(self, change: ConvictionChange) -> str:
        """Format a conviction change as a Telegram alert."""
        if change.tier == "CRITICAL":
            if change.defensive_mode:
                return (
                    f"🚨 CRITICAL NEWS — {change.market}\n\n"
                    f"📰 {change.headline}\n\n"
                    f"Conviction: {change.conviction_before:.2f} → {change.conviction_after:.2f}\n"
                    f"⚡ DEFENSIVE MODE ACTIVATED\n"
                    f"  • Guard → Phase 2 (tight retrace)\n"
                    f"  • Leverage halved\n\n"
                    f"Review and /overrule if needed."
                )
            else:
                return (
                    f"✅ CRITICAL NEWS SUPPORTS POSITION — {change.market}\n\n"
                    f"📰 {change.headline}\n\n"
                    f"Conviction: {change.conviction_before:.2f} → {change.conviction_after:.2f}\n"
                    f"Position strengthened."
                )
        elif change.tier == "MAJOR":
            emoji = "⚠️"
        else:
            emoji = "ℹ️"

        return (
            f"{emoji} {change.tier} NEWS — {change.market}\n\n"
            f"📰 {change.headline}\n"
            f"Conviction: {change.conviction_before:.2f} → {change.conviction_after:.2f} "
            f"({'+' if change.delta_applied > 0 else ''}{change.delta_applied:.2f})\n"
            f"Evidence: {change.evidence_side}"
        )
