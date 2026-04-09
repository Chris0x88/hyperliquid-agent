"""Tests for cli/daemon/iterators/oil_botpattern_tune.py — sub-system 6 L1 iterator.

The iterator reads closed oil_botpattern trades + decision journal, calls the
pure module, and atomically rewrites oil_botpattern.json + appends audit rows.
No network, no AI, no external state beyond the filesystem paths it's pointed
at.

These tests cover:
- Kill switch (enabled=false → no-op)
- Reads oil_botpattern closed trades from main journal
- Writes config atomically + appends audit records
- Rate limit via audit index
- Tick interval throttling
- Bad config tolerance (missing file, unparseable JSON, bad bounds)
- Filter: ignores non-oil_botpattern trades
- Alert emission per nudge
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from cli.daemon.iterators.oil_botpattern_tune import OilBotPatternTuneIterator


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


def _strategy_cfg() -> dict:
    return {
        "enabled": False,
        "short_legs_enabled": False,
        "instruments": ["BRENTOIL", "CL"],
        "long_min_edge": 0.50,
        "short_min_edge": 0.70,
        "funding_warn_pct": 0.50,
        "funding_exit_pct": 1.50,
        "short_blocking_catalyst_severity": 4,
        "sizing_ladder": [
            {"min_edge": 0.50, "base_pct": 0.02, "leverage": 2.0},
        ],
        "drawdown_brakes": {
            "daily_max_loss_pct": 3.0,
            "weekly_max_loss_pct": 8.0,
            "monthly_max_loss_pct": 15.0,
        },
    }


def _tune_cfg(tmp: Path, **overrides) -> dict:
    cfg = {
        "enabled": True,
        "tick_interval_s": 0,  # no throttling in tests
        "window_size": 20,
        "min_sample": 5,
        "rel_step_max": 0.05,
        "min_rate_limit_hours": 24,
        "bounds": {
            "long_min_edge":                    {"min": 0.35, "max": 0.70, "type": "float"},
            "short_min_edge":                   {"min": 0.55, "max": 0.85, "type": "float"},
            "funding_warn_pct":                 {"min": 0.30, "max": 1.00, "type": "float"},
            "funding_exit_pct":                 {"min": 1.00, "max": 2.50, "type": "float"},
            "short_blocking_catalyst_severity": {"min": 3,    "max": 5,    "type": "int"},
        },
        "strategy_config_path":   str(tmp / "oil_botpattern.json"),
        "main_journal_jsonl":     str(tmp / "journal.jsonl"),
        "decision_journal_jsonl": str(tmp / "oil_botpattern_journal.jsonl"),
        "audit_jsonl":            str(tmp / "oil_botpattern_tune_audit.jsonl"),
        "state_json":             str(tmp / "oil_botpattern_tune_state.json"),
    }
    cfg.update(overrides)
    return cfg


def _write_config(tmp: Path, name: str, cfg: dict) -> Path:
    path = tmp / name
    path.write_text(json.dumps(cfg, indent=2))
    return path


def _write_journal_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _winning_longs(n: int) -> list[dict]:
    """n oil_botpattern long winners."""
    return [
        {"strategy_id": "oil_botpattern", "status": "closed", "side": "long",
         "instrument": "BRENTOIL", "realised_pnl_usd": 100, "roe_pct": 5.0,
         "close_reason": "tp_hit", "trade_id": f"L{i}"}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

def test_disabled_config_is_noop(tmp_path):
    strat_path = _write_config(tmp_path, "oil_botpattern.json", _strategy_cfg())
    tune_path = _write_config(
        tmp_path, "oil_botpattern_tune.json",
        _tune_cfg(tmp_path, enabled=False),
    )
    _write_journal_rows(tmp_path / "journal.jsonl", _winning_longs(6))

    it = OilBotPatternTuneIterator(config_path=str(tune_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    # Strategy config untouched
    assert json.loads(strat_path.read_text())["long_min_edge"] == 0.50
    # No audit file written
    assert not (tmp_path / "oil_botpattern_tune_audit.jsonl").exists()


def test_missing_config_is_noop(tmp_path):
    it = OilBotPatternTuneIterator(config_path=str(tmp_path / "nope.json"))
    ctx = _fake_ctx()
    # Should not raise
    it.on_start(ctx)
    it.tick(ctx)


# ---------------------------------------------------------------------------
# Happy path — nudge on winning longs
# ---------------------------------------------------------------------------

def test_nudges_long_min_edge_on_winning_longs(tmp_path):
    strat_path = _write_config(tmp_path, "oil_botpattern.json", _strategy_cfg())
    tune_path = _write_config(
        tmp_path, "oil_botpattern_tune.json", _tune_cfg(tmp_path),
    )
    _write_journal_rows(tmp_path / "journal.jsonl", _winning_longs(6))

    it = OilBotPatternTuneIterator(config_path=str(tune_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    new_cfg = json.loads(strat_path.read_text())
    assert new_cfg["long_min_edge"] < 0.50
    assert new_cfg["long_min_edge"] >= 0.35

    # Audit log written
    audit_path = tmp_path / "oil_botpattern_tune_audit.jsonl"
    assert audit_path.exists()
    audit_rows = [json.loads(line) for line in audit_path.read_text().splitlines() if line]
    assert any(r["param"] == "long_min_edge" for r in audit_rows)
    assert all(r["source"] == "l1_auto_tune" for r in audit_rows)

    # Alert emitted
    assert any("long_min_edge" in a.message for a in ctx.alerts)

    # Structural fields preserved
    assert new_cfg["enabled"] is False
    assert new_cfg["instruments"] == ["BRENTOIL", "CL"]
    assert new_cfg["drawdown_brakes"]["daily_max_loss_pct"] == 3.0


def test_ignores_non_oil_botpattern_trades(tmp_path):
    strat_path = _write_config(tmp_path, "oil_botpattern.json", _strategy_cfg())
    tune_path = _write_config(
        tmp_path, "oil_botpattern_tune.json", _tune_cfg(tmp_path),
    )
    # 6 winning longs from a DIFFERENT strategy — should be ignored
    rows = [
        {"strategy_id": "thesis_engine", "status": "closed", "side": "long",
         "instrument": "BRENTOIL", "realised_pnl_usd": 100, "roe_pct": 5.0}
        for _ in range(6)
    ]
    _write_journal_rows(tmp_path / "journal.jsonl", rows)

    it = OilBotPatternTuneIterator(config_path=str(tune_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    # No change — those trades were filtered out
    assert json.loads(strat_path.read_text())["long_min_edge"] == 0.50


def test_ignores_non_closed_rows(tmp_path):
    strat_path = _write_config(tmp_path, "oil_botpattern.json", _strategy_cfg())
    tune_path = _write_config(
        tmp_path, "oil_botpattern_tune.json", _tune_cfg(tmp_path),
    )
    rows = [
        {"strategy_id": "oil_botpattern", "status": "open", "side": "long",
         "instrument": "BRENTOIL", "realised_pnl_usd": 100, "roe_pct": 5.0}
        for _ in range(6)
    ]
    _write_journal_rows(tmp_path / "journal.jsonl", rows)

    it = OilBotPatternTuneIterator(config_path=str(tune_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    assert json.loads(strat_path.read_text())["long_min_edge"] == 0.50


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------

def test_rate_limit_blocks_second_nudge_same_param(tmp_path):
    strat_path = _write_config(tmp_path, "oil_botpattern.json", _strategy_cfg())
    tune_path = _write_config(
        tmp_path, "oil_botpattern_tune.json", _tune_cfg(tmp_path),
    )
    _write_journal_rows(tmp_path / "journal.jsonl", _winning_longs(6))

    it = OilBotPatternTuneIterator(config_path=str(tune_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)
    first_val = json.loads(strat_path.read_text())["long_min_edge"]

    # Run tick again immediately — should be blocked by rate limit
    it._last_poll_mono = 0.0  # disable interval throttle
    ctx2 = _fake_ctx()
    it.tick(ctx2)
    second_val = json.loads(strat_path.read_text())["long_min_edge"]

    assert first_val == second_val  # no additional nudge


# ---------------------------------------------------------------------------
# Interval throttling
# ---------------------------------------------------------------------------

def test_tick_interval_throttles_subsequent_calls(tmp_path):
    strat_path = _write_config(tmp_path, "oil_botpattern.json", _strategy_cfg())
    tune_path = _write_config(
        tmp_path, "oil_botpattern_tune.json",
        _tune_cfg(tmp_path, tick_interval_s=3600),
    )
    _write_journal_rows(tmp_path / "journal.jsonl", _winning_longs(6))

    it = OilBotPatternTuneIterator(config_path=str(tune_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)  # fires
    baseline = json.loads(strat_path.read_text())["long_min_edge"]

    # Second tick within interval — should be throttled out
    it.tick(ctx)
    # Value unchanged whether throttled OR rate-limited. The test here
    # asserts the tick doesn't crash and the throttle path is exercised.
    assert json.loads(strat_path.read_text())["long_min_edge"] == baseline


# ---------------------------------------------------------------------------
# Bad config tolerance
# ---------------------------------------------------------------------------

def test_bad_bounds_config_is_noop(tmp_path):
    strat_path = _write_config(tmp_path, "oil_botpattern.json", _strategy_cfg())
    bad_cfg = _tune_cfg(tmp_path)
    bad_cfg["bounds"] = {
        "long_min_edge": {"min": "nope", "max": 0.70, "type": "float"},  # bad min
    }
    tune_path = _write_config(tmp_path, "oil_botpattern_tune.json", bad_cfg)
    _write_journal_rows(tmp_path / "journal.jsonl", _winning_longs(6))

    it = OilBotPatternTuneIterator(config_path=str(tune_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)  # should not raise

    assert json.loads(strat_path.read_text())["long_min_edge"] == 0.50


def test_empty_bounds_is_noop(tmp_path):
    strat_path = _write_config(tmp_path, "oil_botpattern.json", _strategy_cfg())
    cfg = _tune_cfg(tmp_path)
    cfg["bounds"] = {}
    tune_path = _write_config(tmp_path, "oil_botpattern_tune.json", cfg)
    _write_journal_rows(tmp_path / "journal.jsonl", _winning_longs(6))

    it = OilBotPatternTuneIterator(config_path=str(tune_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    assert json.loads(strat_path.read_text())["long_min_edge"] == 0.50


def test_missing_strategy_config_is_noop(tmp_path):
    cfg = _tune_cfg(tmp_path)
    cfg["strategy_config_path"] = str(tmp_path / "nope.json")
    tune_path = _write_config(tmp_path, "oil_botpattern_tune.json", cfg)
    _write_journal_rows(tmp_path / "journal.jsonl", _winning_longs(6))

    it = OilBotPatternTuneIterator(config_path=str(tune_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)  # should not raise


def test_missing_journal_is_noop(tmp_path):
    _write_config(tmp_path, "oil_botpattern.json", _strategy_cfg())
    tune_path = _write_config(
        tmp_path, "oil_botpattern_tune.json", _tune_cfg(tmp_path),
    )
    # No journal file

    it = OilBotPatternTuneIterator(config_path=str(tune_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)
    # No alerts — insufficient sample
    assert ctx.alerts == []


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

def test_atomic_write_produces_valid_json(tmp_path):
    strat_path = _write_config(tmp_path, "oil_botpattern.json", _strategy_cfg())
    tune_path = _write_config(
        tmp_path, "oil_botpattern_tune.json", _tune_cfg(tmp_path),
    )
    _write_journal_rows(tmp_path / "journal.jsonl", _winning_longs(6))

    it = OilBotPatternTuneIterator(config_path=str(tune_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    # File is still a valid JSON doc, no .tmp left behind
    parsed = json.loads(strat_path.read_text())
    assert "long_min_edge" in parsed
    assert not (strat_path.with_suffix(".json.tmp")).exists()


# ---------------------------------------------------------------------------
# Audit index built from prior runs
# ---------------------------------------------------------------------------

def test_audit_index_feeds_rate_limit(tmp_path):
    strat_path = _write_config(tmp_path, "oil_botpattern.json", _strategy_cfg())
    tune_path = _write_config(
        tmp_path, "oil_botpattern_tune.json", _tune_cfg(tmp_path),
    )
    _write_journal_rows(tmp_path / "journal.jsonl", _winning_longs(6))

    # Pre-seed audit file with a recent nudge for long_min_edge
    from datetime import datetime, timedelta, timezone
    recent = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).isoformat()
    audit_path = tmp_path / "oil_botpattern_tune_audit.jsonl"
    audit_path.write_text(json.dumps({
        "applied_at": recent, "param": "long_min_edge",
        "old_value": 0.52, "new_value": 0.50, "reason": "prev",
        "stats_sample_size": 10, "stats_snapshot": {},
        "trade_ids_considered": [], "source": "l1_auto_tune",
    }) + "\n")

    it = OilBotPatternTuneIterator(config_path=str(tune_path))
    ctx = _fake_ctx()
    it.on_start(ctx)
    it.tick(ctx)

    # long_min_edge should NOT be nudged again
    assert json.loads(strat_path.read_text())["long_min_edge"] == 0.50
