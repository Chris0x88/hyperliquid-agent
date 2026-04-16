"""Tests for BotPatternIterator — sub-system 4 wiring layer."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from daemon.iterators.bot_classifier import BotPatternIterator
from engines.data.bot_classifier import read_patterns


def _now():
    """Use real wall-clock so timestamps line up with the iterator's datetime.now()."""
    return datetime.now(tz=timezone.utc)


def _write_config(d, enabled=True, **overrides):
    cfg = {
        "enabled": enabled,
        "instruments": ["BRENTOIL"],
        "poll_interval_s": 0,  # fire on every tick
        "lookback_minutes": 60,
        "cascade_window_min": 30,
        "catalyst_floor": 4,
        "supply_freshness_hours": 72,
        "atr_mult_for_big_move": 1.5,
        "min_price_move_pct_for_classification": 0.5,
        "patterns_jsonl": f"{d}/patterns.jsonl",
        "catalysts_jsonl": f"{d}/catalysts.jsonl",
        "supply_state_json": f"{d}/state.json",
        "cascades_jsonl": f"{d}/cascades.jsonl",
    }
    cfg.update(overrides)
    p = Path(d) / "bot_classifier.json"
    p.write_text(json.dumps(cfg))
    return p


def _candles(price_then=68.50, price_now=67.42, hi_lo_pct=0.4):
    """Return 60 1m candles going from price_then → price_now linearly."""
    rows = []
    for i in range(60):
        frac = i / 59.0
        cl = price_then + (price_now - price_then) * frac
        rng = cl * hi_lo_pct / 100.0
        rows.append({
            "t": int((_now() - timedelta(minutes=60 - i)).timestamp() * 1000),
            "o": cl,
            "h": cl + rng / 2,
            "l": cl - rng / 2,
            "c": cl,
            "v": 1000,
        })
    return rows


def _ctx():
    c = MagicMock()
    c.alerts = []
    return c


def test_iterator_has_name():
    assert BotPatternIterator().name == "bot_classifier"


def test_kill_switch_disables_iterator(tmp_path):
    cfg = _write_config(str(tmp_path), enabled=False)
    calls = []
    it = BotPatternIterator(
        config_path=str(cfg),
        candles_provider=lambda *a, **k: (calls.append(a) or _candles()),
    )
    it.on_start(_ctx())
    it.tick(_ctx())
    assert calls == []
    assert not Path(f"{tmp_path}/patterns.jsonl").exists()


def test_tick_classifies_and_appends_pattern(tmp_path):
    cfg = _write_config(str(tmp_path))
    it = BotPatternIterator(
        config_path=str(cfg),
        candles_provider=lambda *a, **k: _candles(),
    )
    it.on_start(_ctx())
    it.tick(_ctx())
    rows = read_patterns(f"{tmp_path}/patterns.jsonl")
    assert len(rows) == 1
    assert rows[0].instrument == "BRENTOIL"
    assert rows[0].direction == "down"


def test_no_candles_skips(tmp_path):
    cfg = _write_config(str(tmp_path))
    it = BotPatternIterator(
        config_path=str(cfg),
        candles_provider=lambda *a, **k: [],
    )
    it.on_start(_ctx())
    it.tick(_ctx())
    assert not Path(f"{tmp_path}/patterns.jsonl").exists()


def test_classification_uses_cascade_input(tmp_path):
    cfg = _write_config(str(tmp_path))
    # Write a long cascade in the cascades file
    cascade = {
        "id": "BRENTOIL_x",
        "instrument": "BRENTOIL",
        "detected_at": (_now() - timedelta(minutes=5)).isoformat(),
        "window_s": 180,
        "side": "long",
        "oi_delta_pct": -4.2,
        "funding_jump_bps": 22.0,
        "severity": 3,
        "notes": "test",
    }
    Path(f"{tmp_path}/cascades.jsonl").write_text(json.dumps(cascade) + "\n")

    it = BotPatternIterator(
        config_path=str(cfg),
        candles_provider=lambda *a, **k: _candles(price_then=68.50, price_now=67.42),
    )
    ctx = _ctx()
    it.on_start(ctx)
    it.tick(ctx)
    rows = read_patterns(f"{tmp_path}/patterns.jsonl")
    assert len(rows) == 1
    assert rows[0].classification == "bot_driven_overextension"
    # High-confidence overextension emits an alert
    assert any("BOT PATTERN" in a.message for a in ctx.alerts)


def test_classification_uses_catalyst_input(tmp_path):
    cfg = _write_config(str(tmp_path))
    catalyst = {
        "id": "cat-001",
        "severity": 5,
        "direction": "up",
        "category": "opec_cut",
        "published_at": (_now() - timedelta(hours=2)).isoformat(),
        "instruments": ["xyz:BRENTOIL"],
    }
    Path(f"{tmp_path}/catalysts.jsonl").write_text(json.dumps(catalyst) + "\n")
    # Fresh supply state with active disruptions strengthens the informed side
    Path(f"{tmp_path}/state.json").write_text(json.dumps({
        "computed_at": (_now() - timedelta(hours=6)).isoformat(),
        "active_disruption_count": 4,
        "active_chokepoints": ["hormuz_strait"],
        "high_confidence_count": 3,
    }))

    it = BotPatternIterator(
        config_path=str(cfg),
        candles_provider=lambda *a, **k: _candles(price_then=67.40, price_now=68.50),
    )
    ctx = _ctx()
    it.on_start(ctx)
    it.tick(ctx)
    rows = read_patterns(f"{tmp_path}/patterns.jsonl")
    assert len(rows) == 1
    # informed move OR mixed (both acceptable depending on score)
    assert rows[0].classification in ("informed_move", "mixed")
    assert any("catalyst_sev5" in s for s in rows[0].signals)


def test_iterator_registered_in_all_tiers():
    from daemon.tiers import iterators_for_tier
    for tier in ("watch", "rebalance", "opportunistic"):
        assert "bot_classifier" in iterators_for_tier(tier)


def test_atr_helper():
    candles = [
        {"h": 70, "l": 69, "c": 69.5},
        {"h": 71, "l": 69, "c": 70},
        {"h": 70, "l": 68, "c": 69},
    ]
    atr = BotPatternIterator._atr(candles)
    # Mean of (1/69.5, 2/70, 2/69) as %
    assert 1.0 < atr < 3.0
