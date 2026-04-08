import json
import time
from pathlib import Path
from unittest.mock import MagicMock

from cli.daemon.iterators.supply_ledger import SupplyLedgerIterator


def _write_config(d, enabled=True):
    p = Path(d) / "supply_ledger.json"
    p.write_text(json.dumps({
        "enabled": enabled,
        "auto_extract": True,
        "recompute_interval_s": 300,
        "disruptions_jsonl": f"{d}/disruptions.jsonl",
        "state_json": f"{d}/state.json",
        "auto_extract_rules": "data/config/supply_auto_extract.yaml",
        "catalysts_jsonl": f"{d}/catalysts.jsonl",
    }))
    return p


def test_iterator_has_name():
    assert SupplyLedgerIterator().name == "supply_ledger"


def test_kill_switch_enabled_false_noop(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=False)
    it = SupplyLedgerIterator(config_path=str(cfg))
    ctx = MagicMock()
    ctx.alerts = []
    it.on_start(ctx)
    it.tick(ctx)
    assert not Path(f"{tmp_path}/disruptions.jsonl").exists()
    assert not Path(f"{tmp_path}/state.json").exists()


def _write_catalysts_jsonl(d, cats):
    p = Path(d) / "catalysts.jsonl"
    with p.open("w") as f:
        for c in cats:
            f.write(json.dumps(c, default=str) + "\n")
    return p


def _physical_catalyst(cat_id="cat-001"):
    return {
        "id": cat_id,
        "headline_id": f"h-{cat_id}",
        "instruments": ["xyz:BRENTOIL", "CL"],
        "event_date": "2026-04-08T22:14:00+00:00",
        "category": "physical_damage_facility",
        "severity": 5,
        "expected_direction": "bull",
        "rationale": "rule: physical_damage_facility",
        "created_at": "2026-04-09T00:00:00+00:00",
        "_headline_title": "Drone strike hits Volgograd refinery, 200kbpd offline",
    }


def test_iterator_auto_extracts_new_catalyst(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_catalysts_jsonl(str(tmp_path), [_physical_catalyst()])

    it = SupplyLedgerIterator(config_path=str(cfg))
    ctx = MagicMock()
    ctx.alerts = []
    it.on_start(ctx)
    it.tick(ctx)

    disruptions_path = Path(f"{tmp_path}/disruptions.jsonl")
    assert disruptions_path.exists()
    lines = disruptions_path.read_text().strip().split("\n")
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["facility_type"] == "refinery"
    assert row["region"] == "russia"
    assert row["source"] == "news_auto"

    state_path = Path(f"{tmp_path}/state.json")
    assert state_path.exists()

    assert any(a.severity == "info" for a in ctx.alerts)


def test_iterator_dedupes_same_catalyst(tmp_path):
    cfg = _write_config(str(tmp_path))
    _write_catalysts_jsonl(str(tmp_path), [_physical_catalyst()])

    it = SupplyLedgerIterator(config_path=str(cfg))
    ctx = MagicMock()
    ctx.alerts = []
    it.on_start(ctx)
    it.tick(ctx)
    it.tick(ctx)

    disruptions_path = Path(f"{tmp_path}/disruptions.jsonl")
    lines = disruptions_path.read_text().strip().split("\n")
    assert len(lines) == 1
