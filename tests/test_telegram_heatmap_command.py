"""Tests for the /heatmap Telegram command — sub-system 3."""
import json
from pathlib import Path
from unittest.mock import patch

from cli.telegram_bot import cmd_heatmap


def _write_zones(path: Path, rows: list[dict]) -> None:
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _zone(rank=1, side="bid", ts="2026-04-09T22:00:00+00:00", instrument="BRENTOIL", notional=482_000):
    return {
        "id": f"{instrument}_{ts}_{side[0]}{rank}",
        "instrument": instrument,
        "snapshot_at": ts,
        "mid": 67.42,
        "side": side,
        "price_low": 67.10 if side == "bid" else 67.70,
        "price_high": 67.18 if side == "bid" else 67.78,
        "centroid": 67.14 if side == "bid" else 67.74,
        "distance_bps": 41.0 if side == "bid" else 47.0,
        "notional_usd": float(notional),
        "level_count": 7,
        "rank": rank,
    }


def test_cmd_heatmap_no_data(tmp_path):
    with patch("cli.telegram_bot.HEATMAP_ZONES_JSONL", str(tmp_path / "z.jsonl")):
        with patch("cli.telegram_bot.HEATMAP_CASCADES_JSONL", str(tmp_path / "c.jsonl")):
            with patch("cli.telegram_bot.tg_send") as send:
                cmd_heatmap("tok", "chat", "")
                body = send.call_args[0][2]
                assert "No heatmap data" in body or "still booting" in body


def test_cmd_heatmap_renders_zones(tmp_path):
    z = tmp_path / "z.jsonl"
    _write_zones(z, [
        _zone(rank=1, side="bid", notional=482_000),
        _zone(rank=2, side="bid", notional=300_000),
        _zone(rank=1, side="ask", notional=600_000),
    ])
    with patch("cli.telegram_bot.HEATMAP_ZONES_JSONL", str(z)):
        with patch("cli.telegram_bot.HEATMAP_CASCADES_JSONL", str(tmp_path / "c.jsonl")):
            with patch("cli.telegram_bot.tg_send") as send:
                cmd_heatmap("tok", "chat", "")
                body = send.call_args[0][2]
                assert "BRENTOIL" in body
                assert "Bid walls" in body
                assert "Ask walls" in body
                assert "67.14" in body
                assert "67.74" in body


def test_cmd_heatmap_picks_latest_snapshot(tmp_path):
    z = tmp_path / "z.jsonl"
    _write_zones(z, [
        _zone(rank=1, side="bid", ts="2026-04-09T22:00:00+00:00"),
        _zone(rank=1, side="bid", ts="2026-04-09T22:01:00+00:00", notional=999_999),
    ])
    with patch("cli.telegram_bot.HEATMAP_ZONES_JSONL", str(z)):
        with patch("cli.telegram_bot.HEATMAP_CASCADES_JSONL", str(tmp_path / "c.jsonl")):
            with patch("cli.telegram_bot.tg_send") as send:
                cmd_heatmap("tok", "chat", "")
                body = send.call_args[0][2]
                assert "$1,000K" in body or "1000K" in body or "999K" in body


def test_cmd_heatmap_renders_cascades(tmp_path):
    z = tmp_path / "z.jsonl"
    c = tmp_path / "c.jsonl"
    _write_zones(z, [_zone(rank=1, side="ask")])
    with c.open("w") as f:
        f.write(json.dumps({
            "id": "BRENTOIL_2026-04-09T22:03:11+00:00",
            "instrument": "BRENTOIL",
            "detected_at": "2026-04-09T22:03:11+00:00",
            "window_s": 180,
            "side": "long",
            "oi_delta_pct": -3.4,
            "funding_jump_bps": 18.0,
            "severity": 2,
            "notes": "test",
        }) + "\n")
    with patch("cli.telegram_bot.HEATMAP_ZONES_JSONL", str(z)):
        with patch("cli.telegram_bot.HEATMAP_CASCADES_JSONL", str(c)):
            with patch("cli.telegram_bot.tg_send") as send:
                cmd_heatmap("tok", "chat", "")
                body = send.call_args[0][2]
                assert "Recent cascades" in body
                assert "long sev2" in body


def test_cmd_heatmap_unknown_instrument(tmp_path):
    z = tmp_path / "z.jsonl"
    _write_zones(z, [_zone(rank=1, side="bid")])
    with patch("cli.telegram_bot.HEATMAP_ZONES_JSONL", str(z)):
        with patch("cli.telegram_bot.HEATMAP_CASCADES_JSONL", str(tmp_path / "c.jsonl")):
            with patch("cli.telegram_bot.tg_send") as send:
                cmd_heatmap("tok", "chat", "GOLD")
                body = send.call_args[0][2]
                assert "GOLD" in body
                assert "No zones" in body


def test_cmd_heatmap_registered_in_handlers():
    from cli.telegram_bot import HANDLERS
    assert HANDLERS.get("/heatmap") is cmd_heatmap
    assert HANDLERS.get("heatmap") is cmd_heatmap
