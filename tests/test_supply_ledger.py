from datetime import datetime, timezone
from modules.supply_ledger import Disruption, SupplyState


def test_disruption_dataclass_constructs():
    d = Disruption(
        id="abc123",
        source="news_auto",
        source_ref="cat-001",
        facility_name="Volgograd refinery",
        facility_type="refinery",
        location="Volgograd, Russia",
        region="russia",
        volume_offline=200000.0,
        volume_unit="bpd",
        incident_date=datetime(2026, 4, 8, tzinfo=timezone.utc),
        expected_recovery=None,
        confidence=2,
        status="active",
        instruments=["xyz:BRENTOIL", "CL"],
        notes="drone strike",
        created_at=datetime(2026, 4, 9, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 9, tzinfo=timezone.utc),
    )
    assert d.region == "russia"
    assert d.volume_offline == 200000.0


def test_supply_state_dataclass_constructs():
    s = SupplyState(
        computed_at=datetime(2026, 4, 9, tzinfo=timezone.utc),
        total_offline_bpd=2_400_000.0,
        total_offline_mcfd=180.0,
        by_region={"russia": 1_200_000.0},
        by_facility_type={"refinery": 1_450_000.0},
        active_chokepoints=["hormuz_strait"],
        active_disruption_count=14,
        high_confidence_count=6,
    )
    assert s.total_offline_bpd == 2_400_000.0


from modules.supply_ledger import classify_region


def test_classify_region_russia():
    assert classify_region("Volgograd refinery strike") == "russia"
    assert classify_region("moscow pipeline") == "russia"


def test_classify_region_red_sea():
    assert classify_region("Houthi missile hits tanker in Red Sea") == "red_sea"
    assert classify_region("bab-el-mandeb blockade") == "red_sea"


def test_classify_region_hormuz():
    assert classify_region("Hormuz strait navy seizure") == "hormuz_strait"


def test_classify_region_unknown():
    assert classify_region("unrelated headline") == "unknown"


from modules.supply_ledger import refine_facility_type


def test_refine_facility_type_pipeline_wins():
    assert refine_facility_type("Druzhba pipeline hit by drone", default="refinery") == "pipeline"


def test_refine_facility_type_oilfield_wins():
    assert refine_facility_type("Priobskoye oilfield strike", default="refinery") == "oilfield"


def test_refine_facility_type_terminal_wins():
    assert refine_facility_type("Novorossiysk oil terminal ablaze", default="refinery") == "terminal"


def test_refine_facility_type_fallback():
    assert refine_facility_type("Volgograd refinery fire", default="refinery") == "refinery"


import tempfile
from modules.supply_ledger import load_auto_extract_rules, AutoExtractRule


def test_load_auto_extract_rules_from_yaml():
    yaml_text = """
mappings:
  - catalyst_category: physical_damage_facility
    facility_type: refinery
    confidence: 2
    status: active
  - catalyst_category: shipping_attack
    facility_type: ship
    confidence: 2
    status: active
"""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(yaml_text)
        path = f.name
    rules = load_auto_extract_rules(path)
    assert len(rules) == 2
    assert rules[0].catalyst_category == "physical_damage_facility"
    assert rules[0].facility_type == "refinery"
    assert rules[1].catalyst_category == "shipping_attack"


from modules.supply_ledger import auto_extract_from_catalyst

CATALYST_PHYSICAL = {
    "id": "cat-001",
    "category": "physical_damage_facility",
    "headline_id": "h-001",
    "instruments": ["xyz:BRENTOIL", "CL"],
    "event_date": datetime(2026, 4, 8, 22, 14, tzinfo=timezone.utc),
    "severity": 5,
    "rationale": "rule: physical_damage_facility",
    "_headline_title": "Drone strike hits Volgograd refinery, 200kbpd offline",
}

CATALYST_SHIPPING = {
    "id": "cat-002",
    "category": "shipping_attack",
    "headline_id": "h-002",
    "instruments": ["xyz:BRENTOIL", "CL"],
    "event_date": datetime(2026, 4, 9, 14, 22, tzinfo=timezone.utc),
    "severity": 5,
    "rationale": "rule: shipping_attack",
    "_headline_title": "Houthi missiles strike VLCC in Red Sea, vessel ablaze",
}

CATALYST_CHOKE = {
    "id": "cat-003",
    "category": "chokepoint_blockade",
    "headline_id": "h-003",
    "instruments": ["xyz:BRENTOIL", "CL"],
    "event_date": datetime(2026, 4, 9, tzinfo=timezone.utc),
    "severity": 5,
    "rationale": "rule: chokepoint_blockade",
    "_headline_title": "Hormuz strait closed after Iranian navy seizure",
}


