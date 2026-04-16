"""Tests for HeatmapIterator — sub-system 3 wiring layer."""
import json
from pathlib import Path
from unittest.mock import MagicMock

from cli.daemon.iterators.heatmap import HeatmapIterator
from engines.data.heatmap import read_cascades, read_zones


def _write_config(d, enabled=True, **overrides):
    cfg = {
        "enabled": enabled,
        "instruments": ["BRENTOIL"],
        "poll_interval_s": 0,  # tests fire on every tick
        "cluster_bps": 8,
        "max_distance_bps": 200,
        "max_zones_per_side": 5,
        "min_zone_notional_usd": 10_000,
        "cascade_window_s": 180,
        "cascade_oi_delta_pct": 1.5,
        "cascade_funding_jump_bps": 10,
        "zones_jsonl": f"{d}/zones.jsonl",
        "cascades_jsonl": f"{d}/cascades.jsonl",
    }
    cfg.update(overrides)
    p = Path(d) / "heatmap.json"
    p.write_text(json.dumps(cfg))
    return p


def _l2book(bid_px=67.40, ask_px=67.50, sz=5000):
    return {
        "levels": [
            [{"px": str(bid_px), "sz": str(sz), "n": 1},
             {"px": str(bid_px - 0.01), "sz": str(sz), "n": 1}],
            [{"px": str(ask_px), "sz": str(sz), "n": 1},
             {"px": str(ask_px + 0.01), "sz": str(sz), "n": 1}],
        ],
        "coin": "xyz:BRENTOIL",
        "time": 0,
    }


def _meta_ctxs(oi=10_000_000, funding=0.0005):
    return [
        {"universe": [{"name": "xyz:BRENTOIL"}]},
        [{"openInterest": str(oi), "funding": str(funding)}],
    ]


def _ctx():
    c = MagicMock()
    c.alerts = []
    return c


def test_iterator_has_name():
    assert HeatmapIterator().name == "heatmap"


def test_kill_switch_disables_iterator(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=False)
    calls = []

    def fake_post(payload):
        calls.append(payload)
        return {}

    it = HeatmapIterator(config_path=str(cfg), http_post=fake_post)
    it.on_start(_ctx())
    it.tick(_ctx())
    assert calls == []
    assert not Path(f"{tmp_path}/zones.jsonl").exists()


def test_tick_writes_zones(tmp_path):
    cfg = _write_config(str(tmp_path))

    def fake_post(payload):
        if payload.get("type") == "l2Book":
            return _l2book()
        if payload.get("type") == "metaAndAssetCtxs":
            return _meta_ctxs()
        return {}

    it = HeatmapIterator(config_path=str(cfg), http_post=fake_post)
    it.on_start(_ctx())
    it.tick(_ctx())

    zones = read_zones(f"{tmp_path}/zones.jsonl")
    assert len(zones) > 0
    assert all(z.instrument == "BRENTOIL" for z in zones)
    assert any(z.side == "bid" for z in zones)
    assert any(z.side == "ask" for z in zones)


def test_first_tick_no_cascade_seeds_state(tmp_path):
    cfg = _write_config(str(tmp_path))

    def fake_post(payload):
        if payload.get("type") == "l2Book":
            return _l2book()
        if payload.get("type") == "metaAndAssetCtxs":
            return _meta_ctxs(oi=10_000_000, funding=0.0005)
        return {}

    it = HeatmapIterator(config_path=str(cfg), http_post=fake_post)
    it.on_start(_ctx())
    it.tick(_ctx())
    # No cascades yet — first tick is just baseline
    assert read_cascades(f"{tmp_path}/cascades.jsonl") == []


def test_second_tick_detects_cascade(tmp_path):
    cfg = _write_config(str(tmp_path))

    state = {"oi": 10_000_000, "funding": 0.0005}

    def fake_post(payload):
        if payload.get("type") == "l2Book":
            return _l2book()
        if payload.get("type") == "metaAndAssetCtxs":
            return [
                {"universe": [{"name": "xyz:BRENTOIL"}]},
                [{"openInterest": str(state["oi"]), "funding": str(state["funding"])}],
            ]
        return {}

    it = HeatmapIterator(config_path=str(cfg), http_post=fake_post)
    ctx = _ctx()
    it.on_start(ctx)
    it.tick(ctx)  # baseline
    # Now: 5% OI drop with funding spike
    state["oi"] = 9_500_000
    state["funding"] = 0.0025  # +20bps from 5bps
    it.tick(ctx)
    cascades = read_cascades(f"{tmp_path}/cascades.jsonl")
    assert len(cascades) == 1
    assert cascades[0].side == "long"
    assert cascades[0].severity >= 3
    # High-severity cascade emits an alert
    assert any("LIQUIDATION CASCADE" in a.message for a in ctx.alerts)


def test_no_cascade_below_threshold(tmp_path):
    cfg = _write_config(str(tmp_path))
    state = {"oi": 10_000_000, "funding": 0.0005}

    def fake_post(payload):
        if payload.get("type") == "l2Book":
            return _l2book()
        if payload.get("type") == "metaAndAssetCtxs":
            return [
                {"universe": [{"name": "xyz:BRENTOIL"}]},
                [{"openInterest": str(state["oi"]), "funding": str(state["funding"])}],
            ]
        return {}

    it = HeatmapIterator(config_path=str(cfg), http_post=fake_post)
    ctx = _ctx()
    it.on_start(ctx)
    it.tick(ctx)
    state["oi"] = 9_950_000  # -0.5% only
    it.tick(ctx)
    assert read_cascades(f"{tmp_path}/cascades.jsonl") == []


def test_empty_l2book_does_not_crash(tmp_path):
    cfg = _write_config(str(tmp_path))

    def fake_post(payload):
        return {}

    it = HeatmapIterator(config_path=str(cfg), http_post=fake_post)
    it.on_start(_ctx())
    it.tick(_ctx())  # must not raise
    assert not Path(f"{tmp_path}/zones.jsonl").exists() or read_zones(f"{tmp_path}/zones.jsonl") == []


def test_iterator_registered_in_all_tiers():
    from cli.daemon.tiers import iterators_for_tier
    for tier in ("watch", "rebalance", "opportunistic"):
        assert "heatmap" in iterators_for_tier(tier)
