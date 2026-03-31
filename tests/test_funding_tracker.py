"""Tests for common.funding_tracker — cumulative funding cost tracking."""
import json
import time
from pathlib import Path

import pytest
from common.funding_tracker import FundingTracker, PositionFunding, FundingRecord


class TestPositionFunding:
    def test_record_single(self):
        pf = PositionFunding(symbol="BRENTOIL")
        rec = pf.record(funding_rate=0.000125, position_notional=500, timestamp=1000)
        assert rec.cost_usd == pytest.approx(0.0625, abs=0.001)
        assert pf.hours_tracked == 1
        assert pf.total_paid_usd == pytest.approx(0.0625, abs=0.001)

    def test_negative_funding_received(self):
        pf = PositionFunding(symbol="BTC")
        pf.record(funding_rate=-0.0001, position_notional=1000, timestamp=1000)
        assert pf.total_paid_usd < 0  # we received
        assert pf.total_received_usd == pytest.approx(0.1, abs=0.001)

    def test_days_tracked(self):
        pf = PositionFunding(symbol="TEST")
        for i in range(48):
            pf.record(0.0001, 100, timestamp=1000 + i * 3600)
        assert pf.days_tracked == pytest.approx(2.0)

    def test_net_cost(self):
        pf = PositionFunding(symbol="TEST")
        pf.record(0.001, 100)   # paid 0.1
        pf.record(-0.001, 100)  # received 0.1
        assert pf.net_cost_usd == pytest.approx(0.0, abs=0.01)

    def test_recent_trend_paying(self):
        pf = PositionFunding(symbol="TEST")
        for _ in range(5):
            pf.record(0.001, 1000)  # paying a lot
        assert pf.recent_trend == "paying"

    def test_recent_trend_earning(self):
        pf = PositionFunding(symbol="TEST")
        for _ in range(5):
            pf.record(-0.001, 1000)  # earning
        assert pf.recent_trend == "earning"

    def test_recent_trend_insufficient(self):
        pf = PositionFunding(symbol="TEST")
        pf.record(0.0001, 100)
        assert pf.recent_trend == "insufficient_data"

    def test_summary_format(self):
        pf = PositionFunding(symbol="BRENTOIL")
        pf.record(0.0001, 500, timestamp=1000)
        summary = pf.summary()
        assert "BRENTOIL" in summary
        assert "paid" in summary or "earned" in summary

    def test_rolling_window_cap(self):
        pf = PositionFunding(symbol="TEST")
        pf._max_recent = 5
        for i in range(10):
            pf.record(0.0001, 100, timestamp=i * 3600)
        assert len(pf.recent_records) == 5


class TestFundingTracker:
    def test_record_and_get(self, tmp_path):
        t = FundingTracker(state_dir=tmp_path)
        t.record("BRENTOIL", 0.0001, 500)
        pf = t.get("BRENTOIL")
        assert pf is not None
        assert pf.hours_tracked == 1

    def test_multi_symbol(self, tmp_path):
        t = FundingTracker(state_dir=tmp_path)
        t.record("BRENTOIL", 0.0001, 500)
        t.record("BTC", -0.00005, 1000)
        assert t.get("BRENTOIL").total_paid_usd > 0
        assert t.get("BTC").total_paid_usd < 0

    def test_persistence(self, tmp_path):
        t1 = FundingTracker(state_dir=tmp_path)
        t1.record("BRENTOIL", 0.001, 500)
        t1.record("BRENTOIL", 0.001, 500)

        # Load fresh from disk
        t2 = FundingTracker(state_dir=tmp_path)
        pf = t2.get("BRENTOIL")
        assert pf is not None
        assert pf.hours_tracked == 2

    def test_clear(self, tmp_path):
        t = FundingTracker(state_dir=tmp_path)
        t.record("TEST", 0.0001, 100)
        t.clear("TEST")
        assert t.get("TEST") is None

    def test_summary(self, tmp_path):
        t = FundingTracker(state_dir=tmp_path)
        t.record("BRENTOIL", 0.001, 500)
        t.record("BTC", -0.0005, 1000)
        s = t.summary()
        assert "BRENTOIL" in s
        assert "BTC" in s

    def test_empty_summary(self, tmp_path):
        t = FundingTracker(state_dir=tmp_path)
        assert "No funding data" in t.summary()

    def test_file_written(self, tmp_path):
        t = FundingTracker(state_dir=tmp_path)
        t.record("TEST", 0.0001, 100)
        assert (tmp_path / "funding.json").exists()
        data = json.loads((tmp_path / "funding.json").read_text())
        assert "TEST" in data
