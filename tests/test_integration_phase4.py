"""Phase 4a integration tests — REFLECT validation.

Tests reflect_adapter suggestions and ApexConfig JSON roundtrip.

Read-only validation: no production code is modified.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is importable
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.apex_config import ApexConfig
from modules.reflect_adapter import suggest_research_directions
from modules.reflect_engine import ReflectMetrics


# ===========================================================================
# 1. reflect_adapter.suggest_research_directions()
# ===========================================================================

class TestReflectAdapterDirections:

    def test_high_fdr_suggests_radar_threshold(self):
        metrics = ReflectMetrics(
            total_round_trips=10,
            fdr=35.0,
            win_rate=55.0,
            net_pnl=100.0,
            gross_pnl=200.0,
            total_fees=50.0,
        )
        directions = suggest_research_directions(metrics)
        assert any("radar_score_threshold" in d for d in directions), \
            f"High FDR should suggest radar_score_threshold. Got: {directions}"

    def test_low_win_rate_suggests_pulse_confidence(self):
        metrics = ReflectMetrics(
            total_round_trips=10,
            win_rate=35.0,
            fdr=10.0,
            net_pnl=50.0,
            gross_pnl=100.0,
            total_fees=5.0,
        )
        directions = suggest_research_directions(metrics)
        assert any("pulse_confidence" in d.lower() for d in directions), \
            f"Low win rate should suggest pulse_confidence. Got: {directions}"

    def test_both_issues_present(self):
        metrics = ReflectMetrics(
            total_round_trips=10,
            fdr=35.0,
            win_rate=35.0,
            net_pnl=50.0,
            gross_pnl=100.0,
            total_fees=30.0,
        )
        directions = suggest_research_directions(metrics)
        has_radar = any("radar_score_threshold" in d for d in directions)
        has_pulse = any("pulse_confidence" in d.lower() for d in directions)
        assert has_radar and has_pulse, \
            f"Both FDR and win_rate issues should produce both suggestions. Got: {directions}"

    def test_healthy_metrics_suggest_relaxing(self):
        metrics = ReflectMetrics(
            total_round_trips=10,
            win_rate=60.0,
            fdr=10.0,
            net_pnl=500.0,
            gross_pnl=600.0,
            total_fees=20.0,
        )
        directions = suggest_research_directions(metrics)
        text = " ".join(directions).lower()
        assert "healthy" in text or "lower" in text or "relax" in text, \
            f"Healthy metrics should suggest relaxing. Got: {directions}"

    def test_insufficient_data(self):
        metrics = ReflectMetrics(total_round_trips=2)
        directions = suggest_research_directions(metrics)
        assert len(directions) == 1
        assert "more trades" in directions[0].lower()


# ===========================================================================
# 2. ApexConfig JSON roundtrip
# ===========================================================================

class TestApexConfigRoundtrip:

    def test_json_roundtrip_non_defaults(self, tmp_path):
        original = ApexConfig(
            total_budget=25_000.0,
            max_slots=5,
            leverage=15.0,
            radar_score_threshold=220,
            pulse_confidence_threshold=85.0,
            daily_loss_limit=750.0,
            max_same_direction=1,
            min_hold_ms=3_000_000,
            slot_cooldown_ms=600_000,
            cooldown_duration_ms=2_400_000,
            entry_order_type="Gtc",
        )
        path = str(tmp_path / "apex_config.json")
        original.to_json(path)
        restored = ApexConfig.from_json(path)

        assert restored.total_budget == original.total_budget
        assert restored.max_slots == original.max_slots
        assert restored.leverage == original.leverage
        assert restored.radar_score_threshold == original.radar_score_threshold
        assert restored.pulse_confidence_threshold == original.pulse_confidence_threshold
        assert restored.daily_loss_limit == original.daily_loss_limit
        assert restored.max_same_direction == original.max_same_direction

    def test_phase3_fields_survive_roundtrip(self, tmp_path):
        """Phase 3 fields must survive JSON serialization."""
        original = ApexConfig(
            min_hold_ms=5_000_000,
            slot_cooldown_ms=900_000,
            cooldown_duration_ms=3_600_000,
            entry_order_type="Alo",
        )
        path = str(tmp_path / "config.json")
        original.to_json(path)
        restored = ApexConfig.from_json(path)

        assert restored.min_hold_ms == 5_000_000
        assert restored.slot_cooldown_ms == 900_000
        assert restored.cooldown_duration_ms == 3_600_000
        assert restored.entry_order_type == "Alo"

    def test_roundtrip_all_fields(self, tmp_path):
        """Every field in to_dict() should survive the roundtrip."""
        original = ApexConfig()
        path = str(tmp_path / "config.json")
        original.to_json(path)
        restored = ApexConfig.from_json(path)

        orig_dict = original.to_dict()
        rest_dict = restored.to_dict()

        for key in orig_dict:
            assert key in rest_dict, f"Missing field after roundtrip: {key}"
            assert orig_dict[key] == rest_dict[key], \
                f"Field {key} mismatch: {orig_dict[key]} != {rest_dict[key]}"
