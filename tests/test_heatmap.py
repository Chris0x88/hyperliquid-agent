"""Tests for modules/heatmap.py — sub-system 3 pure logic."""
from datetime import datetime, timezone
from pathlib import Path

from modules.heatmap import (
    Cascade,
    Zone,
    append_cascade,
    append_zone,
    append_zones,
    cluster_l2_book,
    detect_cascade,
    latest_snapshot,
    read_cascades,
    read_zones,
)


# ---------------------------------------------------------------------------
# Dataclass + JSONL round-trip
# ---------------------------------------------------------------------------

def _zone(rank=1, instrument="BRENTOIL", ts=None):
    return Zone(
        id=f"{instrument}_z{rank}",
        instrument=instrument,
        snapshot_at=ts or datetime(2026, 4, 9, 22, 0, tzinfo=timezone.utc),
        mid=67.42,
        side="bid",
        price_low=67.10,
        price_high=67.18,
        centroid=67.14,
        distance_bps=41.0,
        notional_usd=482_000.0,
        level_count=7,
        rank=rank,
    )


def _cascade():
    return Cascade(
        id="BRENTOIL_2026-04-09T22:03:11+00:00",
        instrument="BRENTOIL",
        detected_at=datetime(2026, 4, 9, 22, 3, 11, tzinfo=timezone.utc),
        window_s=180,
        side="long",
        oi_delta_pct=-3.4,
        funding_jump_bps=18.0,
        severity=2,
        notes="OI dropped 3.4% in 180s — likely long cascade",
    )


def test_zone_dataclass_constructs():
    z = _zone()
    assert z.instrument == "BRENTOIL"
    assert z.notional_usd == 482_000.0
    assert z.rank == 1


def test_cascade_dataclass_constructs():
    c = _cascade()
    assert c.side == "long"
    assert c.severity == 2


def test_zone_jsonl_round_trip(tmp_path: Path):
    p = tmp_path / "zones.jsonl"
    z1 = _zone(rank=1)
    z2 = _zone(rank=2)
    append_zone(str(p), z1)
    append_zone(str(p), z2)
    rows = read_zones(str(p))
    assert len(rows) == 2
    assert rows[0].rank == 1
    assert rows[1].rank == 2
    assert rows[0].snapshot_at == z1.snapshot_at


def test_append_zones_batch(tmp_path: Path):
    p = tmp_path / "zones.jsonl"
    append_zones(str(p), [_zone(rank=1), _zone(rank=2), _zone(rank=3)])
    assert len(read_zones(str(p))) == 3


def test_cascade_jsonl_round_trip(tmp_path: Path):
    p = tmp_path / "cascades.jsonl"
    c = _cascade()
    append_cascade(str(p), c)
    rows = read_cascades(str(p))
    assert len(rows) == 1
    assert rows[0].id == c.id
    assert rows[0].oi_delta_pct == -3.4


def test_read_missing_file_returns_empty(tmp_path: Path):
    assert read_zones(str(tmp_path / "nope.jsonl")) == []
    assert read_cascades(str(tmp_path / "nope.jsonl")) == []


def test_latest_snapshot_picks_most_recent(tmp_path: Path):
    t1 = datetime(2026, 4, 9, 22, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 4, 9, 22, 1, tzinfo=timezone.utc)
    rows = [_zone(rank=1, ts=t1), _zone(rank=2, ts=t1), _zone(rank=1, ts=t2)]
    latest = latest_snapshot(rows, "BRENTOIL")
    assert len(latest) == 1
    assert latest[0].snapshot_at == t2


# ---------------------------------------------------------------------------
# cluster_l2_book — wedge 3
# ---------------------------------------------------------------------------

