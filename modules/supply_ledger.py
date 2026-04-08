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
