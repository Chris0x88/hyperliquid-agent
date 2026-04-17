"""Signal registry — slug → Signal class.

Import order matters: signal modules call @register at import time, so
common/signals/__init__.py MUST import all sub-packages before anyone
calls all_signals() / get() / compute().
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from common.signals.base import Candle, Category, Signal, SignalResult

_REGISTRY: dict[str, type[Signal]] = {}


def register(cls: type[Signal]) -> type[Signal]:
    """Class decorator. Registers a Signal subclass by its card.slug.

    Raises ValueError on slug collision — two signals with the same slug
    would silently shadow each other in the UI.
    """
    slug = cls.card.slug
    if slug in _REGISTRY and _REGISTRY[slug] is not cls:
        raise ValueError(
            f"Signal slug collision: {slug!r} already registered by "
            f"{_REGISTRY[slug].__module__}.{_REGISTRY[slug].__name__}, "
            f"new attempt from {cls.__module__}.{cls.__name__}"
        )
    _REGISTRY[slug] = cls
    return cls


def get(slug: str) -> type[Signal] | None:
    """Fetch a registered Signal class by slug. Returns None if missing."""
    return _REGISTRY.get(slug)


def all_signals() -> list[type[Signal]]:
    """All registered Signal classes, sorted by (category, name)."""
    return sorted(
        _REGISTRY.values(),
        key=lambda c: (c.card.category, c.card.name),
    )


def by_category() -> dict[str, list[type[Signal]]]:
    """All registered signals grouped by category. Useful for UI rendering."""
    grouped: dict[str, list[type[Signal]]] = defaultdict(list)
    for cls in all_signals():
        grouped[cls.card.category].append(cls)
    return dict(grouped)


def compute(slug: str, candles: list[Candle], **params: Any) -> SignalResult:
    """Compute a signal by slug. Raises KeyError if slug is unknown."""
    cls = _REGISTRY.get(slug)
    if cls is None:
        raise KeyError(f"Unknown signal slug: {slug!r}. "
                       f"Registered: {sorted(_REGISTRY.keys())}")
    return cls().compute(candles, **params)


def _reset_for_tests() -> None:
    """Clear the registry. Tests only — production code should never call this."""
    _REGISTRY.clear()


def _count() -> int:
    """Registered signal count. Debugging helper."""
    return len(_REGISTRY)
