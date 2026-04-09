from __future__ import annotations

from cli.risk_monitor import _calc_drawdown_pct, _calc_liq_distance_pct


def test_calc_drawdown_pct_handles_long_and_short():
    assert round(_calc_drawdown_pct(100.0, 90.0, 1.0), 2) == 10.0
    assert round(_calc_drawdown_pct(100.0, 110.0, -1.0), 2) == 10.0
    assert _calc_drawdown_pct(100.0, 105.0, 1.0) == 0.0


def test_calc_liq_distance_pct_handles_long_and_short():
    assert round(_calc_liq_distance_pct(100.0, 90.0, 1.0), 2) == 10.0
    assert round(_calc_liq_distance_pct(100.0, 110.0, -1.0), 2) == 10.0
    assert _calc_liq_distance_pct(100.0, 0.0, 1.0) == 0.0
