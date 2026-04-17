"""common/signals — deterministic signal library.

Design goals (2026-04-17):
  • Mechanical, not AI. Signals are pure Python — AI is only used to WRITE
    the code, never to run it at decision time.
  • Every signal ships with a SignalCard (what it measures, how to read it,
    basis, failure modes) so the dashboard can auto-render the explainer.
  • Every signal ships with a ChartSpec so the chart page can overlay or
    sub-pane it without special-casing each signal.
  • Registry-driven. Dashboard discovers signals via `all_signals()` — no
    hard-coded lists in the UI.

Usage:
    from common.signals import all_signals, get, compute

    for sig_cls in all_signals():
        print(sig_cls.card.name)

    result = compute("obv", candles)  # returns SignalResult

Adding a new signal:
  1. Create a module under common/signals/<category>/<slug>.py
  2. Subclass Signal, fill in .card + .chart_spec, implement compute()
  3. Decorate the class with @register
  4. Add an import to common/signals/<category>/__init__.py

The dashboard + API pick it up automatically.
"""
from common.signals.base import (
    Candle,
    ChartSpec,
    Signal,
    SignalCard,
    SignalResult,
)
from common.signals.registry import (
    all_signals,
    by_category,
    compute,
    get,
    register,
)

# Eagerly import signal sub-packages so their @register decorators fire.
# Each sub-package imports its individual signals in its __init__.py.
from common.signals import volume  # noqa: F401
from common.signals import accumulation  # noqa: F401
from common.signals import regime  # noqa: F401

__all__ = [
    "Candle",
    "ChartSpec",
    "Signal",
    "SignalCard",
    "SignalResult",
    "all_signals",
    "by_category",
    "compute",
    "get",
    "register",
]
