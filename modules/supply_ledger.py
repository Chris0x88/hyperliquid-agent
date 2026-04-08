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
    # Chokepoints / narrow maritime regions first, so headlines like
    # "Hormuz strait closed after Iranian navy seizure" classify as
    # hormuz_strait rather than iran. (Inline fix: plan had country regions first.)
    "hormuz_strait": ("hormuz",),
    "red_sea": ("red sea", "bab-el-mandeb", "bab el mandeb", "houthi", "yemen"),
    "suez": ("suez",),
    "malacca_strait": ("malacca",),
    "russia": ("russia", "russian", "volgograd", "moscow", "ryazan", "samara", "ust-luga", "novorossiysk"),
    "iran": ("iran", "iranian", "tehran", "abadan", "bandar abbas", "kharg"),
    "saudi": ("saudi", "arabia", "ras tanura", "abqaiq", "jeddah", "yanbu"),
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


import json
from dataclasses import asdict
from pathlib import Path


def _disruption_to_dict(d: Disruption) -> dict:
    out = asdict(d)
    out["incident_date"] = d.incident_date.isoformat()
    out["expected_recovery"] = d.expected_recovery.isoformat() if d.expected_recovery else None
    out["created_at"] = d.created_at.isoformat()
    out["updated_at"] = d.updated_at.isoformat()
    return out


def _disruption_from_dict(raw: dict) -> Disruption:
    return Disruption(
        id=raw["id"],
        source=raw["source"],
        source_ref=raw["source_ref"],
        facility_name=raw["facility_name"],
        facility_type=raw["facility_type"],
        location=raw["location"],
        region=raw["region"],
        volume_offline=raw.get("volume_offline"),
        volume_unit=raw.get("volume_unit"),
        incident_date=datetime.fromisoformat(raw["incident_date"]),
        expected_recovery=datetime.fromisoformat(raw["expected_recovery"]) if raw.get("expected_recovery") else None,
        confidence=int(raw["confidence"]),
        status=raw["status"],
        instruments=list(raw.get("instruments", [])),
        notes=raw.get("notes", ""),
        created_at=datetime.fromisoformat(raw["created_at"]),
        updated_at=datetime.fromisoformat(raw["updated_at"]),
    )


def append_disruption(jsonl_path: str, d: Disruption) -> None:
    p = Path(jsonl_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(_disruption_to_dict(d)) + "\n")


def read_disruptions(jsonl_path: str) -> list[Disruption]:
    p = Path(jsonl_path)
    if not p.exists():
        return []
    out: list[Disruption] = []
    with p.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(_disruption_from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return out


def latest_per_id(rows: list[Disruption]) -> list[Disruption]:
    """Keep only the latest row per id (by updated_at)."""
    by_id: dict[str, Disruption] = {}
    for r in rows:
        prev = by_id.get(r.id)
        if prev is None or r.updated_at > prev.updated_at:
            by_id[r.id] = r
    return list(by_id.values())
