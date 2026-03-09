"""Shared setup for quoting-engine-powered strategies.

Adds the quoting_engine package paths to sys.path so it is importable
without pip install. Raises a clear error if the module is not found.
"""
from __future__ import annotations

import os
import sys

_QE_PARENT = os.path.expanduser("~/Tee-work-")
_QE_ROOT = os.path.join(_QE_PARENT, "quoting_engine")

if not os.path.isdir(_QE_ROOT):
    raise ImportError(
        f"quoting_engine not found at {_QE_ROOT}. "
        "The following strategies require it: engine_mm, regime_mm, grid_mm, "
        "liquidation_mm, funding_arb. "
        "Use simple_mm or avellaneda_mm as open-source alternatives."
    )

for p in [_QE_PARENT, _QE_ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)
