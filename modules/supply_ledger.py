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


import hashlib


def _hash_disruption(facility_name: str, incident_date: datetime) -> str:
    key = f"{facility_name}|{incident_date.isoformat()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def auto_extract_from_catalyst(
    catalyst: dict,
    rules: list[AutoExtractRule],
) -> Disruption | None:
    """Turn a Catalyst record (dict or dataclass) into a Disruption.

    Returns None if no matching rule, or the category is not in the auto-extract set.
    """
    category = catalyst["category"] if isinstance(catalyst, dict) else catalyst.category
    rule = next((r for r in rules if r.catalyst_category == category), None)
    if rule is None:
        return None

    if isinstance(catalyst, dict):
        title = catalyst.get("_headline_title") or catalyst.get("rationale", "")
        cat_id = catalyst["id"]
        headline_id = catalyst.get("headline_id", "")
        instruments = list(catalyst.get("instruments", []))
        event_date = catalyst["event_date"]
        if isinstance(event_date, str):
            event_date = datetime.fromisoformat(event_date)
    else:
        title = getattr(catalyst, "_headline_title", "") or catalyst.rationale
        cat_id = catalyst.id
        headline_id = catalyst.headline_id
        instruments = list(catalyst.instruments)
        event_date = catalyst.event_date

    facility_type = refine_facility_type(title, default=rule.facility_type)
    region = classify_region(title)
    facility_name = title[:60].strip() or "unknown"

    now = datetime.now(tz=event_date.tzinfo) if event_date.tzinfo else datetime.utcnow()
    return Disruption(
        id=_hash_disruption(facility_name, event_date),
        source="news_auto",
        source_ref=cat_id,
        facility_name=facility_name,
        facility_type=facility_type,
        location=region,
        region=region,
        volume_offline=None,
        volume_unit=None,
        incident_date=event_date,
        expected_recovery=None,
        confidence=rule.confidence,
        status=rule.status,
        instruments=instruments,
        notes=f"auto-extracted from catalyst {cat_id} (headline {headline_id})",
        created_at=now,
        updated_at=now,
    )
