"""ThesisState — the contract between the AI scheduled task (writer) and the daemon (reader).

The AI writes conviction state here. The daemon reads it every tick to drive execution.
This is the core of the two-layer architecture: AI judgment → daemon execution.

File layout: data/thesis/{market_slug}_state.json
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Any, Dict

log = logging.getLogger("thesis")

# Directory for thesis state files (relative to agent-cli working dir)
DEFAULT_THESIS_DIR = "data/thesis"


@dataclass
class Evidence:
    """One piece of evidence for/against the thesis."""
    timestamp: int          # unix ms
    source: str             # "news", "price_action", "fundamentals", "autoresearch"
    summary: str            # one-line summary
    weight: float           # 0.0-1.0 how much to weight this evidence
    url: str = ""           # optional source URL
    exit_cause: str = ""    # if related to an exit: "thesis_invalidation" | "weekend_wick" | "funding" | "other"

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "Evidence":
        return cls(
            timestamp=d.get("timestamp", 0),
            source=d.get("source", ""),
            summary=d.get("summary", ""),
            weight=float(d.get("weight", 0.5)),
            url=d.get("url", ""),
            exit_cause=d.get("exit_cause", ""),
        )


@dataclass
class ThesisState:
    """AI-authored conviction state for one market.

    Written by the scheduled task. Read by thesis_engine.py every daemon tick.
    The execution_engine uses conviction to size positions dynamically.
    """
    market: str                          # e.g. "xyz:BRENTOIL" or "BTC-PERP"
    direction: str                        # "long" | "short" | "flat"
    conviction: float                     # 0.0-1.0 (Druckenmiller bands)
    thesis_summary: str = ""             # human-readable thesis
    invalidation_conditions: List[str] = field(default_factory=list)  # NOT price levels
    evidence_for: List[Evidence] = field(default_factory=list)
    evidence_against: List[Evidence] = field(default_factory=list)

    # Execution guidance (AI recommendations, not hard rules)
    recommended_leverage: float = 5.0
    recommended_size_pct: float = 0.10   # fraction of account
    weekend_leverage_cap: float = 3.0    # reduced during thin liquidity
    take_profit_price: Optional[float] = None  # thesis-based TP (e.g. gold→$10k). None = no TP.

    # Tactical trade guidance
    allow_tactical_trades: bool = True   # if True, execution_engine may enter/exit intraday
    tactical_notes: str = ""             # notes for the execution engine

    # Metadata
    last_evaluation_ts: int = 0          # unix ms when AI last wrote this
    snapshot_ref: str = ""               # which account snapshot was used
    notes: str = ""                      # misc AI notes

    def __post_init__(self):
        if not self.last_evaluation_ts:
            self.last_evaluation_ts = int(time.time() * 1000)

    @property
    def age_hours(self) -> float:
        """How old this evaluation is in hours."""
        return (time.time() * 1000 - self.last_evaluation_ts) / 3_600_000

    @property
    def needs_review(self) -> bool:
        """True after 24h — triggers Telegram reminder, but doesn't reduce conviction."""
        return self.age_hours > 24.0

    @property
    def is_stale(self) -> bool:
        """True after 7 days — starts tapering conviction."""
        return self.age_hours > 168.0  # 7 days

    @property
    def is_very_stale(self) -> bool:
        """True after 14 days — full defensive mode."""
        return self.age_hours > 336.0  # 14 days

    def effective_conviction(self) -> float:
        """Runtime conviction with tiered staleness.

        - < 7 days: full conviction (thesis holds for weeks/months)
        - 7-14 days: taper linearly from conviction → 0.3
        - > 14 days: clamp to 0.3 (defensive)

        Thesis-driven trades hold for weeks. 24h hard clamp was killing the edge.
        Now: 24h sends a review reminder (handled by heartbeat), 7d starts tapering.
        """
        if self.is_very_stale:
            return min(self.conviction, 0.3)
        if self.is_stale:
            # Linear taper: at 7d = full conviction, at 14d = 0.3
            hours_past_stale = self.age_hours - 168.0
            taper = max(0.0, min(1.0, hours_past_stale / 168.0))
            return self.conviction - taper * (self.conviction - 0.3)
        return self.conviction

    def market_slug(self) -> str:
        """Filesystem-safe market name."""
        return self.market.replace(":", "_").replace("/", "_").replace("-", "_").lower()

    def save(self, thesis_dir: str = DEFAULT_THESIS_DIR) -> str:
        """Persist state to disk. Returns filepath written."""
        Path(thesis_dir).mkdir(parents=True, exist_ok=True)
        path = os.path.join(thesis_dir, f"{self.market_slug()}_state.json")
        data = {
            "market": self.market,
            "direction": self.direction,
            "conviction": self.conviction,
            "thesis_summary": self.thesis_summary,
            "invalidation_conditions": self.invalidation_conditions,
            "evidence_for": [e.to_dict() for e in self.evidence_for],
            "evidence_against": [e.to_dict() for e in self.evidence_against],
            "recommended_leverage": self.recommended_leverage,
            "recommended_size_pct": self.recommended_size_pct,
            "weekend_leverage_cap": self.weekend_leverage_cap,
            "allow_tactical_trades": self.allow_tactical_trades,
            "tactical_notes": self.tactical_notes,
            "take_profit_price": self.take_profit_price,
            "last_evaluation_ts": self.last_evaluation_ts,
            "snapshot_ref": self.snapshot_ref,
            "notes": self.notes,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        log.info("ThesisState saved: %s  conviction=%.2f  direction=%s", path, self.conviction, self.direction)
        return path

    @classmethod
    def load(cls, market: str, thesis_dir: str = DEFAULT_THESIS_DIR) -> Optional["ThesisState"]:
        """Load thesis state for a market. Returns None if not found."""
        slug = market.replace(":", "_").replace("/", "_").replace("-", "_").lower()
        path = os.path.join(thesis_dir, f"{slug}_state.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            state = cls(
                market=data["market"],
                direction=data.get("direction", "flat"),
                conviction=float(data.get("conviction", 0.3)),
                thesis_summary=data.get("thesis_summary", ""),
                invalidation_conditions=data.get("invalidation_conditions", []),
                evidence_for=[Evidence.from_dict(e) for e in data.get("evidence_for", [])],
                evidence_against=[Evidence.from_dict(e) for e in data.get("evidence_against", [])],
                recommended_leverage=float(data.get("recommended_leverage", 5.0)),
                recommended_size_pct=float(data.get("recommended_size_pct", 0.10)),
                weekend_leverage_cap=float(data.get("weekend_leverage_cap", 3.0)),
                allow_tactical_trades=data.get("allow_tactical_trades", True),
                tactical_notes=data.get("tactical_notes", ""),
                take_profit_price=data.get("take_profit_price"),
                last_evaluation_ts=int(data.get("last_evaluation_ts", 0)),
                snapshot_ref=data.get("snapshot_ref", ""),
                notes=data.get("notes", ""),
            )
            return state
        except Exception as e:
            log.error("Failed to load ThesisState for %s: %s", market, e)
            return None

    @classmethod
    def load_all(cls, thesis_dir: str = DEFAULT_THESIS_DIR) -> Dict[str, "ThesisState"]:
        """Load all thesis states from disk. Returns {market: ThesisState}."""
        result = {}
        p = Path(thesis_dir)
        if not p.exists():
            return result
        for fp in p.glob("*_state.json"):
            try:
                with open(fp) as f:
                    data = json.load(f)
                market = data.get("market", "")
                if not market:
                    continue
                state = cls.load(market, thesis_dir)
                if state:
                    result[market] = state
            except Exception as e:
                log.warning("Skipping malformed thesis file %s: %s", fp, e)
        return result
