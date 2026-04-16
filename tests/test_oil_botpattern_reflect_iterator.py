"""Tests for cli/daemon/iterators/oil_botpattern_reflect.py — sub-system 6 L2."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daemon.iterators.oil_botpattern_reflect import (
    OilBotPatternReflectIterator,
    find_proposal,
    load_proposals,
    write_proposals_atomic,
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


def _reflect_cfg(tmp: Path, **overrides) -> dict:
    cfg = {
        "enabled": True,
        "window_days": 7,
        "min_sample_per_rule": 5,
        "min_run_interval_days": 7,
        "main_journal_jsonl":     str(tmp / "journal.jsonl"),
        "decision_journal_jsonl": str(tmp / "oil_botpattern_journal.jsonl"),
        "strategy_config_path":   str(tmp / "oil_botpattern.json"),
        "proposals_jsonl":        str(tmp / "oil_botpattern_proposals.jsonl"),
        "state_json":             str(tmp / "oil_botpattern_reflect_state.json"),
        "audit_jsonl":            str(tmp / "oil_botpattern_tune_audit.jsonl"),
    }
    cfg.update(overrides)
    return cfg


def _write_config(tmp: Path, name: str, cfg: dict) -> Path:
    path = tmp / name
    path.write_text(json.dumps(cfg, indent=2))
    return path


def _losing_cl_trades(n: int) -> list[dict]:
    return [
        {"strategy_id": "oil_botpattern", "status": "closed", "side": "long",
         "instrument": "CL", "realised_pnl_usd": -20, "roe_pct": -1.5,
         "close_reason": "sl_hit", "close_ts": _now_iso(1),
         "trade_id": f"CL{i}"}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

def test_disabled_is_noop(tmp_path):
    cfg = _reflect_cfg(tmp_path, enabled=False)
    cfg_path = _write_config(tmp_path, "oil_botpattern_reflect.json", cfg)
    journal = tmp_path / "journal.jsonl"
    journal.write_text("\n".join(json.dumps(r) for r in _losing_cl_trades(10)))

    it = OilBotPatternReflectIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    assert not (tmp_path / "oil_botpattern_proposals.jsonl").exists()
    assert ctx.alerts == []


# ---------------------------------------------------------------------------
# Cadence: first run fires, second run is throttled
# ---------------------------------------------------------------------------

def test_first_run_fires_when_state_missing(tmp_path):
    cfg_path = _write_config(
        tmp_path, "oil_botpattern_reflect.json", _reflect_cfg(tmp_path),
    )
    journal = tmp_path / "journal.jsonl"
    journal.write_text("\n".join(json.dumps(r) for r in _losing_cl_trades(6)))

    it = OilBotPatternReflectIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    # State written
    state_path = tmp_path / "oil_botpattern_reflect_state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["last_run_at"] is not None

    # Proposal should include instrument_dead for CL
    proposals_path = tmp_path / "oil_botpattern_proposals.jsonl"
    assert proposals_path.exists()
    rows = [json.loads(l) for l in proposals_path.read_text().splitlines() if l]
    assert any(p["type"] == "instrument_dead" for p in rows)

    # Warning alert emitted
    assert any(a.severity == "warning" for a in ctx.alerts)
    assert any("proposal" in a.message.lower() for a in ctx.alerts)


def test_second_run_within_interval_is_noop(tmp_path):
    cfg_path = _write_config(
        tmp_path, "oil_botpattern_reflect.json", _reflect_cfg(tmp_path),
    )
    journal = tmp_path / "journal.jsonl"
    journal.write_text("\n".join(json.dumps(r) for r in _losing_cl_trades(6)))

    it = OilBotPatternReflectIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)  # fires
    first_count = len(load_proposals(str(tmp_path / "oil_botpattern_proposals.jsonl")))

    # Second tick immediately — should be throttled
    ctx2 = _fake_ctx()
    it.tick(ctx2)
    second_count = len(load_proposals(str(tmp_path / "oil_botpattern_proposals.jsonl")))

    assert second_count == first_count
    assert ctx2.alerts == []


def test_run_due_after_interval(tmp_path):
    cfg_path = _write_config(
        tmp_path, "oil_botpattern_reflect.json", _reflect_cfg(tmp_path),
    )
    journal = tmp_path / "journal.jsonl"
    journal.write_text("\n".join(json.dumps(r) for r in _losing_cl_trades(6)))

    # Seed state with last_run 8 days ago — due
    state_path = tmp_path / "oil_botpattern_reflect_state.json"
    old = (datetime.now(tz=UTC) - timedelta(days=8)).isoformat()
    state_path.write_text(json.dumps({"last_run_at": old, "last_proposal_id": 10}))

    it = OilBotPatternReflectIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    proposals = load_proposals(str(tmp_path / "oil_botpattern_proposals.jsonl"))
    assert len(proposals) >= 1
    # IDs should continue from last_proposal_id = 10
    assert min(p["id"] for p in proposals) == 11


# ---------------------------------------------------------------------------
# Empty window — state advances, no proposals
# ---------------------------------------------------------------------------

def test_empty_window_updates_state_no_proposals(tmp_path):
    cfg_path = _write_config(
        tmp_path, "oil_botpattern_reflect.json", _reflect_cfg(tmp_path),
    )
    # Empty journal
    (tmp_path / "journal.jsonl").write_text("")

    it = OilBotPatternReflectIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    # State updated
    state_path = tmp_path / "oil_botpattern_reflect_state.json"
    assert state_path.exists()
    # No proposals file
    assert not (tmp_path / "oil_botpattern_proposals.jsonl").exists()
    # No alert
    assert not any(a.severity == "warning" for a in ctx.alerts)


# ---------------------------------------------------------------------------
# Filtering: non-oil_botpattern trades ignored
# ---------------------------------------------------------------------------

def test_ignores_other_strategies(tmp_path):
    cfg_path = _write_config(
        tmp_path, "oil_botpattern_reflect.json", _reflect_cfg(tmp_path),
    )
    rows = [
        {"strategy_id": "thesis_engine", "status": "closed", "instrument": "CL",
         "realised_pnl_usd": -20, "roe_pct": -1.5, "close_ts": _now_iso(1)}
        for _ in range(10)
    ]
    (tmp_path / "journal.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows)
    )

    it = OilBotPatternReflectIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    # No proposals — those trades were filtered out
    assert not (tmp_path / "oil_botpattern_proposals.jsonl").exists()


# ---------------------------------------------------------------------------
# Helper functions for the Telegram handler
# ---------------------------------------------------------------------------

def test_load_proposals_missing_file_returns_empty(tmp_path):
    result = load_proposals(str(tmp_path / "nope.jsonl"))
    assert result == []


def test_write_proposals_atomic_roundtrip(tmp_path):
    path = tmp_path / "proposals.jsonl"
    rows = [
        {"id": 1, "status": "pending"},
        {"id": 2, "status": "approved"},
    ]
    write_proposals_atomic(str(path), rows)
    loaded = load_proposals(str(path))
    assert loaded == rows


def test_find_proposal_by_id():
    rows = [
        {"id": 1, "status": "pending"},
        {"id": 2, "status": "pending"},
        {"id": 3, "status": "pending"},
    ]
    assert find_proposal(rows, 2)["id"] == 2
    assert find_proposal(rows, 99) is None


def test_find_proposal_tolerates_bad_id():
    rows = [{"id": "oops"}, {"id": 5, "status": "pending"}]
    assert find_proposal(rows, 5)["id"] == 5


# ---------------------------------------------------------------------------
# Bad config tolerance
# ---------------------------------------------------------------------------

def test_missing_config_is_noop(tmp_path):
    it = OilBotPatternReflectIterator(config_path=str(tmp_path / "nope.json"))
    ctx = _fake_ctx()
    it.on_start(ctx)  # should not raise
    it.tick(ctx)


def test_bad_state_file_resets(tmp_path):
    cfg_path = _write_config(
        tmp_path, "oil_botpattern_reflect.json", _reflect_cfg(tmp_path),
    )
    # Corrupt state file
    state_path = tmp_path / "oil_botpattern_reflect_state.json"
    state_path.write_text("{not json")
    (tmp_path / "journal.jsonl").write_text("")

    it = OilBotPatternReflectIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)  # should not raise

    # State is now rewritten as valid JSON
    assert json.loads(state_path.read_text())["last_run_at"] is not None
