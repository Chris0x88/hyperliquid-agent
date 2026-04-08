"""Supply Disruption Ledger — pure logic.

Spec: docs/plans/OIL_BOT_PATTERN_02_SUPPLY_LEDGER.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Disruption:
    id: str
    source: str
    source_ref: str
    facility_name: str
    facility_type: str
    location: str
    region: str
    volume_offline: float | None
    volume_unit: str | None
    incident_date: datetime
    expected_recovery: datetime | None
    confidence: int
    status: str
    instruments: list[str]
    notes: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SupplyState:
    computed_at: datetime
    total_offline_bpd: float
    total_offline_mcfd: float
    by_region: dict[str, float]
    by_facility_type: dict[str, float]
    active_chokepoints: list[str]
    active_disruption_count: int
    high_confidence_count: int


REGION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "russia": ("russia", "russian", "volgograd", "moscow", "ryazan", "samara", "ust-luga", "novorossiysk"),
    "iran": ("iran", "iranian", "tehran", "abadan", "bandar abbas", "kharg"),
    "saudi": ("saudi", "arabia", "ras tanura", "abqaiq", "jeddah", "yanbu"),
    "hormuz_strait": ("hormuz",),
    "red_sea": ("red sea", "bab-el-mandeb", "bab el mandeb", "houthi", "yemen"),
    "suez": ("suez",),
    "malacca_strait": ("malacca",),
    "us_gulf": ("cushing", "permian", "eagle ford", "gulf of mexico", "us gulf", "houston"),
    "nigeria": ("nigeria", "nigerian", "niger delta"),
    "venezuela": ("venezuela", "venezuelan", "pdvsa"),
    "libya": ("libya", "libyan"),
}


def classify_region(text: str) -> str:
    """Map free-text headline/location to a canonical region key."""
    t = text.lower()
    for region, keywords in REGION_KEYWORDS.items():
        if any(k in t for k in keywords):
            return region
    return "unknown"


_FACILITY_HINTS = (
    ("pipeline", "pipeline"),
    ("oilfield", "oilfield"),
    ("oil field", "oilfield"),
    ("terminal", "terminal"),
    ("gas plant", "gas_plant"),
    ("refinery", "refinery"),
)


def refine_facility_type(text: str, default: str) -> str:
    t = text.lower()
    for keyword, facility in _FACILITY_HINTS:
        if keyword in t:
            return facility
    return default


import yaml


@dataclass(frozen=True)
class AutoExtractRule:
    catalyst_category: str
    facility_type: str
    confidence: int
    status: str


def load_auto_extract_rules(yaml_path: str) -> list[AutoExtractRule]:
    with open(yaml_path, "r") as f:
        doc = yaml.safe_load(f) or {}
    out: list[AutoExtractRule] = []
    for m in doc.get("mappings", []):
        out.append(AutoExtractRule(
            catalyst_category=m["catalyst_category"],
            facility_type=m["facility_type"],
            confidence=int(m["confidence"]),
            status=m["status"],
        ))
    return out
