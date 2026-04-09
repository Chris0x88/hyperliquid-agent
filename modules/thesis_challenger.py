"""ThesisChallenger — mechanical invalidation detector.

Compares incoming catalysts against thesis invalidation_conditions.
When a catalyst headline semantically matches an invalidation condition,
fires a CRITICAL alert and flags the thesis for review.

This is PURE PYTHON — zero LLM calls. Pattern matching only.
AI review is triggered on-demand by the user or at 12h cadence.

Architecture:
  - Reads catalysts.jsonl (new entries since last check)
  - Reads thesis state files
  - For each thesis with invalidation_conditions:
    - Extracts keywords from each condition
    - Matches against catalyst headlines + categories
    - If match found: fires Alert, writes challenge record
  - Challenge records stored in data/thesis/challenges.jsonl
  - Telegram gets immediate alert with matched condition + headline

Kill switch: data/config/thesis_challenger.json → enabled: false
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("thesis_challenger")

# -- Keyword extraction patterns for invalidation conditions --
# These map common thesis language to catalyst categories and headline keywords

CONDITION_CATEGORY_MAP: dict[str, list[str]] = {
    # Ceasefire / peace / deal language
    "ceasefire": ["iran_deal", "ceasefire", "peace_deal", "trump_oil_announcement"],
    "peace": ["iran_deal", "ceasefire", "peace_deal", "trump_oil_announcement"],
    "deal": ["iran_deal", "peace_deal", "trump_oil_announcement"],
    "resolution": ["iran_deal", "ceasefire", "peace_deal"],
    "truce": ["iran_deal", "ceasefire"],
    "negotiations": ["iran_deal", "peace_deal"],
    # Military / strike language
    "strike": ["military_strike", "shipping_attack", "infrastructure_attack"],
    "attack": ["shipping_attack", "military_strike", "tanker_attack"],
    "kharg": ["military_strike", "infrastructure_attack"],
    "military": ["military_strike"],
    "bomb": ["military_strike"],
    # Supply / SPR language
    "spr": ["spr_release", "strategic_reserve"],
    "reserve": ["spr_release", "strategic_reserve"],
    "opec": ["opec_decision", "opec_cut", "opec_increase"],
    "production": ["production_change", "opec_decision"],
    # Sanctions
    "sanction": ["sanctions_change", "iran_sanctions"],
    "embargo": ["sanctions_change", "embargo"],
    # Price levels
    "hormuz": ["hormuz_closure", "hormuz_reopening", "shipping_attack"],
    "strait": ["hormuz_closure", "hormuz_reopening"],
    # Deadline language
    "deadline": ["trump_oil_announcement", "iran_deal"],
    "trump": ["trump_oil_announcement", "iran_deal"],
}

# Headline keyword patterns (regex fragments)
CONDITION_HEADLINE_PATTERNS: dict[str, list[str]] = {
    "ceasefire": [r"ceasefire", r"cease.fire", r"truce", r"peace\s+deal"],
    "peace": [r"peace", r"ceasefire", r"truce", r"diplomatic"],
    "deal": [r"deal", r"agreement", r"accord", r"pact"],
    "resolution": [r"resolv", r"resolution", r"agreement", r"ceasefire"],
    "strike": [r"strike", r"attack", r"bomb", r"missile"],
    "kharg": [r"kharg", r"iranian?\s+oil\s+infra"],
    "spr": [r"spr\b", r"strategic\s+petroleum", r"reserve\s+release"],
    "hormuz": [r"hormuz", r"strait"],
    "deadline": [r"deadline", r"ultimatum", r"expir"],
    "trump": [r"trump", r"white\s+house", r"president"],
    "sanction": [r"sanction", r"embargo", r"restrict"],
    "opec": [r"opec", r"cartel", r"production\s+cut"],
}


@dataclass
class ChallengeRecord:
    """A matched invalidation condition triggered by a catalyst."""
    id: str
    thesis_market: str
    invalidation_condition: str
    matched_catalyst_id: str
    matched_headline: str
    matched_category: str
    match_type: str  # "category" or "keyword"
    match_score: float  # 0-1, higher = stronger match
    created_at: str
    reviewed: bool = False
    review_outcome: str = ""  # "confirmed_invalid", "still_valid", "needs_update"


def _extract_keywords(condition: str) -> list[str]:
    """Extract meaningful keywords from an invalidation condition string."""
    # Lowercase and strip punctuation
    text = condition.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    words = text.split()

    # Filter stopwords
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "must", "ought",
        "if", "or", "and", "but", "not", "no", "nor", "so", "yet", "both",
        "than", "that", "this", "these", "those", "it", "its", "of", "in",
        "on", "at", "to", "for", "with", "by", "from", "as", "into", "about",
        "up", "out", "down", "off", "over", "under", "any", "all", "each",
        "every", "either", "neither", "before", "after", "above", "below",
        "between", "through", "during", "without", "within", "hard", "stop",
        "close", "passes", "without", "before", "shows", "data",
    }
    return [w for w in words if w not in stopwords and len(w) > 2]


def match_condition_against_catalyst(
    condition: str,
    catalyst_category: str,
    headline_title: str,
) -> tuple[bool, str, float]:
    """Check if a catalyst matches an invalidation condition.

    Returns (matched, match_type, score).
    """
    keywords = _extract_keywords(condition)
    condition_lower = condition.lower()

    best_score = 0.0
    best_type = ""

    # 1. Category match — check if catalyst category maps to any condition keyword
    for kw in keywords:
        mapped_cats = CONDITION_CATEGORY_MAP.get(kw, [])
        if catalyst_category in mapped_cats:
            score = 0.7  # base category match
            # Boost if multiple keywords match
            matching_kws = sum(
                1 for k in keywords
                if catalyst_category in CONDITION_CATEGORY_MAP.get(k, [])
            )
            score = min(1.0, score + 0.1 * (matching_kws - 1))
            if score > best_score:
                best_score = score
                best_type = "category"

    # 2. Headline keyword match — check if headline contains condition-relevant words
    headline_lower = headline_title.lower()
    keyword_hits = 0
    for kw in keywords:
        patterns = CONDITION_HEADLINE_PATTERNS.get(kw, [])
        for pat in patterns:
            if re.search(pat, headline_lower):
                keyword_hits += 1
                break
        # Also check if the keyword itself appears in the headline
        if kw in headline_lower:
            keyword_hits += 1

    if keyword_hits >= 2:
        score = min(1.0, 0.5 + 0.15 * keyword_hits)
        if score > best_score:
            best_score = score
            best_type = "keyword"

    # 3. Direct phrase match — strongest signal
    # Check for key phrases from the condition appearing in the headline
    phrases_to_check = []
    # Extract 2-3 word phrases
    words = condition_lower.split()
    for i in range(len(words) - 1):
        phrase = f"{words[i]} {words[i+1]}"
        phrase_clean = re.sub(r'[^\w\s]', '', phrase).strip()
        if len(phrase_clean) > 5:
            phrases_to_check.append(phrase_clean)

    for phrase in phrases_to_check:
        if phrase in headline_lower:
            score = 0.9
            if score > best_score:
                best_score = score
                best_type = "phrase"

    matched = best_score >= 0.6
    return matched, best_type, best_score


def check_thesis_against_catalysts(
    thesis_state: dict,
    catalysts: list[dict],
    headlines: dict[str, dict],
) -> list[ChallengeRecord]:
    """Check all invalidation conditions against recent catalysts.

    Args:
        thesis_state: Loaded thesis JSON
        catalysts: List of catalyst dicts from catalysts.jsonl
        headlines: Map of headline_id → headline dict for title lookup

    Returns:
        List of ChallengeRecord for any matches found
    """
    market = thesis_state.get("market", "unknown")
    conditions = thesis_state.get("invalidation_conditions", [])
    if not conditions:
        return []

    # For each condition, find the BEST matching catalyst (highest score)
    # This prevents flooding with 47 alerts when 3 would do
    best_per_condition: dict[str, tuple[float, ChallengeRecord]] = {}

    for condition in conditions:
        for cat in catalysts:
            cat_id = cat.get("id", "")
            cat_category = cat.get("category", "")
            headline_id = cat.get("headline_id", "")
            headline = headlines.get(headline_id, {})
            headline_title = headline.get("title", "")

            matched, match_type, score = match_condition_against_catalyst(
                condition, cat_category, headline_title,
            )

            if not matched:
                continue

            challenge_id = hashlib.md5(
                f"{market}:{condition}:{cat_id}".encode()
            ).hexdigest()[:16]

            record = ChallengeRecord(
                id=challenge_id,
                thesis_market=market,
                invalidation_condition=condition,
                matched_catalyst_id=cat_id,
                matched_headline=headline_title,
                matched_category=cat_category,
                match_type=match_type,
                match_score=score,
                created_at=datetime.now(timezone.utc).isoformat(),
            )

            existing = best_per_condition.get(condition)
            if existing is None or score > existing[0]:
                best_per_condition[condition] = (score, record)

    return [record for _, record in best_per_condition.values()]


class ThesisChallengerEngine:
    """Stateful engine that tracks which catalysts have been checked."""

    def __init__(
        self,
        thesis_dir: str = "data/thesis",
        catalysts_path: str = "data/news/catalysts.jsonl",
        headlines_path: str = "data/news/headlines.jsonl",
        challenges_path: str = "data/thesis/challenges.jsonl",
        config_path: str = "data/config/thesis_challenger.json",
    ):
        self._thesis_dir = Path(thesis_dir)
        self._catalysts_path = Path(catalysts_path)
        self._headlines_path = Path(headlines_path)
        self._challenges_path = Path(challenges_path)
        self._config_path = Path(config_path)
        self._last_catalyst_offset: int = 0
        self._alerted_challenge_ids: set[str] = set()

    @property
    def enabled(self) -> bool:
        if not self._config_path.exists():
            return True  # default enabled
        try:
            cfg = json.loads(self._config_path.read_text())
            return cfg.get("enabled", True)
        except Exception:
            return True

    def load_theses(self) -> list[dict]:
        """Load all thesis state files."""
        theses = []
        if not self._thesis_dir.exists():
            return theses
        for f in self._thesis_dir.glob("*_state.json"):
            try:
                theses.append(json.loads(f.read_text()))
            except Exception as e:
                log.warning("Failed to load thesis %s: %s", f, e)
        return theses

    def load_new_catalysts(self) -> list[dict]:
        """Load catalysts added since last check."""
        if not self._catalysts_path.exists():
            return []
        try:
            lines = self._catalysts_path.read_text().strip().split("\n")
            new_lines = lines[self._last_catalyst_offset:]
            self._last_catalyst_offset = len(lines)
            catalysts = []
            for line in new_lines:
                if line.strip():
                    catalysts.append(json.loads(line))
            return catalysts
        except Exception as e:
            log.warning("Failed to load catalysts: %s", e)
            return []

    def load_all_catalysts(self) -> list[dict]:
        """Load all catalysts (for initial scan)."""
        if not self._catalysts_path.exists():
            return []
        try:
            catalysts = []
            for line in self._catalysts_path.read_text().strip().split("\n"):
                if line.strip():
                    catalysts.append(json.loads(line))
            self._last_catalyst_offset = len(catalysts)
            return catalysts
        except Exception as e:
            log.warning("Failed to load catalysts: %s", e)
            return []

    def load_headlines_map(self) -> dict[str, dict]:
        """Load headline_id → headline dict for title lookup."""
        if not self._headlines_path.exists():
            return {}
        headlines = {}
        try:
            for line in self._headlines_path.read_text().strip().split("\n"):
                if line.strip():
                    h = json.loads(line)
                    headlines[h.get("id", "")] = h
        except Exception as e:
            log.warning("Failed to load headlines: %s", e)
        return headlines

    def scan(self, full: bool = False) -> list[ChallengeRecord]:
        """Run a scan. Returns new challenges found.

        Args:
            full: If True, scan ALL catalysts (not just new ones)
        """
        if not self.enabled:
            return []

        theses = self.load_theses()
        catalysts = self.load_all_catalysts() if full else self.load_new_catalysts()
        if not catalysts:
            return []

        headlines = self.load_headlines_map()
        all_challenges = []

        for thesis in theses:
            challenges = check_thesis_against_catalysts(thesis, catalysts, headlines)
            # Filter out already-alerted
            new_challenges = [
                c for c in challenges if c.id not in self._alerted_challenge_ids
            ]
            all_challenges.extend(new_challenges)

        # Persist new challenges
        if all_challenges:
            self._persist_challenges(all_challenges)
            for c in all_challenges:
                self._alerted_challenge_ids.add(c.id)

        return all_challenges

    def _persist_challenges(self, challenges: list[ChallengeRecord]) -> None:
        """Append challenges to JSONL file."""
        self._challenges_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._challenges_path, "a") as f:
            for c in challenges:
                f.write(json.dumps(asdict(c)) + "\n")

    def format_alert(self, challenge: ChallengeRecord) -> str:
        """Format a challenge as a Telegram alert message."""
        return (
            f"🚨 THESIS CHALLENGE — {challenge.thesis_market}\n\n"
            f"Invalidation condition:\n"
            f"  \"{challenge.invalidation_condition}\"\n\n"
            f"Matched by:\n"
            f"  📰 {challenge.matched_headline}\n"
            f"  Category: {challenge.matched_category}\n"
            f"  Match: {challenge.match_type} ({challenge.match_score:.0%})\n\n"
            f"⚠️ REVIEW THESIS IMMEDIATELY\n"
            f"The thesis may be invalidated. Check conditions and update."
        )