def _book(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> dict:
    return {
        "levels": [
            [{"px": str(p), "sz": str(s), "n": 1} for p, s in bids],
            [{"px": str(p), "sz": str(s), "n": 1} for p, s in asks],
        ],
        "coin": "xyz:BRENTOIL",
        "time": 0,
    }


def test_cluster_empty_book_returns_empty():
    assert cluster_l2_book({}, "BRENTOIL", datetime.now(tz=timezone.utc)) == []
    assert cluster_l2_book({"levels": [[], []]}, "BRENTOIL", datetime.now(tz=timezone.utc)) == []


def test_cluster_one_sided_book_returns_empty():
    book = _book([(67.0, 1000)], [])
    assert cluster_l2_book(book, "BRENTOIL", datetime.now(tz=timezone.utc)) == []


def test_cluster_basic_clustering():
    # Two clusters per side: tight wall near mid, second wall further out.
    bids = [(67.40, 100), (67.39, 100), (67.38, 100),  # cluster 1 ~$20K
            (67.20, 5000), (67.19, 4000)]              # cluster 2 ~$615K
    asks = [(67.50, 100), (67.51, 100),                # cluster 1 ~$13K
            (67.80, 6000), (67.81, 6000)]              # cluster 2 ~$813K
    book = _book(bids, asks)
    snapshot = datetime(2026, 4, 9, 22, 0, tzinfo=timezone.utc)
    zones = cluster_l2_book(
        book, "BRENTOIL", snapshot,
        cluster_bps=8.0, max_distance_bps=200.0,
        max_zones_per_side=5, min_notional_usd=50_000.0,
    )
    assert len(zones) > 0
    bids_out = [z for z in zones if z.side == "bid"]
    asks_out = [z for z in zones if z.side == "ask"]
    # Both sides have only one cluster passing the $50K floor
    assert len(bids_out) == 1
    assert len(asks_out) == 1
    # Rank 1 on each side is the survivor
    assert bids_out[0].rank == 1
    assert asks_out[0].rank == 1
    # Distances are positive
    assert bids_out[0].distance_bps > 0
    assert asks_out[0].distance_bps > 0
    # IDs encode side
    assert bids_out[0].id.endswith("_b1")
    assert asks_out[0].id.endswith("_a1")


def test_cluster_drops_far_levels():
    bids = [(67.40, 1000), (50.00, 100_000)]  # second is way beyond max_distance
    asks = [(67.50, 1000)]
    book = _book(bids, asks)
    zones = cluster_l2_book(
        book, "BRENTOIL", datetime.now(tz=timezone.utc),
        max_distance_bps=200.0, min_notional_usd=10_000,
    )
    bids_out = [z for z in zones if z.side == "bid"]
    # Only the close cluster qualifies
    assert len(bids_out) == 1
    assert bids_out[0].centroid > 67.0


def test_cluster_respects_max_zones_per_side():
    bids = []
    px = 67.40
    # 10 separated clusters, each big enough to pass $50K floor
    for i in range(10):
        bids.append((px, 5000))
        px -= 0.20  # well outside cluster_bps
    asks = [(67.50, 1000)]
    book = _book(bids, asks)
    zones = cluster_l2_book(
        book, "BRENTOIL", datetime.now(tz=timezone.utc),
        cluster_bps=2.0, max_distance_bps=10_000, max_zones_per_side=3,
        min_notional_usd=50_000,
    )
    bids_out = [z for z in zones if z.side == "bid"]
    assert len(bids_out) == 3
    # Ranks are 1..3
    assert sorted(z.rank for z in bids_out) == [1, 2, 3]


# ---------------------------------------------------------------------------
# detect_cascade — wedge 4
# ---------------------------------------------------------------------------

def _now():
    return datetime(2026, 4, 9, 22, 0, tzinfo=timezone.utc)


def test_cascade_long_liquidation():
    c = detect_cascade(
        instrument="BRENTOIL", detected_at=_now(),
        prev_oi=10_000_000, curr_oi=9_660_000,  # -3.4%
        prev_funding_bps=5.0, curr_funding_bps=23.0,  # +18 bps
        window_s=180, oi_threshold_pct=1.5, funding_threshold_bps=10.0,
    )
    assert c is not None
    assert c.side == "long"
    assert c.severity == 2
    assert c.oi_delta_pct < 0


def test_cascade_short_liquidation():
    c = detect_cascade(
        instrument="BRENTOIL", detected_at=_now(),
        prev_oi=10_000_000, curr_oi=9_500_000,  # -5%
        prev_funding_bps=20.0, curr_funding_bps=0.0,  # -20 bps
        window_s=180,
    )
    assert c is not None
    assert c.side == "short"
    assert c.severity == 3


def test_cascade_below_oi_threshold_returns_none():
    c = detect_cascade(
        instrument="BRENTOIL", detected_at=_now(),
        prev_oi=10_000_000, curr_oi=9_950_000,  # -0.5%, below 1.5%
        prev_funding_bps=5.0, curr_funding_bps=20.0,
        window_s=180,
    )
    assert c is None


def test_cascade_below_funding_threshold_returns_none():
    c = detect_cascade(
        instrument="BRENTOIL", detected_at=_now(),
        prev_oi=10_000_000, curr_oi=9_000_000,  # -10%
        prev_funding_bps=5.0, curr_funding_bps=8.0,  # only +3 bps
        window_s=180,
    )
    assert c is None


def test_cascade_zero_prev_oi_returns_none():
    c = detect_cascade(
        instrument="BRENTOIL", detected_at=_now(),
        prev_oi=0, curr_oi=1_000_000,
        prev_funding_bps=0, curr_funding_bps=20,
        window_s=180,
    )
    assert c is None


def test_cascade_severity_boundaries():
    # 7% drop = severity 4
    c4 = detect_cascade(
        "BRENTOIL", _now(), 10_000_000, 9_300_000,
        0, 20, 60,
    )
    assert c4 is not None and c4.severity == 4
    # 4% drop = severity 3
    c3 = detect_cascade(
        "BRENTOIL", _now(), 10_000_000, 9_600_000,
        0, 20, 60,
    )
    assert c3 is not None and c3.severity == 3
    # 1.6% drop = severity 1
    c1 = detect_cascade(
        "BRENTOIL", _now(), 10_000_000, 9_840_000,
        0, 20, 60,
    )
    assert c1 is not None and c1.severity == 1
