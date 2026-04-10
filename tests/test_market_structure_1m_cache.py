"""Tests for the 1m candle caching policy in market_structure_iter.

Added 2026-04-09: extends _refresh_candles to also populate 1m rows
for sub-system 4's classifier consumers. Prior to this wedge,
bot_classifier had to direct-fetch from HL on every poll because the
cache never held 1m data (market_structure_iter only stored 1h/4h/1d).

This file tests the refresh POLICY only — it does not exercise live
HL API calls. A fake cache + patched requests.post cover both the
"fresh enough, skip" and "stale, fetch + store" paths.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from cli.daemon.iterators.market_structure_iter import (
    MarketStructureIterator,
    _OIL_CLASSIFIER_MARKETS,
)


class _FakeCache:
    """In-memory CandleCache stand-in."""

    def __init__(self, date_ranges: dict | None = None):
        # (coin, interval) -> (earliest_ms, latest_ms)
        self._date_ranges: dict = dict(date_ranges or {})
        self.stored_calls: list = []

    def date_range(self, coin: str, interval: str):
        return self._date_ranges.get((coin, interval))

    def store_candles(self, coin: str, interval: str, rows: list) -> int:
        self.stored_calls.append((coin, interval, len(rows)))
        # Pretend the cache advanced to "now" after a successful store
        now_ms = int(time.time() * 1000)
        prev = self._date_ranges.get((coin, interval)) or (now_ms, now_ms)
        self._date_ranges[(coin, interval)] = (prev[0], now_ms)
        return len(rows)


def _iterator(cache: _FakeCache) -> MarketStructureIterator:
    it = MarketStructureIterator(candle_cache=cache)
    return it


_SENTINEL = object()


def _fake_response(status_code: int = 200, rows=_SENTINEL):
    m = MagicMock()
    m.status_code = status_code
    if rows is _SENTINEL:
        rows = [{"t": 1, "o": 95.0, "h": 95.5, "l": 94.5, "c": 95.2, "v": 1.0}]
    m.json.return_value = rows
    return m


# ---------------------------------------------------------------------------
# Module-level constant
# ---------------------------------------------------------------------------

def test_oil_classifier_markets_contains_expected_pairs():
    assert "xyz:BRENTOIL" in _OIL_CLASSIFIER_MARKETS
    assert "xyz:CL" in _OIL_CLASSIFIER_MARKETS


def test_oil_classifier_markets_is_narrow():
    """Cache load guard: only the two oil instruments should be in the
    1m-cached set. If a future change broadens this, the test should
    be intentionally updated — not silently widened."""
    assert len(_OIL_CLASSIFIER_MARKETS) == 2


# ---------------------------------------------------------------------------
# Happy path: 1m cache is stale → fetch + store
# ---------------------------------------------------------------------------

def test_refresh_fetches_1m_for_oil_markets_when_stale():
    cache = _FakeCache()
    it = _iterator(cache)

    with patch("cli.daemon.iterators.market_structure_iter.requests.post") as post:
        post.return_value = _fake_response()
        it._refresh_candles({"xyz:BRENTOIL"}, lookback_hours=168)

    # All four intervals should have been requested for BRENTOIL
    request_intervals = [c.kwargs["json"]["req"]["interval"] for c in post.call_args_list]
    assert "1h" in request_intervals
    assert "4h" in request_intervals
    assert "1d" in request_intervals
    assert "1m" in request_intervals

    # store_candles called for each
    stored_intervals = [s[1] for s in cache.stored_calls]
    assert "1m" in stored_intervals


def test_refresh_skips_1m_for_non_oil_markets():
    cache = _FakeCache()
    it = _iterator(cache)

    with patch("cli.daemon.iterators.market_structure_iter.requests.post") as post:
        post.return_value = _fake_response()
        it._refresh_candles({"BTC"}, lookback_hours=168)

    # BTC gets 1h/4h/1d but NOT 1m
    request_intervals = [c.kwargs["json"]["req"]["interval"] for c in post.call_args_list]
    assert "1h" in request_intervals
    assert "1m" not in request_intervals


def test_refresh_skips_1m_when_cache_is_fresh_enough():
    """Within the 5-min staleness window, 1m fetches should skip."""
    now_ms = int(time.time() * 1000)
    # Cache has 1m data from 1 minute ago — well under 5-min threshold
    fresh_range = (now_ms - 300_000, now_ms - 60_000)
    cache = _FakeCache(date_ranges={("xyz:BRENTOIL", "1m"): fresh_range})
    it = _iterator(cache)

    with patch("cli.daemon.iterators.market_structure_iter.requests.post") as post:
        post.return_value = _fake_response()
        it._refresh_candles({"xyz:BRENTOIL"}, lookback_hours=168)

    request_intervals = [c.kwargs["json"]["req"]["interval"] for c in post.call_args_list]
    assert "1m" not in request_intervals
    # Other intervals may or may not fire depending on their fresh ranges;
    # the important assertion is the 1m-skip path.


def test_refresh_fetches_1m_when_stale_past_5_min():
    now_ms = int(time.time() * 1000)
    stale_range = (now_ms - 600_000, now_ms - 600_000)  # 10 min old
    cache = _FakeCache(date_ranges={("xyz:BRENTOIL", "1m"): stale_range})
    it = _iterator(cache)

    with patch("cli.daemon.iterators.market_structure_iter.requests.post") as post:
        post.return_value = _fake_response()
        it._refresh_candles({"xyz:BRENTOIL"}, lookback_hours=168)

    # Fetch fires because stale > 5 min
    request_intervals = [c.kwargs["json"]["req"]["interval"] for c in post.call_args_list]
    assert "1m" in request_intervals


# ---------------------------------------------------------------------------
# Lookback window
# ---------------------------------------------------------------------------

def test_1m_lookback_is_120_minutes_not_lookback_hours():
    """1m fetches use a 120-minute lookback, not the lookback_hours
    parameter that 1h/4h/1d use."""
    cache = _FakeCache()
    it = _iterator(cache)

    with patch("cli.daemon.iterators.market_structure_iter.requests.post") as post:
        post.return_value = _fake_response()
        it._refresh_candles({"xyz:BRENTOIL"}, lookback_hours=168)

    # Find the 1m call and check its startTime
    one_m_calls = [
        c for c in post.call_args_list
        if c.kwargs["json"]["req"]["interval"] == "1m"
    ]
    assert len(one_m_calls) == 1
    req = one_m_calls[0].kwargs["json"]["req"]
    window_ms = req["endTime"] - req["startTime"]
    # 120 minutes = 7_200_000 ms — allow a second of slack for clock
    assert 7_000_000 <= window_ms <= 7_300_000


# ---------------------------------------------------------------------------
# Error tolerance
# ---------------------------------------------------------------------------

def test_refresh_tolerates_http_errors():
    cache = _FakeCache()
    it = _iterator(cache)

    with patch("cli.daemon.iterators.market_structure_iter.requests.post") as post:
        post.side_effect = Exception("network down")
        # Should not raise — errors logged at debug level
        it._refresh_candles({"xyz:BRENTOIL"}, lookback_hours=168)

    assert cache.stored_calls == []


def test_refresh_tolerates_empty_response():
    cache = _FakeCache()
    it = _iterator(cache)

    with patch("cli.daemon.iterators.market_structure_iter.requests.post") as post:
        post.return_value = _fake_response(status_code=200, rows=[])
        it._refresh_candles({"xyz:BRENTOIL"}, lookback_hours=168)

    # Empty candle list → nothing stored
    assert cache.stored_calls == []
