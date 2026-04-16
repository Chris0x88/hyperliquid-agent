"""Stop / Liquidity Heatmap — pure logic.

Spec: docs/plans/OIL_BOT_PATTERN_03_LIQUIDITY_HEATMAP.md

Sub-system 3 of the Oil Bot-Pattern Strategy. Read-only.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Zone:
    id: str
    instrument: str
    snapshot_at: datetime
    mid: float
    side: str  # "bid" | "ask"
    price_low: float
    price_high: float
    centroid: float
    distance_bps: float
    notional_usd: float
    level_count: int
    rank: int  # 1 = largest cluster on this side


@dataclass(frozen=True)
class Cascade:
    id: str
    instrument: str
    detected_at: datetime
    window_s: int
    side: str  # "long" | "short" — which side got liquidated
    oi_delta_pct: float
    funding_jump_bps: float
    severity: int  # 1..4
    notes: str


# ---------------------------------------------------------------------------
# JSONL I/O
# ---------------------------------------------------------------------------

def _zone_to_dict(z: Zone) -> dict:
    out = asdict(z)
    out["snapshot_at"] = z.snapshot_at.isoformat()
    return out


def _zone_from_dict(raw: dict) -> Zone:
    return Zone(
        id=raw["id"],
        instrument=raw["instrument"],
        snapshot_at=datetime.fromisoformat(raw["snapshot_at"]),
        mid=float(raw["mid"]),
        side=raw["side"],
        price_low=float(raw["price_low"]),
        price_high=float(raw["price_high"]),
        centroid=float(raw["centroid"]),
        distance_bps=float(raw["distance_bps"]),
        notional_usd=float(raw["notional_usd"]),
        level_count=int(raw["level_count"]),
        rank=int(raw["rank"]),
    )


def _cascade_to_dict(c: Cascade) -> dict:
    out = asdict(c)
    out["detected_at"] = c.detected_at.isoformat()
    return out


def _cascade_from_dict(raw: dict) -> Cascade:
    return Cascade(
        id=raw["id"],
        instrument=raw["instrument"],
        detected_at=datetime.fromisoformat(raw["detected_at"]),
        window_s=int(raw["window_s"]),
        side=raw["side"],
        oi_delta_pct=float(raw["oi_delta_pct"]),
        funding_jump_bps=float(raw["funding_jump_bps"]),
        severity=int(raw["severity"]),
        notes=raw.get("notes", ""),
    )


def append_zone(jsonl_path: str, z: Zone) -> None:
    p = Path(jsonl_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(_zone_to_dict(z)) + "\n")


def append_zones(jsonl_path: str, zones: list[Zone]) -> None:
    p = Path(jsonl_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        for z in zones:
            f.write(json.dumps(_zone_to_dict(z)) + "\n")


def read_zones(jsonl_path: str) -> list[Zone]:
    p = Path(jsonl_path)
    if not p.exists():
        return []
    out: list[Zone] = []
    with p.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(_zone_from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return out


def latest_snapshot(zones: list[Zone], instrument: str) -> list[Zone]:
    """Return only zones from the most recent snapshot for one instrument."""
    rows = [z for z in zones if z.instrument == instrument]
    if not rows:
        return []
    latest_ts = max(z.snapshot_at for z in rows)
    return [z for z in rows if z.snapshot_at == latest_ts]


def append_cascade(jsonl_path: str, c: Cascade) -> None:
    p = Path(jsonl_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(_cascade_to_dict(c)) + "\n")


def read_cascades(jsonl_path: str) -> list[Cascade]:
    p = Path(jsonl_path)
    if not p.exists():
        return []
    out: list[Cascade] = []
    with p.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(_cascade_from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return out


# ---------------------------------------------------------------------------
# Zone clustering — wedge 3
# ---------------------------------------------------------------------------

def cluster_l2_book(
    book: dict,
    instrument: str,
    snapshot_at: datetime,
    cluster_bps: float = 8.0,
    max_distance_bps: float = 200.0,
    max_zones_per_side: int = 5,
    min_notional_usd: float = 50_000.0,
) -> list[Zone]:
    """Cluster a Hyperliquid l2Book snapshot into Zone records.

    `book` is the dict returned by HL info `l2Book`:
        {"levels": [bids, asks], "coin": ..., "time": ...}
    where each side is a list of {"px": "...", "sz": "...", "n": int}.

    Algorithm:
      1. Compute mid from best bid + best ask.
      2. For each side, walk levels outward from mid. Group levels whose
         price is within `cluster_bps` of the cluster's first level into
         the same cluster.
      3. Drop levels beyond `max_distance_bps` from mid.
      4. Compute notional = sum(px * sz) per cluster.
      5. Drop clusters under `min_notional_usd`.
      6. Rank by notional descending, keep top `max_zones_per_side`.
    """
    levels = book.get("levels") or []
    if len(levels) != 2:
        return []
    bids_raw, asks_raw = levels[0], levels[1]
    if not bids_raw or not asks_raw:
        return []

    try:
        best_bid = float(bids_raw[0]["px"])
        best_ask = float(asks_raw[0]["px"])
    except (KeyError, ValueError, TypeError):
        return []

    if best_bid <= 0 or best_ask <= 0 or best_ask <= best_bid:
        return []

    mid = (best_bid + best_ask) / 2.0
    out: list[Zone] = []

    for side, raw in (("bid", bids_raw), ("ask", asks_raw)):
        clusters = _cluster_side(raw, mid, side, cluster_bps, max_distance_bps)
        # Filter under-min, then rank
        kept = [c for c in clusters if c["notional_usd"] >= min_notional_usd]
        kept.sort(key=lambda c: c["notional_usd"], reverse=True)
        kept = kept[:max_zones_per_side]
        for rank, c in enumerate(kept, start=1):
            zid = f"{instrument}_{snapshot_at.isoformat()}_{side[0]}{rank}"
            out.append(Zone(
                id=zid,
                instrument=instrument,
                snapshot_at=snapshot_at,
                mid=mid,
                side=side,
                price_low=c["price_low"],
                price_high=c["price_high"],
                centroid=c["centroid"],
                distance_bps=c["distance_bps"],
                notional_usd=c["notional_usd"],
                level_count=c["level_count"],
                rank=rank,
            ))
    return out


def _cluster_side(
    raw_levels: list[dict],
    mid: float,
    side: str,
    cluster_bps: float,
    max_distance_bps: float,
) -> list[dict]:
    """Walk one side outward from mid, grouping nearby levels into clusters."""
    parsed: list[tuple[float, float]] = []  # (px, sz)
    for lvl in raw_levels:
        try:
            px = float(lvl["px"])
            sz = float(lvl["sz"])
        except (KeyError, ValueError, TypeError):
            continue
        if px <= 0 or sz <= 0:
            continue
        dist_bps = abs(px - mid) / mid * 10_000.0
        if dist_bps > max_distance_bps:
            continue
        parsed.append((px, sz))
    if not parsed:
        return []

    # Walk from best toward worse
    parsed.sort(key=lambda t: t[0], reverse=(side == "bid"))

    clusters: list[dict] = []
    cur: dict | None = None
    for px, sz in parsed:
        if cur is None:
            cur = _new_cluster(px, sz, mid)
            continue
        anchor_bps = abs(px - cur["price_high"]) / mid * 10_000.0
        if anchor_bps <= cluster_bps:
            _extend_cluster(cur, px, sz)
        else:
            _finalize_cluster(cur, mid)
            clusters.append(cur)
            cur = _new_cluster(px, sz, mid)
    if cur is not None:
        _finalize_cluster(cur, mid)
        clusters.append(cur)
    return clusters


def _new_cluster(px: float, sz: float, mid: float) -> dict:
    return {
        "price_low": px,
        "price_high": px,
        "_notional_weighted_px": px * sz,
        "notional_usd": px * sz,
        "level_count": 1,
    }


def _extend_cluster(c: dict, px: float, sz: float) -> None:
    c["price_low"] = min(c["price_low"], px)
    c["price_high"] = max(c["price_high"], px)
    c["_notional_weighted_px"] += px * sz
    c["notional_usd"] += px * sz
    c["level_count"] += 1


def _finalize_cluster(c: dict, mid: float) -> None:
    centroid = (c["price_low"] + c["price_high"]) / 2.0
    c["centroid"] = centroid
    c["distance_bps"] = abs(centroid - mid) / mid * 10_000.0
    c.pop("_notional_weighted_px", None)


# ---------------------------------------------------------------------------
# Cascade detection — wedge 4
# ---------------------------------------------------------------------------

def detect_cascade(
    instrument: str,
    detected_at: datetime,
    prev_oi: float,
    curr_oi: float,
    prev_funding_bps: float,
    curr_funding_bps: float,
    window_s: int,
    oi_threshold_pct: float = 1.5,
    funding_threshold_bps: float = 10.0,
) -> Cascade | None:
    """Detect a liquidation cascade from OI + funding deltas.

    OI dropping with funding spiking up = long cascade (longs liquidated,
    funding rises as short pressure dominates).
    OI dropping with funding spiking down = short cascade.
    """
    if prev_oi <= 0:
        return None

    oi_delta_pct = (curr_oi - prev_oi) / prev_oi * 100.0
    funding_jump = curr_funding_bps - prev_funding_bps

    # Cascade only fires when OI drops materially
    if oi_delta_pct >= -oi_threshold_pct:
        return None
    # And funding moves enough to confirm direction
    if abs(funding_jump) < funding_threshold_bps:
        return None

    side = "long" if funding_jump > 0 else "short"
    severity = _severity(abs(oi_delta_pct))
    notes = (
        f"OI dropped {abs(oi_delta_pct):.1f}% in {window_s}s with funding "
        f"{'spike up' if side == 'long' else 'spike down'} "
        f"({funding_jump:+.1f}bps) — likely {side} cascade"
    )
    return Cascade(
        id=f"{instrument}_{detected_at.isoformat()}",
        instrument=instrument,
        detected_at=detected_at,
        window_s=window_s,
        side=side,
        oi_delta_pct=oi_delta_pct,
        funding_jump_bps=funding_jump,
        severity=severity,
        notes=notes,
    )


def _severity(abs_oi_drop_pct: float) -> int:
    if abs_oi_drop_pct >= 7.0:
        return 4
    if abs_oi_drop_pct >= 4.0:
        return 3
    if abs_oi_drop_pct >= 2.5:
        return 2
    return 1