def _rules():
    return load_auto_extract_rules("data/config/supply_auto_extract.yaml")


def test_auto_extract_physical_damage_refinery():
    d = auto_extract_from_catalyst(CATALYST_PHYSICAL, _rules())
    assert d is not None
    assert d.facility_type == "refinery"
    assert d.region == "russia"
    assert d.confidence == 2
    assert d.status == "active"
    assert d.source == "news_auto"
    assert d.source_ref == "cat-001"


def test_auto_extract_shipping_ship():
    d = auto_extract_from_catalyst(CATALYST_SHIPPING, _rules())
    assert d.facility_type == "ship"
    assert d.region == "red_sea"


def test_auto_extract_chokepoint():
    d = auto_extract_from_catalyst(CATALYST_CHOKE, _rules())
    assert d.facility_type == "chokepoint"
    assert d.region == "hormuz_strait"


def test_auto_extract_unknown_category_returns_none():
    unrelated = dict(CATALYST_PHYSICAL, category="eia_weekly")
    assert auto_extract_from_catalyst(unrelated, _rules()) is None


from pathlib import Path
from modules.supply_ledger import append_disruption, read_disruptions, latest_per_id


def _make_disruption(did, status="active", updated=None):
    now = datetime(2026, 4, 9, tzinfo=timezone.utc)
    return Disruption(
        id=did,
        source="news_auto",
        source_ref="cat",
        facility_name="Test",
        facility_type="refinery",
        location="russia",
        region="russia",
        volume_offline=100000.0,
        volume_unit="bpd",
        incident_date=now,
        expected_recovery=None,
        confidence=2,
        status=status,
        instruments=["CL"],
        notes="",
        created_at=now,
        updated_at=updated or now,
    )


def test_append_and_read_roundtrip(tmp_path):
    path = tmp_path / "d.jsonl"
    append_disruption(str(path), _make_disruption("a"))
    append_disruption(str(path), _make_disruption("b"))
    rows = read_disruptions(str(path))
    assert len(rows) == 2
    assert {r.id for r in rows} == {"a", "b"}


def test_latest_per_id_keeps_newest(tmp_path):
    path = tmp_path / "d.jsonl"
    early = _make_disruption("a", status="active", updated=datetime(2026, 4, 9, 10, tzinfo=timezone.utc))
    late = _make_disruption("a", status="restored", updated=datetime(2026, 4, 9, 18, tzinfo=timezone.utc))
    append_disruption(str(path), early)
    append_disruption(str(path), late)
    rows = read_disruptions(str(path))
    latest = latest_per_id(rows)
    assert len(latest) == 1
    assert latest[0].status == "restored"


from modules.supply_ledger import compute_state


def test_compute_state_empty():
    state = compute_state([])
    assert state.total_offline_bpd == 0.0
    assert state.active_disruption_count == 0
    assert state.active_chokepoints == []


def test_compute_state_sums_active_only():
    now = datetime(2026, 4, 9, tzinfo=timezone.utc)
    rows = [
        _make_disruption("a", status="active", updated=now),
        _make_disruption("b", status="restored", updated=now),
    ]
    state = compute_state(rows)
    assert state.total_offline_bpd == 100000.0
    assert state.active_disruption_count == 1


def test_compute_state_partial_halves_volume():
    now = datetime(2026, 4, 9, tzinfo=timezone.utc)
    rows = [_make_disruption("a", status="partial", updated=now)]
    state = compute_state(rows)
    assert state.total_offline_bpd == 50000.0


def test_compute_state_active_chokepoints():
    now = datetime(2026, 4, 9, tzinfo=timezone.utc)
    choke = Disruption(
        id="c1", source="manual", source_ref="user",
        facility_name="Hormuz Strait closure", facility_type="chokepoint",
        location="hormuz_strait", region="hormuz_strait",
        volume_offline=None, volume_unit=None,
        incident_date=now, expected_recovery=None,
        confidence=4, status="active",
        instruments=["CL", "xyz:BRENTOIL"], notes="",
        created_at=now, updated_at=now,
    )
    state = compute_state([choke])
    assert state.active_chokepoints == ["hormuz_strait"]


def test_compute_state_latest_per_id_semantics():
    early = _make_disruption("a", status="active", updated=datetime(2026, 4, 9, 10, tzinfo=timezone.utc))
    late = _make_disruption("a", status="restored", updated=datetime(2026, 4, 9, 18, tzinfo=timezone.utc))
    state = compute_state([early, late])
    assert state.active_disruption_count == 0
