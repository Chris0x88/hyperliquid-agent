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
