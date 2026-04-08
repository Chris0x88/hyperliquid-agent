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
