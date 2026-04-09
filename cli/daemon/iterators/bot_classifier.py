"""BotPatternIterator — sub-system 4 of the Oil Bot-Pattern Strategy.

Periodically classifies recent moves on configured oil instruments as
bot-driven, informed, mixed, or unclear, by combining inputs from
sub-systems #1 (catalysts), #2 (supply state), and #3 (cascades) plus
candle data and basic ATR.

Read-only: never places trades. Heuristic-only — no ML, no LLM.
Kill switch: data/config/bot_classifier.json → enabled: false
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from cli.daemon.context import Alert, TickContext
from modules.bot_classifier import (
    append_pattern,
    classify_pattern,
)

log = logging.getLogger("daemon.bot_classifier")

DEFAULT_CONFIG_PATH = "data/config/bot_classifier.json"


def _coin_for_instrument(instrument: str) -> str:
    if instrument in ("BRENTOIL", "GOLD", "SILVER"):
        return f"xyz:{instrument}"
    return instrument


class BotPatternIterator:
    name = "bot_classifier"

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        candles_provider: Callable[[str, int, int], list[dict]] | None = None,
    ):
        self._config_path = config_path
        self._config: dict = {}
        self._last_poll_mono: float = 0.0
        self._candles_provider = candles_provider or self._default_candles_provider
        self._alerted_pattern_ids: set[str] = set()

    def on_start(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            log.info("BotPatternIterator disabled — no-op")
            return
        log.info(
            "BotPatternIterator started — instruments=%s poll_interval=%ds",
            self._config.get("instruments", []),
            self._config.get("poll_interval_s", 300),
        )

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            return

        now_mono = time.monotonic()
        interval = int(self._config.get("poll_interval_s", 300))
        if self._last_poll_mono != 0.0 and (now_mono - self._last_poll_mono) < interval:
            return
        self._last_poll_mono = now_mono

        detected_at = datetime.now(tz=timezone.utc)
        lookback_min = int(self._config.get("lookback_minutes", 60))

        # Pre-load shared inputs (catalysts + supply state) once per tick
        catalysts = self._load_recent_catalysts(detected_at)
        supply_state = self._load_supply_state()
        cascades = self._load_recent_cascades(detected_at)

        for instrument in self._config.get("instruments", []):
            try:
                self._classify_one(
                    instrument, detected_at, lookback_min,
                    cascades, catalysts, supply_state, ctx,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("bot_classifier: %s failed: %s", instrument, e)

    # ------------------------------------------------------------------
    # Per-instrument classification
    # ------------------------------------------------------------------

    def _classify_one(
        self,
        instrument: str,
        detected_at: datetime,
        lookback_min: int,
        all_cascades: list[dict],
        all_catalysts: list[dict],
        supply_state: dict | None,
        ctx: TickContext,
    ) -> None:
        # Filter cascades + catalysts to this instrument where possible
        inst_cascades = [c for c in all_cascades if c.get("instrument") == instrument]
        inst_catalysts = [
            c for c in all_catalysts
            if not c.get("instruments")  # global catalysts apply
            or any(self._instrument_matches(instrument, x) for x in c.get("instruments", []))
        ]

        coin = _coin_for_instrument(instrument)
        candles = self._candles_provider(coin, lookback_min, 60)
        if not candles:
            log.debug("bot_classifier: no candles for %s, skipping", instrument)
            return

        price_now = float(candles[-1]["c"])
        price_then = float(candles[0]["c"])
        if price_then <= 0:
            return
        price_change_pct = (price_now - price_then) / price_then * 100.0
        atr = self._atr(candles)

        pattern = classify_pattern(
            instrument=instrument,
            detected_at=detected_at,
            price_at_detection=price_now,
            price_change_pct=price_change_pct,
            atr=atr,
            recent_cascades=inst_cascades,
            recent_catalysts=inst_catalysts,
            supply_state=supply_state,
            cascade_window_min=int(self._config.get("cascade_window_min", 30)),
            catalyst_floor=int(self._config.get("catalyst_floor", 4)),
            supply_freshness_hours=int(self._config.get("supply_freshness_hours", 72)),
            atr_mult_for_big_move=float(self._config.get("atr_mult_for_big_move", 1.5)),
            lookback_minutes=lookback_min,
            min_price_move_pct=float(self._config.get("min_price_move_pct_for_classification", 0.5)),
        )

        append_pattern(self._config["patterns_jsonl"], pattern)
        self._maybe_alert(pattern, ctx)

    @staticmethod
    def _instrument_matches(instrument: str, raw: str) -> bool:
        if not raw:
            return False
        return raw == instrument or raw.replace("xyz:", "") == instrument

    @staticmethod
    def _atr(candles: list[dict]) -> float:
        """Simple ATR proxy: mean of (high - low) as % of close over window."""
        if not candles:
            return 0.0
        ranges = []
        for c in candles:
            try:
                hi = float(c["h"])
                lo = float(c["l"])
                cl = float(c["c"])
                if cl > 0:
                    ranges.append((hi - lo) / cl * 100.0)
            except (KeyError, TypeError, ValueError):
                continue
        if not ranges:
            return 0.0
        return sum(ranges) / len(ranges)

    # ------------------------------------------------------------------
    # Input loaders
    # ------------------------------------------------------------------

    def _load_recent_catalysts(self, detected_at: datetime) -> list[dict]:
        path = Path(self._config.get("catalysts_jsonl", "data/news/catalysts.jsonl"))
        if not path.exists():
            return []
        cutoff = detected_at - timedelta(hours=24)
        out: list[dict] = []
        try:
            with path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts_str = row.get("published_at") or row.get("scheduled_at")
                    if not ts_str:
                        continue
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
                    if ts < cutoff:
                        continue
                    out.append(row)
        except OSError:
            return []
        return out

    def _load_supply_state(self) -> dict | None:
        path = Path(self._config.get("supply_state_json", "data/supply/state.json"))
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def _load_recent_cascades(self, detected_at: datetime) -> list[dict]:
        path = Path(self._config.get("cascades_jsonl", "data/heatmap/cascades.jsonl"))
        if not path.exists():
            return []
        # Pull a generous window — the classifier filters with cascade_window_min
        cutoff = detected_at - timedelta(hours=4)
        out: list[dict] = []
        try:
            with path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts_str = row.get("detected_at")
                    if not ts_str:
                        continue
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
                    if ts < cutoff:
                        continue
                    out.append(row)
        except OSError:
            return []
        return out

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def _maybe_alert(self, pattern, ctx: TickContext) -> None:
        if pattern.id in self._alerted_pattern_ids:
            return
        # Only alert on high-confidence bot-driven overextensions — that's
        # the signal sub-system 5 will care about most.
        if pattern.classification != "bot_driven_overextension":
            return
        if pattern.confidence < 0.75:
            return
        self._alerted_pattern_ids.add(pattern.id)
        ctx.alerts.append(Alert(
            severity="info",
            source=self.name,
            message=(
                f"BOT PATTERN {pattern.instrument} {pattern.direction} "
                f"conf={pattern.confidence:.2f} "
                f"move={pattern.price_change_pct:+.2f}%"
            ),
            data={
                "instrument": pattern.instrument,
                "classification": pattern.classification,
                "confidence": pattern.confidence,
                "direction": pattern.direction,
            },
        ))

    # ------------------------------------------------------------------
    # Config + default candles provider
    # ------------------------------------------------------------------

    def _reload_config(self) -> None:
        try:
            self._config = json.loads(Path(self._config_path).read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.warning("bot_classifier config unavailable (%s)", e)
            self._config = {"enabled": False}

    @staticmethod
    def _default_candles_provider(coin: str, lookback_min: int, interval_s: int) -> list[dict]:
        """Pull 1m candles for the classifier window.

        2026-04-09: Cache was empty for 1m because market_structure_iter
        only caches 1h/4h/1d. The classifier's 300s poll interval is
        tolerant of a direct HL API fetch per poll. Fetch first, try
        cache as fallback.
        """
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - lookback_min * 60_000

        # Primary: direct HL public API fetch. Matches the endpoint used
        # by market_structure_iter._refresh_candles.
        try:
            import requests
            payload = {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin, "interval": "1m",
                    "startTime": start_ms, "endTime": now_ms,
                },
            }
            r = requests.post(
                "https://api.hyperliquid.xyz/info",
                json=payload, timeout=10,
            )
            if r.status_code == 200:
                candles = r.json()
                if isinstance(candles, list) and candles:
                    return candles
        except Exception as e:  # noqa: BLE001
            log.debug("bot_classifier: HL 1m fetch failed for %s: %s", coin, e)

        # Fallback: check the cache (will usually be empty until a
        # future wedge extends market_structure_iter to cache 1m).
        try:
            from modules.candle_cache import CandleCache
            cache = CandleCache()
            rows = cache.get_candles(coin, "1m", start_ms, now_ms)
            cache.close()
            return rows
        except Exception as e:  # noqa: BLE001
            log.debug("bot_classifier: cache fallback failed for %s: %s", coin, e)
            return []
