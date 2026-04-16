"""HeatmapIterator — sub-system 3 of the Oil Bot-Pattern Strategy.

Polls Hyperliquid l2Book + meta for configured oil instruments, clusters
liquidity into zones, and detects liquidation cascades from OI/funding deltas.

Read-only: never places trades. Safe in all tiers.
Kill switch: data/config/heatmap.json → enabled: false
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from daemon.context import Alert, TickContext
from engines.data.heatmap import (
    append_cascade,
    append_zones,
    cluster_l2_book,
    detect_cascade,
)

log = logging.getLogger("daemon.heatmap")

DEFAULT_CONFIG_PATH = "data/config/heatmap.json"
HL_INFO_URL = "https://api.hyperliquid.xyz/info"


def _coin_for_instrument(instrument: str) -> str:
    """Return the HL `coin` field for an instrument symbol.

    BRENTOIL trades on the xyz dex and needs the `xyz:` prefix; native perps
    do not. See CLAUDE.md "Coin name normalization" gotcha.
    """
    if instrument in ("BRENTOIL", "GOLD", "SILVER"):
        return f"xyz:{instrument}"
    return instrument


class HeatmapIterator:
    name = "heatmap"

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        http_post: Any = None,
    ):
        self._config_path = config_path
        self._config: dict = {}
        self._last_poll_mono: float = 0.0
        # instrument -> {"oi": float, "funding_bps": float, "ts": float}
        self._prev_state: dict[str, dict[str, float]] = {}
        # cascade dedupe by id
        self._alerted_cascade_ids: set[str] = set()
        # Injectable HTTP for tests
        self._http_post = http_post or self._default_post

    def on_start(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            log.info("HeatmapIterator disabled — no-op")
            return
        log.info(
            "HeatmapIterator started — instruments=%s poll_interval=%ds",
            self._config.get("instruments", []),
            self._config.get("poll_interval_s", 60),
        )

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            return

        now_mono = time.monotonic()
        interval = int(self._config.get("poll_interval_s", 60))
        if self._last_poll_mono != 0.0 and (now_mono - self._last_poll_mono) < interval:
            return
        self._last_poll_mono = now_mono

        instruments: list[str] = list(self._config.get("instruments", []))
        snapshot_at = datetime.now(tz=timezone.utc)

        for instrument in instruments:
            try:
                self._poll_instrument(instrument, snapshot_at, ctx)
            except Exception as e:  # noqa: BLE001 — daemon must keep ticking
                log.warning("heatmap: %s poll failed: %s", instrument, e)

    # ------------------------------------------------------------------
    # Per-instrument poll
    # ------------------------------------------------------------------

    def _poll_instrument(
        self, instrument: str, snapshot_at: datetime, ctx: TickContext
    ) -> None:
        coin = _coin_for_instrument(instrument)
        book = self._http_post({"type": "l2Book", "coin": coin})
        if not book or not isinstance(book, dict):
            log.debug("heatmap: empty l2Book for %s", instrument)
            return

        zones = cluster_l2_book(
            book,
            instrument=instrument,
            snapshot_at=snapshot_at,
            cluster_bps=float(self._config.get("cluster_bps", 8.0)),
            max_distance_bps=float(self._config.get("max_distance_bps", 200.0)),
            max_zones_per_side=int(self._config.get("max_zones_per_side", 5)),
            min_notional_usd=float(self._config.get("min_zone_notional_usd", 50_000)),
        )
        if zones:
            append_zones(self._config["zones_jsonl"], zones)

        # Cascade detection — needs OI + funding deltas
        oi, funding_bps = self._fetch_oi_funding(instrument, coin)
        if oi is None or funding_bps is None:
            return

        prev = self._prev_state.get(instrument)
        self._prev_state[instrument] = {
            "oi": oi,
            "funding_bps": funding_bps,
            "ts": time.time(),
        }
        if prev is None:
            return

        window_s = max(1, int(time.time() - prev["ts"]))
        cfg_window = int(self._config.get("cascade_window_s", 180))
        # Only run cascade math when the elapsed window is meaningful
        if window_s > cfg_window * 3:
            # Long gap: discard, treat current as new baseline
            return

        cascade = detect_cascade(
            instrument=instrument,
            detected_at=snapshot_at,
            prev_oi=prev["oi"],
            curr_oi=oi,
            prev_funding_bps=prev["funding_bps"],
            curr_funding_bps=funding_bps,
            window_s=window_s,
            oi_threshold_pct=float(self._config.get("cascade_oi_delta_pct", 1.5)),
            funding_threshold_bps=float(self._config.get("cascade_funding_jump_bps", 10.0)),
        )
        if cascade is None:
            return

        append_cascade(self._config["cascades_jsonl"], cascade)
        self._maybe_alert(cascade, ctx)

    # ------------------------------------------------------------------
    # OI + funding fetch
    # ------------------------------------------------------------------

    def _fetch_oi_funding(
        self, instrument: str, coin: str
    ) -> tuple[float | None, float | None]:
        """Pull open interest + funding rate from metaAndAssetCtxs.

        Handles both native (`metaAndAssetCtxs`) and xyz (`metaAndAssetCtxs`
        with `dex='xyz'`) clearinghouses. Returns (oi, funding_bps) or
        (None, None) on failure.
        """
        is_xyz = coin.startswith("xyz:")
        bare = coin.replace("xyz:", "")
        payload = {"type": "metaAndAssetCtxs"}
        if is_xyz:
            payload["dex"] = "xyz"
        data = self._http_post(payload)
        if not isinstance(data, list) or len(data) != 2:
            return (None, None)
        meta, ctxs = data[0], data[1]
        universe = meta.get("universe", []) if isinstance(meta, dict) else []

        # CLAUDE.md gotcha: xyz universe entries may carry the prefix; native
        # may not. Match against both forms.
        idx = None
        for i, u in enumerate(universe):
            name = u.get("name", "")
            if name == coin or name == bare or name.replace("xyz:", "") == bare:
                idx = i
                break
        if idx is None or idx >= len(ctxs):
            return (None, None)

        ctx_row = ctxs[idx] or {}
        try:
            oi = float(ctx_row.get("openInterest", 0) or 0)
        except (TypeError, ValueError):
            oi = 0.0
        try:
            funding = float(ctx_row.get("funding", 0) or 0)
        except (TypeError, ValueError):
            funding = 0.0
        # HL funding is hourly fractional (e.g. 0.0001 = 1bp). Convert to bps.
        funding_bps = funding * 10_000.0
        return (oi, funding_bps)

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def _maybe_alert(self, cascade, ctx: TickContext) -> None:
        if cascade.id in self._alerted_cascade_ids:
            return
        if cascade.severity < 3:
            return
        self._alerted_cascade_ids.add(cascade.id)
        ctx.alerts.append(Alert(
            severity="warning" if cascade.severity == 3 else "critical",
            source=self.name,
            message=(
                f"LIQUIDATION CASCADE {cascade.instrument} {cascade.side} "
                f"sev{cascade.severity} OI {cascade.oi_delta_pct:+.1f}% "
                f"funding {cascade.funding_jump_bps:+.1f}bps"
            ),
            data={
                "instrument": cascade.instrument,
                "side": cascade.side,
                "severity": cascade.severity,
                "oi_delta_pct": cascade.oi_delta_pct,
            },
        ))

    # ------------------------------------------------------------------
    # Config + HTTP
    # ------------------------------------------------------------------

    def _reload_config(self) -> None:
        try:
            self._config = json.loads(Path(self._config_path).read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.warning("heatmap config unavailable (%s)", e)
            self._config = {"enabled": False}

    @staticmethod
    def _default_post(payload: dict) -> Any:
        try:
            return requests.post(HL_INFO_URL, json=payload, timeout=10).json()
        except Exception:  # noqa: BLE001
            return {}
