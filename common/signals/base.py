"""Signal framework primitives — Card, ChartSpec, Result, base class.

These dataclasses are the contract between:
  • Signal authors (who implement compute())
  • The registry (which tracks signals by slug)
  • The dashboard API (which serializes cards + results over JSON)
  • The chart UI (which reads chart_spec to render without special-casing)

Keep this file tiny. Behaviour lives in individual signal modules.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

# Candle shape matches engines/data/candle_cache.py — {t, o, h, l, c, v}
# where t is unix ms and o/h/l/c/v are strings (from SQLite) or floats.
Candle = dict[str, Any]


Category = Literal[
    "volume",         # OBV, CVD, A/D line, volume profile
    "structure",      # HH/HL, order blocks, FVG, liquidity pools
    "momentum",       # RSI, MACD, stochastic
    "regime",         # ADX, Hurst, BB squeeze, regime classifier
    "trend",          # moving averages, slope indicators
    "accumulation",   # Wyckoff phase, VSA, effort/result
]

Placement = Literal["overlay", "subpane"]
SeriesType = Literal["line", "histogram", "area", "markers", "band"]
Axis = Literal["price", "percent", "raw", "oscillator"]


@dataclass(frozen=True)
class SignalCard:
    """Explanatory metadata — rendered verbatim in the dashboard.

    Write this for a trader, not a developer. The dashboard shows this
    when the user expands a signal, and again next to the chart legend.
    If the card doesn't teach the user how to USE the signal, it shouldn't
    ship.

    Fields:
      name:           Human-readable name shown in UI ("On-Balance Volume")
      slug:           Stable kebab-or-snake-case ID used in URLs + registry
                      ("obv", "cvd", "vsa_effort_result")
      category:       One of the Category literals — groups signals in UI
      what:           One-paragraph description of what it measures
      basis:          Source/attribution — paper, book, author, year
      how_to_read:    Bullet-style guide. Concrete: "Rising OBV + flat
                      price = accumulation." Not abstract.
      failure_modes:  When the signal breaks. Low-volume markets, high
                      correlation regimes, news shocks, etc.
      inputs:         Columns the signal reads — "close, volume"
      params:         Default parameter dict — dashboard may expose sliders
    """
    name: str
    slug: str
    category: Category
    what: str
    basis: str
    how_to_read: str
    failure_modes: str
    inputs: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "slug": self.slug,
            "category": self.category,
            "what": self.what,
            "basis": self.basis,
            "how_to_read": self.how_to_read,
            "failure_modes": self.failure_modes,
            "inputs": self.inputs,
            "params": dict(self.params),
        }


@dataclass(frozen=True)
class ChartSpec:
    """How the signal renders. The chart page reads this directly.

    Fields:
      placement:    "overlay" draws on the main price chart. "subpane"
                    creates a sub-panel below the price chart.
      series_type:  line (most), histogram (CVD delta), area (filled
                    oscillators), markers (discrete events — sweeps,
                    phase transitions), band (upper/lower pair).
      color:        Theme token hint ("primary", "tertiary") OR explicit
                    hex. Dashboard resolves tokens against theme.ts.
      axis:         "price" = share price scale. "percent" = 0-100.
                    "oscillator" = centered on zero. "raw" = auto-fit.
      series_name:  Legend label. Often same as card.name but can shorten.
      priority:     Render order for overlays. Higher = on top. 0 is fine.
    """
    placement: Placement
    series_type: SeriesType
    color: str
    axis: Axis
    series_name: str
    priority: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "placement": self.placement,
            "series_type": self.series_type,
            "color": self.color,
            "axis": self.axis,
            "series_name": self.series_name,
            "priority": self.priority,
        }


@dataclass
class SignalResult:
    """Output of Signal.compute(). Fully JSON-serializable.

    Fields:
      slug:        Matches the signal's card.slug
      values:      Time series — list of [timestamp_ms, value] pairs.
                   Primary data drawn on the chart.
      markers:     Optional discrete events — e.g. "phase shift to
                   markup detected at t=X". Each: {time, position
                   ('above'|'below'|'inBar'), color, shape, text}.
      meta:        Current state summary — latest value, signal strength,
                   regime label, etc. Free-form, rendered below the chart.
      card:        Snapshot of the SignalCard (for clients that fetch
                   compute() without a separate card lookup).
      chart_spec:  Snapshot of the ChartSpec (same reason).
    """
    slug: str
    values: list[list[float]] = field(default_factory=list)
    markers: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    card: SignalCard | None = None
    chart_spec: ChartSpec | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "values": self.values,
            "markers": self.markers,
            "meta": self.meta,
            "card": self.card.to_dict() if self.card else None,
            "chart_spec": self.chart_spec.to_dict() if self.chart_spec else None,
        }


class Signal(ABC):
    """Base class for all signals.

    Subclasses MUST set class attributes `card` and `chart_spec`, and
    implement `compute()`. The registry uses `card.slug` as the key.

    Convention: one signal per module. Module path encodes category
    (common/signals/volume/obv.py). Keep compute() pure — no I/O, no
    network, no time.time(). All state comes from `candles` + `params`.
    """
    card: SignalCard
    chart_spec: ChartSpec

    @abstractmethod
    def compute(self, candles: list[Candle], **params: Any) -> SignalResult:
        """Compute the signal over the given candle series.

        Args:
          candles: list of {t,o,h,l,c,v} dicts, sorted by t ascending.
                   String or float values accepted (coerce internally).
          **params: override any card.params default.

        Returns:
          SignalResult with values + meta populated, plus snapshot copies
          of the card and chart_spec for convenient client rendering.
        """
        ...

    @classmethod
    def new_result(cls) -> SignalResult:
        """Helper for subclasses: a pre-stamped SignalResult with card +
        chart_spec snapshots already filled in. Just populate values/meta.
        """
        return SignalResult(
            slug=cls.card.slug,
            card=cls.card,
            chart_spec=cls.chart_spec,
        )
