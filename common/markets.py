"""Market registry — per-instrument metadata loaded from data/config/markets.yaml.

Pure data + lookup. NO business logic, NO I/O beyond loading the YAML on init.
The engines that call this (conviction_engine, sizing, risk caps, ...) keep
their own behaviour — this module just answers "what is the shape of symbol X?".

Wedge 1 of the Multi-Market Expansion. See
``docs/plans/MULTI_MARKET_EXPANSION_PLAN.md`` for the full plan.

xyz-prefix handling
-------------------
The xyz clearinghouse returns universe names with an ``xyz:`` prefix
(``xyz:BRENTOIL``), while the native clearinghouse does not (``BTC``). This
registry normalises both forms so callers can pass either string and get the
same row back. Mirrors the ``_coin_matches()`` helper in ``cli/telegram_bot.py``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Mapping, Optional

import yaml

log = logging.getLogger("markets")

DirectionBias = Literal["long_only", "short_only", "neutral"]
Direction = Literal["long", "short", "neutral", "flat", ""]

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "config" / "markets.yaml"
)


def _normalize_symbol(symbol: str) -> str:
    """Strip the ``xyz:`` prefix so lookups work with either form.

    Examples
    --------
    >>> _normalize_symbol("BRENTOIL")
    'BRENTOIL'
    >>> _normalize_symbol("xyz:BRENTOIL")
    'BRENTOIL'
    >>> _normalize_symbol("XYZ:brentoil")
    'BRENTOIL'
    """
    if not symbol:
        return ""
    s = symbol.strip()
    # Case-insensitive prefix strip so "XYZ:BRENTOIL" and "xyz:BRENTOIL" both work
    if s.lower().startswith("xyz:"):
        s = s[4:]
    return s.upper()


@dataclass(frozen=True)
class MarketSpec:
    """Immutable per-instrument metadata."""

    symbol: str
    direction_bias: DirectionBias
    asset_class: str
    max_leverage: int
    thesis_required: bool = True
    sub_class: Optional[str] = None
    roll_calendar: Optional[str] = None
    exception_subsystems: tuple[str, ...] = field(default_factory=tuple)


class MarketRegistry:
    """Loads markets.yaml and answers per-market metadata questions.

    Keep this class pure-data: all business logic (sizing, stops, execution)
    stays in the engines that call it. The registry just looks things up.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self._path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._markets: dict[str, MarketSpec] = {}
        self._version: int = 0
        self._load()

    # ── Loading ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(
                f"markets.yaml not found at {self._path}. "
                "Wedge 1 of the Multi-Market Expansion requires this file."
            )
        with self._path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        self._version = int(raw.get("version", 0))
        rows: Mapping[str, Mapping] = raw.get("markets", {}) or {}
        if not rows:
            raise ValueError(
                f"markets.yaml at {self._path} has no 'markets' section"
            )

        parsed: dict[str, MarketSpec] = {}
        for symbol, row in rows.items():
            norm = _normalize_symbol(symbol)
            if not norm:
                log.warning("Skipping empty market symbol in %s", self._path)
                continue
            try:
                parsed[norm] = self._parse_row(norm, row)
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError(
                    f"markets.yaml: invalid row for {symbol!r}: {exc}"
                ) from exc
        self._markets = parsed

    @staticmethod
    def _parse_row(symbol: str, row: Mapping) -> MarketSpec:
        direction_bias = str(row.get("direction_bias", "neutral")).lower()
        if direction_bias not in ("long_only", "short_only", "neutral"):
            raise ValueError(
                f"direction_bias must be long_only/short_only/neutral, "
                f"got {direction_bias!r}"
            )
        asset_class = str(row.get("asset_class", "")).strip()
        if not asset_class:
            raise ValueError("asset_class is required")
        max_leverage_raw = row.get("max_leverage")
        if max_leverage_raw is None:
            raise ValueError("max_leverage is required")
        max_leverage = int(max_leverage_raw)
        if max_leverage <= 0:
            raise ValueError(f"max_leverage must be > 0, got {max_leverage}")
        thesis_required = bool(row.get("thesis_required", True))
        sub_class = row.get("sub_class")
        sub_class = str(sub_class).strip() if sub_class else None
        roll_calendar = row.get("roll_calendar")
        roll_calendar = str(roll_calendar).strip() if roll_calendar else None
        excs_raw = row.get("exception_subsystems") or []
        if not isinstance(excs_raw, (list, tuple)):
            raise ValueError("exception_subsystems must be a list")
        exception_subsystems = tuple(str(e).strip() for e in excs_raw if str(e).strip())
        return MarketSpec(
            symbol=symbol,
            direction_bias=direction_bias,  # type: ignore[arg-type]
            asset_class=asset_class,
            max_leverage=max_leverage,
            thesis_required=thesis_required,
            sub_class=sub_class,
            roll_calendar=roll_calendar,
            exception_subsystems=exception_subsystems,
        )

    # ── Lookup helpers ─────────────────────────────────────────────────────

    @property
    def version(self) -> int:
        return self._version

    def known_symbols(self) -> tuple[str, ...]:
        """Return all registered (normalised) symbols in sorted order."""
        return tuple(sorted(self._markets.keys()))

    def is_known(self, symbol: str) -> bool:
        return _normalize_symbol(symbol) in self._markets

    def get(self, symbol: str) -> Optional[MarketSpec]:
        """Return the spec for ``symbol`` (xyz:-prefix tolerant), or None."""
        return self._markets.get(_normalize_symbol(symbol))

    def _require(self, symbol: str) -> MarketSpec:
        spec = self.get(symbol)
        if spec is None:
            raise KeyError(
                f"Unknown market {symbol!r}. Known symbols: "
                f"{', '.join(self.known_symbols()) or '(none)'}"
            )
        return spec

    # ── Public API required by Wedge 1 ─────────────────────────────────────

    def get_direction_bias(self, symbol: str) -> DirectionBias:
        """Return the direction_bias for ``symbol``.

        Raises KeyError if the symbol is not in the registry.
        """
        return self._require(symbol).direction_bias

    def get_max_leverage(self, symbol: str) -> int:
        """Return the leverage cap for ``symbol``.

        Raises KeyError if the symbol is not in the registry.
        """
        return self._require(symbol).max_leverage

    def is_thesis_required(self, symbol: str) -> bool:
        return self._require(symbol).thesis_required

    def is_direction_allowed(
        self,
        symbol: str,
        direction: str,
        subsystem: Optional[str] = None,
    ) -> bool:
        """Is ``direction`` allowed for ``symbol`` under ``subsystem``?

        Rules:
        - ``neutral`` direction_bias allows everything.
        - ``long_only`` blocks ``short`` unless ``subsystem`` is in the row's
          ``exception_subsystems``.
        - ``short_only`` blocks ``long`` unless ``subsystem`` is in the row's
          ``exception_subsystems``.
        - Empty / ``flat`` / ``neutral`` direction is always allowed (they
          represent "no position" or "close", not a new trade direction).
        - Unknown symbols return False (fail-closed). Callers that want the
          old "pass unknown" behaviour should check ``is_known()`` first.
        """
        spec = self.get(symbol)
        if spec is None:
            log.warning(
                "is_direction_allowed: unknown symbol %r — failing closed",
                symbol,
            )
            return False

        d = (direction or "").strip().lower()
        # Non-directional states are always allowed
        if d in ("", "flat", "neutral"):
            return True
        if d not in ("long", "short"):
            log.warning(
                "is_direction_allowed: unknown direction %r for %s — failing closed",
                direction,
                symbol,
            )
            return False

        if spec.direction_bias == "neutral":
            return True

        # Check for subsystem exception
        if subsystem and subsystem in spec.exception_subsystems:
            return True

        if spec.direction_bias == "long_only":
            return d == "long"
        if spec.direction_bias == "short_only":
            return d == "short"
        # Should not reach here (guarded at load time), but fail closed
        return False


# ── Module-level default registry ──────────────────────────────────────────
#
# Lazily instantiated so importing this module doesn't touch the filesystem
# until a caller actually needs it. Tests that want isolation can build their
# own ``MarketRegistry(config_path=...)`` directly.

_default_registry: Optional[MarketRegistry] = None


def get_default_registry() -> MarketRegistry:
    """Return a lazily-loaded process-wide MarketRegistry instance."""
    global _default_registry
    if _default_registry is None:
        _default_registry = MarketRegistry()
    return _default_registry


def reset_default_registry() -> None:
    """Clear the cached default registry (for tests)."""
    global _default_registry
    _default_registry = None
