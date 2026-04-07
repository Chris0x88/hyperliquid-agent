"""Tests for the _load_funding_summary helper added to cli/daily_report.py (C5)."""
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from cli import daily_report


@pytest.fixture
def tmp_funding(tmp_path, monkeypatch):
    """Redirect daily_report's CWD-relative funding path into a tmp dir."""
    daemon_dir = tmp_path / "data" / "daemon"
    daemon_dir.mkdir(parents=True)
    # daily_report uses relative path "data/daemon/funding_tracker.jsonl"
    monkeypatch.chdir(tmp_path)
    yield daemon_dir / "funding_tracker.jsonl"


def _write(path: Path, records: list):
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _now() -> int:
    return int(time.time())


class TestEmpty:
    def test_no_file_returns_unavailable(self, tmp_funding):
        # File does not exist
        assert not tmp_funding.exists()
        result = daily_report._load_funding_summary(hours=24)
        assert result["available"] is False
        assert result["paid_usd"] == 0.0
        assert result["earned_usd"] == 0.0
        assert result["net_usd"] == 0.0
        assert result["by_instrument"] == {}

    def test_empty_file_returns_zeros(self, tmp_funding):
        tmp_funding.write_text("")
        result = daily_report._load_funding_summary(hours=24)
        assert result["available"] is True
        assert result["paid_usd"] == 0.0
        assert result["earned_usd"] == 0.0


class TestAggregation:
    def test_paid_only(self, tmp_funding):
        now = _now()
        _write(tmp_funding, [
            {"timestamp": now - 1000, "instrument": "BTC", "rate": 0.0001, "payment_usd": 5.0, "cumulative_usd": 5.0},
            {"timestamp": now - 500, "instrument": "BTC", "rate": 0.0001, "payment_usd": 3.0, "cumulative_usd": 8.0},
        ])
        result = daily_report._load_funding_summary(hours=24)
        assert result["paid_usd"] == 8.0
        assert result["earned_usd"] == 0.0
        assert result["net_usd"] == -8.0

    def test_earned_only(self, tmp_funding):
        now = _now()
        _write(tmp_funding, [
            {"timestamp": now - 100, "instrument": "ETH", "rate": -0.0002, "payment_usd": -2.0, "cumulative_usd": -2.0},
        ])
        result = daily_report._load_funding_summary(hours=24)
        assert result["paid_usd"] == 0.0
        assert result["earned_usd"] == 2.0
        assert result["net_usd"] == 2.0

    def test_mixed_paid_and_earned(self, tmp_funding):
        now = _now()
        _write(tmp_funding, [
            {"timestamp": now - 100, "instrument": "BTC", "payment_usd": 5.0},
            {"timestamp": now - 50, "instrument": "ETH", "payment_usd": -3.0},
        ])
        result = daily_report._load_funding_summary(hours=24)
        assert result["paid_usd"] == 5.0
        assert result["earned_usd"] == 3.0
        assert result["net_usd"] == -2.0

    def test_per_instrument_breakdown(self, tmp_funding):
        now = _now()
        _write(tmp_funding, [
            {"timestamp": now - 100, "instrument": "BTC", "payment_usd": 5.0},
            {"timestamp": now - 50, "instrument": "BTC", "payment_usd": 2.0},
            {"timestamp": now - 25, "instrument": "ETH", "payment_usd": -1.0},
        ])
        result = daily_report._load_funding_summary(hours=24)
        assert "BTC" in result["by_instrument"]
        assert "ETH" in result["by_instrument"]
        btc = result["by_instrument"]["BTC"]
        assert btc["paid"] == 7.0
        assert btc["earned"] == 0.0
        assert btc["events"] == 2
        eth = result["by_instrument"]["ETH"]
        assert eth["paid"] == 0.0
        assert eth["earned"] == 1.0
        assert eth["events"] == 1


class TestTimeWindow:
    def test_old_records_excluded(self, tmp_funding):
        now = _now()
        old = now - 30 * 3600  # 30 hours ago — outside 24h window
        recent = now - 2 * 3600  # 2 hours ago — inside window
        _write(tmp_funding, [
            {"timestamp": old, "instrument": "BTC", "payment_usd": 100.0},
            {"timestamp": recent, "instrument": "BTC", "payment_usd": 5.0},
        ])
        result = daily_report._load_funding_summary(hours=24)
        assert result["paid_usd"] == 5.0  # only recent
        assert result["by_instrument"]["BTC"]["events"] == 1

    def test_custom_hours_window(self, tmp_funding):
        now = _now()
        _write(tmp_funding, [
            {"timestamp": now - 5 * 3600, "instrument": "BTC", "payment_usd": 10.0},
            {"timestamp": now - 1 * 3600, "instrument": "BTC", "payment_usd": 3.0},
        ])
        # 2-hour window: only the second record qualifies
        result = daily_report._load_funding_summary(hours=2)
        assert result["paid_usd"] == 3.0


class TestRobustness:
    def test_malformed_lines_skipped(self, tmp_funding):
        now = _now()
        with open(tmp_funding, "w") as f:
            f.write(json.dumps({"timestamp": now, "instrument": "BTC", "payment_usd": 5.0}) + "\n")
            f.write("not json\n")
            f.write("\n")
            f.write(json.dumps({"timestamp": now, "instrument": "ETH", "payment_usd": -2.0}) + "\n")
        result = daily_report._load_funding_summary(hours=24)
        assert result["paid_usd"] == 5.0
        assert result["earned_usd"] == 2.0

    def test_missing_payment_field(self, tmp_funding):
        now = _now()
        _write(tmp_funding, [
            {"timestamp": now, "instrument": "BTC"},  # no payment_usd
        ])
        # Treated as 0 — should not crash
        result = daily_report._load_funding_summary(hours=24)
        assert result["paid_usd"] == 0.0
        assert result["earned_usd"] == 0.0
