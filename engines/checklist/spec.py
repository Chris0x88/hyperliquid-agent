"""Checklist framework dataclasses and YAML schema documentation.

Each market has an optional YAML config at data/checklist/<market_bare>.yaml.
If absent, defaults apply (all standard checks enabled at default weights).

YAML schema:
------------
market: SILVER           # bare name without xyz: prefix
enabled: true
items:
  sl_on_exchange:
    enabled: true
    weight: 10           # relative weight in score (int 1-10)
  tp_on_exchange:
    enabled: true
    weight: 5
  # ... other item keys matching ITEM_DEFAULTS

All evaluator outputs: ("pass"|"warn"|"fail", "one-line reason", optional_data_dict)

ChecklistResult fields:
  status      — worst of all item statuses: "pass" | "warn" | "fail"
  score       — 0.0-1.0 weighted pass rate (1.0 = all pass)
  items       — list of ChecklistItem (one per evaluator)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Canonical item keys with default weights and modes
ITEM_DEFAULTS: Dict[str, Dict[str, Any]] = {
    # ---- Evening-only ----
    "sl_on_exchange":      {"weight": 10, "mode": "evening", "category": "safety"},
    "tp_on_exchange":      {"weight": 5,  "mode": "evening", "category": "safety"},
    "cumulative_risk":     {"weight": 7,  "mode": "evening", "category": "risk"},
    "leverage_vs_thesis":  {"weight": 6,  "mode": "evening", "category": "risk"},
    "weekend_leverage":    {"weight": 8,  "mode": "evening", "category": "risk"},
    "news_catalyst_12h":   {"weight": 4,  "mode": "evening", "category": "news"},
    "funding_cost":        {"weight": 5,  "mode": "evening", "category": "cost"},
    # ---- Morning-only ----
    "overnight_fills":     {"weight": 3,  "mode": "morning", "category": "debrief"},
    "overnight_closed":    {"weight": 3,  "mode": "morning", "category": "debrief"},
    "cascade_events":      {"weight": 5,  "mode": "morning", "category": "debrief"},
    "new_catalysts":       {"weight": 4,  "mode": "morning", "category": "news"},
    "pending_actions":     {"weight": 3,  "mode": "morning", "category": "action"},
    "asia_setup":          {"weight": 3,  "mode": "morning", "category": "setup"},
    # ---- Both ----
    "sweep_risk":          {"weight": 8,  "mode": "both",    "category": "manipulation"},
}

EvalResult = Tuple[str, str, Optional[Dict[str, Any]]]  # (status, reason, data)


@dataclass
class ChecklistItem:
    """Result for a single evaluator."""
    name: str
    status: str         # "pass" | "warn" | "fail" | "skip"
    reason: str         # one-line human-readable explanation
    weight: int         # from ITEM_DEFAULTS
    mode: str           # "evening" | "morning" | "both"
    category: str
    data: Optional[Dict[str, Any]] = None  # optional structured detail

    @property
    def emoji(self) -> str:
        return {"pass": "✅", "warn": "⚠️", "fail": "❌", "skip": "⏭"}.get(self.status, "❓")


@dataclass
class ChecklistResult:
    """Aggregated result for one market, one mode."""
    market: str
    mode: str           # "evening" | "morning"
    timestamp: int      # Unix epoch seconds
    items: List[ChecklistItem] = field(default_factory=list)

    @property
    def status(self) -> str:
        """Worst status across all non-skipped items."""
        statuses = [i.status for i in self.items if i.status != "skip"]
        if "fail" in statuses:
            return "fail"
        if "warn" in statuses:
            return "warn"
        return "pass"

    @property
    def score(self) -> float:
        """Weighted pass rate 0.0-1.0."""
        total_w = sum(i.weight for i in self.items if i.status != "skip")
        if total_w == 0:
            return 1.0
        pass_w = sum(i.weight for i in self.items if i.status == "pass")
        return pass_w / total_w

    @property
    def fails(self) -> List[ChecklistItem]:
        return [i for i in self.items if i.status == "fail"]

    @property
    def warns(self) -> List[ChecklistItem]:
        return [i for i in self.items if i.status == "warn"]

    def to_dict(self) -> dict:
        return {
            "market": self.market,
            "mode": self.mode,
            "timestamp": self.timestamp,
            "status": self.status,
            "score": round(self.score, 3),
            "items": [
                {
                    "name": i.name,
                    "status": i.status,
                    "reason": i.reason,
                    "weight": i.weight,
                    "mode": i.mode,
                    "category": i.category,
                    "data": i.data,
                }
                for i in self.items
            ],
        }


@dataclass
class MarketChecklist:
    """Config object parsed from YAML (or built from defaults)."""
    market: str
    enabled: bool = True
    item_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def item_config(self, key: str) -> Dict[str, Any]:
        """Merge defaults with per-market YAML overrides."""
        base = dict(ITEM_DEFAULTS.get(key, {}))
        base.update(self.item_overrides.get(key, {}))
        return base

    def is_item_enabled(self, key: str) -> bool:
        cfg = self.item_overrides.get(key, {})
        return bool(cfg.get("enabled", True))
