"""Tests for cli/daemon/iterators/oil_botpattern_patternlib.py — sub-system 6 L3."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cli.daemon.iterators.oil_botpattern_patternlib import (
    OilBotPatternPatternLibIterator,
    apply_promote,
    apply_reject,
    find_candidate,
    load_candidates,
    load_catalog,
    write_candidates_atomic,
    write_catalog_atomic,
)


UTC = timezone.utc


@dataclass
class FakeAlert:
    severity: str
    source: str
    message: str
    data: dict


@dataclass
class FakeCtx:
    alerts: list = field(default_factory=list)


def _fake_ctx() -> FakeCtx:
    return FakeCtx()


def _now_iso(days_ago: float = 0.0) -> str:
    return (datetime.now(tz=UTC) - timedelta(days=days_ago)).isoformat()


def _cfg(tmp: Path, **overrides) -> dict:
    cfg = {
        "enabled": True,
        "tick_interval_s": 0,
        "min_occurrences": 3,
        "confidence_band_precision": 0.1,
        "window_days": 30,
        "bot_patterns_jsonl":  str(tmp / "bot_patterns.jsonl"),
        "catalog_json":        str(tmp / "bot_pattern_catalog.json"),
        "candidates_jsonl":    str(tmp / "bot_pattern_candidates.jsonl"),
        "state_json":          str(tmp / "patternlib_state.json"),
    }
    cfg.update(overrides)
    return cfg


def _write_config(tmp: Path, name: str, cfg: dict) -> Path:
    path = tmp / name
    path.write_text(json.dumps(cfg, indent=2))
    return path


def _pattern_row(**overrides) -> dict:
    base = {
        "id": "r1",
        "instrument": "BRENTOIL",
        "detected_at": _now_iso(1),
        "classification": "bot_driven_overextension",
        "direction": "down",
        "confidence": 0.72,
        "signals": ["overextended_move", "oi_divergence"],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

def test_disabled_is_noop(tmp_path):
    cfg_path = _write_config(tmp_path, "cfg.json", _cfg(tmp_path, enabled=False))
    (tmp_path / "bot_patterns.jsonl").write_text(
        "\n".join(json.dumps(_pattern_row()) for _ in range(5))
    )
    it = OilBotPatternPatternLibIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)
    assert not (tmp_path / "bot_pattern_candidates.jsonl").exists()
    assert ctx.alerts == []


def test_missing_config_is_noop(tmp_path):
    it = OilBotPatternPatternLibIterator(config_path=str(tmp_path / "nope.json"))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)  # should not raise


def test_missing_bot_patterns_is_noop(tmp_path):
    cfg_path = _write_config(tmp_path, "cfg.json", _cfg(tmp_path))
    it = OilBotPatternPatternLibIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)
    assert not (tmp_path / "bot_pattern_candidates.jsonl").exists()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_emits_candidate_on_enough_occurrences(tmp_path):
    cfg_path = _write_config(tmp_path, "cfg.json", _cfg(tmp_path))
    (tmp_path / "bot_patterns.jsonl").write_text(
        "\n".join(json.dumps(_pattern_row()) for _ in range(3))
    )

    it = OilBotPatternPatternLibIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    candidates = load_candidates(str(tmp_path / "bot_pattern_candidates.jsonl"))
    assert len(candidates) == 1
    assert candidates[0]["occurrences"] == 3
    assert candidates[0]["status"] == "pending"

    # Alert emitted
    assert any("pattern candidate" in a.message for a in ctx.alerts)

    # State updated
    state = json.loads((tmp_path / "patternlib_state.json").read_text())
    assert state["last_candidate_id"] == candidates[0]["id"]


def test_skips_existing_candidate_key(tmp_path):
    cfg_path = _write_config(tmp_path, "cfg.json", _cfg(tmp_path))
    # Pre-seed candidates with the same signature
    from modules.oil_botpattern_patternlib import compute_signature
    sig = compute_signature(_pattern_row(), precision=0.1)
    pre = [{
        "id": 1, "status": "pending", "signature_key": sig.as_key(),
        "classification": "x", "direction": "down", "confidence_band": 0.7,
        "signals": [], "occurrences": 3,
        "first_seen_at": "", "last_seen_at": "",
        "example_instruments": [],
    }]
    (tmp_path / "bot_pattern_candidates.jsonl").write_text(
        "\n".join(json.dumps(c) for c in pre)
    )
    # Seed state so next_id doesn't collide
    (tmp_path / "patternlib_state.json").write_text(
        json.dumps({"last_candidate_id": 1, "last_run_at": None})
    )
    (tmp_path / "bot_patterns.jsonl").write_text(
        "\n".join(json.dumps(_pattern_row()) for _ in range(5))
    )

    it = OilBotPatternPatternLibIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    # Candidates file should still have just 1
    candidates = load_candidates(str(tmp_path / "bot_pattern_candidates.jsonl"))
    assert len(candidates) == 1


def test_skips_catalog_entries(tmp_path):
    cfg_path = _write_config(tmp_path, "cfg.json", _cfg(tmp_path))
    from modules.oil_botpattern_patternlib import compute_signature
    sig = compute_signature(_pattern_row(), precision=0.1)
    (tmp_path / "bot_pattern_catalog.json").write_text(
        json.dumps({sig.as_key(): {"classification": "x"}})
    )
    (tmp_path / "bot_patterns.jsonl").write_text(
        "\n".join(json.dumps(_pattern_row()) for _ in range(5))
    )

    it = OilBotPatternPatternLibIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    assert not (tmp_path / "bot_pattern_candidates.jsonl").exists()


def test_monotonic_ids_across_ticks(tmp_path):
    cfg_path = _write_config(tmp_path, "cfg.json", _cfg(tmp_path))
    (tmp_path / "bot_patterns.jsonl").write_text(
        "".join(json.dumps(_pattern_row(signals=["a"])) + "\n" for _ in range(3))
    )

    it = OilBotPatternPatternLibIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)
    ids_first = [c["id"] for c in load_candidates(str(tmp_path / "bot_pattern_candidates.jsonl"))]

    # Second tick: add rows with a DIFFERENT signature
    with (tmp_path / "bot_patterns.jsonl").open("a") as f:
        for _ in range(3):
            f.write(json.dumps(_pattern_row(signals=["b"])) + "\n")

    it._last_poll_mono = 0.0  # reset throttle
    ctx2 = _fake_ctx()
    it.tick(ctx2)
    ids_all = [c["id"] for c in load_candidates(str(tmp_path / "bot_pattern_candidates.jsonl"))]
    assert len(ids_all) == 2
    assert ids_all[1] > ids_first[-1]


# ---------------------------------------------------------------------------
# Promote + reject helpers
# ---------------------------------------------------------------------------

def test_apply_promote_adds_to_catalog(tmp_path):
    catalog_path = str(tmp_path / "catalog.json")
    cand_path = str(tmp_path / "candidates.jsonl")
    write_candidates_atomic(cand_path, [{
        "id": 42, "status": "pending",
        "signature_key": "sig1", "classification": "test", "direction": "up",
        "confidence_band": 0.7, "signals": ["a"], "occurrences": 5,
        "first_seen_at": "2026-04-01", "last_seen_at": "2026-04-08",
        "example_instruments": ["BRENTOIL"],
    }])

    ok, msg = apply_promote(catalog_path, cand_path, 42, "2026-04-09T10:00:00+00:00")
    assert ok is True

    catalog = load_catalog(catalog_path)
    assert "sig1" in catalog
    assert catalog["sig1"]["classification"] == "test"
    assert catalog["sig1"]["promoted_at"] == "2026-04-09T10:00:00+00:00"

    candidates = load_candidates(cand_path)
    assert candidates[0]["status"] == "promoted"
    assert candidates[0]["reviewed_at"] == "2026-04-09T10:00:00+00:00"


def test_apply_promote_not_found(tmp_path):
    catalog_path = str(tmp_path / "catalog.json")
    cand_path = str(tmp_path / "candidates.jsonl")
    ok, msg = apply_promote(catalog_path, cand_path, 99, "now")
    assert ok is False
    assert "not found" in msg


def test_apply_promote_non_pending_rejected(tmp_path):
    catalog_path = str(tmp_path / "catalog.json")
    cand_path = str(tmp_path / "candidates.jsonl")
    write_candidates_atomic(cand_path, [{
        "id": 1, "status": "rejected",
        "signature_key": "sig1",
    }])
    ok, msg = apply_promote(catalog_path, cand_path, 1, "now")
    assert ok is False
    assert "not pending" in msg


def test_apply_reject_does_not_touch_catalog(tmp_path):
    catalog_path = str(tmp_path / "catalog.json")
    cand_path = str(tmp_path / "candidates.jsonl")
    write_candidates_atomic(cand_path, [{
        "id": 5, "status": "pending", "signature_key": "sig1",
    }])

    ok, msg = apply_reject(cand_path, 5, "2026-04-09T10:00:00+00:00")
    assert ok is True

    # Catalog file never created
    assert not Path(catalog_path).exists()

    candidates = load_candidates(cand_path)
    assert candidates[0]["status"] == "rejected"
    assert candidates[0]["reviewed_at"] == "2026-04-09T10:00:00+00:00"


def test_find_candidate_by_id():
    candidates = [{"id": 1}, {"id": 2}, {"id": 3}]
    assert find_candidate(candidates, 2)["id"] == 2
    assert find_candidate(candidates, 99) is None
