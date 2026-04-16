"""Tests for cli/daemon/iterators/oil_botpattern_shadow.py — sub-system 6 L4."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daemon.iterators.oil_botpattern_shadow import (
    OilBotPatternShadowIterator,
    find_shadow_eval,
    load_shadow_evals,
)


UTC = timezone.utc


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
        "window_days": 30,
        "min_sample": 3,
        "proposals_jsonl":        str(tmp / "proposals.jsonl"),
        "strategy_config_path":   str(tmp / "oil_botpattern.json"),
        "main_journal_jsonl":     str(tmp / "journal.jsonl"),
        "decision_journal_jsonl": str(tmp / "oil_botpattern_journal.jsonl"),
        "shadow_evals_jsonl":     str(tmp / "shadow_evals.jsonl"),
        "state_json":             str(tmp / "shadow_state.json"),
    }
    cfg.update(overrides)
    return cfg


def _write_config(tmp: Path, name: str, cfg: dict) -> Path:
    path = tmp / name
    path.write_text(json.dumps(cfg, indent=2))
    return path


def _approved_proposal(pid: int = 42) -> dict:
    return {
        "id": pid, "type": "gate_overblock", "status": "approved",
        "description": "raise long_min_edge",
        "created_at": _now_iso(5),
        "reviewed_at": _now_iso(1),
        "reviewed_outcome": "applied",
        "proposed_action": {
            "kind": "config_change",
            "target": "data/config/oil_botpattern.json",
            "path": "long_min_edge",
            "old_value": 0.50,
            "new_value": 0.45,
        },
    }


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

def test_disabled_is_noop(tmp_path):
    cfg_path = _write_config(tmp_path, "cfg.json", _cfg(tmp_path, enabled=False))
    (tmp_path / "proposals.jsonl").write_text(
        json.dumps(_approved_proposal()) + "\n"
    )
    it = OilBotPatternShadowIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)
    # proposals file unchanged (no shadow_eval added)
    p = json.loads((tmp_path / "proposals.jsonl").read_text().strip())
    assert "shadow_eval" not in p
    assert not (tmp_path / "shadow_evals.jsonl").exists()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_evaluates_approved_proposals_and_writes_eval(tmp_path):
    cfg_path = _write_config(tmp_path, "cfg.json", _cfg(tmp_path))
    (tmp_path / "proposals.jsonl").write_text(
        json.dumps(_approved_proposal()) + "\n"
    )
    decisions = [
        {"direction": "long", "edge": 0.47, "decided_at": _now_iso(2)},
        {"direction": "long", "edge": 0.48, "decided_at": _now_iso(3)},
        {"direction": "long", "edge": 0.55, "decided_at": _now_iso(4)},
        {"direction": "long", "edge": 0.60, "decided_at": _now_iso(5)},
    ]
    (tmp_path / "oil_botpattern_journal.jsonl").write_text(
        "".join(json.dumps(d) + "\n" for d in decisions)
    )
    trades = [
        {"strategy_id": "oil_botpattern", "status": "closed",
         "close_ts": _now_iso(1), "realised_pnl_usd": 50}
        for _ in range(3)
    ]
    (tmp_path / "journal.jsonl").write_text(
        "".join(json.dumps(t) + "\n" for t in trades)
    )

    it = OilBotPatternShadowIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    # Proposal updated with shadow_eval
    proposals = [
        json.loads(line)
        for line in (tmp_path / "proposals.jsonl").read_text().splitlines()
        if line
    ]
    assert len(proposals) == 1
    assert "shadow_eval" in proposals[0]
    assert proposals[0]["shadow_eval"]["status"] == "evaluated"
    assert proposals[0]["shadow_eval"]["sample_sufficient"] is True

    # Eval log has one record
    evals = load_shadow_evals(str(tmp_path / "shadow_evals.jsonl"))
    assert len(evals) == 1
    assert evals[0]["proposal_id"] == 42

    # Alert emitted
    assert any("counterfactual eval" in a.message for a in ctx.alerts)


def test_skips_already_evaluated_proposals(tmp_path):
    cfg_path = _write_config(tmp_path, "cfg.json", _cfg(tmp_path))
    proposal = _approved_proposal()
    proposal["shadow_eval"] = {"status": "evaluated"}
    (tmp_path / "proposals.jsonl").write_text(
        json.dumps(proposal) + "\n"
    )

    it = OilBotPatternShadowIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    # No new eval written
    assert not (tmp_path / "shadow_evals.jsonl").exists()
    assert ctx.alerts == []


def test_skips_non_approved_proposals(tmp_path):
    cfg_path = _write_config(tmp_path, "cfg.json", _cfg(tmp_path))
    proposal = _approved_proposal()
    proposal["status"] = "pending"
    (tmp_path / "proposals.jsonl").write_text(
        json.dumps(proposal) + "\n"
    )

    it = OilBotPatternShadowIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    p = json.loads((tmp_path / "proposals.jsonl").read_text().strip())
    assert "shadow_eval" not in p


def test_advisory_proposal_marked_not_applicable(tmp_path):
    cfg_path = _write_config(tmp_path, "cfg.json", _cfg(tmp_path))
    proposal = _approved_proposal()
    proposal["proposed_action"]["kind"] = "advisory"
    (tmp_path / "proposals.jsonl").write_text(
        json.dumps(proposal) + "\n"
    )

    it = OilBotPatternShadowIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    p = json.loads((tmp_path / "proposals.jsonl").read_text().strip())
    assert p["shadow_eval"]["status"] == "not_applicable"
    assert not (tmp_path / "shadow_evals.jsonl").exists()


def test_throttle_via_tick_interval(tmp_path):
    cfg_path = _write_config(
        tmp_path, "cfg.json", _cfg(tmp_path, tick_interval_s=3600),
    )
    (tmp_path / "proposals.jsonl").write_text(
        json.dumps(_approved_proposal()) + "\n"
    )

    it = OilBotPatternShadowIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)  # first call — will try to evaluate

    # Second tick within interval — should be throttled (no crash, no work)
    ctx2 = _fake_ctx()
    it.tick(ctx2)


def test_missing_proposals_file_is_noop(tmp_path):
    cfg_path = _write_config(tmp_path, "cfg.json", _cfg(tmp_path))
    it = OilBotPatternShadowIterator(config_path=str(cfg_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)
    assert ctx.alerts == []


def test_missing_config_is_noop(tmp_path):
    it = OilBotPatternShadowIterator(config_path=str(tmp_path / "nope.json"))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_find_shadow_eval_returns_latest():
    evals = [
        {"proposal_id": 1, "evaluated_at": "2026-04-01"},
        {"proposal_id": 1, "evaluated_at": "2026-04-08"},
        {"proposal_id": 2, "evaluated_at": "2026-04-07"},
    ]
    latest = find_shadow_eval(evals, 1)
    assert latest["evaluated_at"] == "2026-04-08"
    assert find_shadow_eval(evals, 99) is None


def test_load_shadow_evals_missing_file_empty(tmp_path):
    assert load_shadow_evals(str(tmp_path / "nope.jsonl")) == []
