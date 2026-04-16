"""PortfolioRiskMonitorIterator — cumulative open-risk cap (alert-only).

Monitors the SUM of `(distance to SL) * size` across every open position
and compares it to total account equity. Per Chris's stated rule:

    "I don't want to lose more than 10% of my equity on any one trade
     ideally... but that's cumulative equity and needs to be calculated
     correctly."

This is the *portfolio-level* risk budget — distinct from per-position
risk (already enforced by liquidation_monitor + exchange_protection +
heartbeat compute_stop_price) and from the correlation/margin gates in
exchange/portfolio_risk.py (which count positions and margin %, not real
$ at risk).

The iterator is **alert-only by design**. The user explicitly asked for a
sparring partner, not a babysitter — "I don't want the robot stepping in
and overriding my positioning." Concretely:

    - 0%   - warn_pct  → silent
    - warn_pct - cap   → ONE warning alert (state-change dedup)
    - cap and beyond   → ONE critical alert + sets ctx.risk_gate to
                         COOLDOWN so the **entry-pre-flight** in risk.py
                         throttles NEW positions. Existing positions are
                         not touched.

SL discovery (best-effort, in priority order):
  1. Live exchange-side SL trigger orders for the position's instrument
  2. Estimated SL from heartbeat config (ATR-based) — TODO when wired
  3. Liquidation-distance fallback (worst case if SL is missing entirely)

Kill switch: `data/config/portfolio_risk_monitor.json` (`enabled: false`
by default — must be explicitly turned on).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from daemon.context import Alert, TickContext
from exchange.risk_manager import RiskGate

log = logging.getLogger("daemon.portfolio_risk_monitor")

ZERO = Decimal("0")

# Defaults — overridable via data/config/portfolio_risk_monitor.json.
DEFAULT_CONFIG_PATH = "data/config/portfolio_risk_monitor.json"
DEFAULT_CAP_PCT = Decimal("0.10")    # 10% of equity, per Chris's rule
DEFAULT_WARN_PCT = Decimal("0.08")   # 8% — warn before the throttle hits
DEFAULT_TICK_INTERVAL_S = 30
DEFAULT_ENABLED = False              # opt-in; ship OFF


@dataclass
class PortfolioRiskConfig:
    enabled: bool = DEFAULT_ENABLED
    cap_pct: Decimal = DEFAULT_CAP_PCT
    warn_pct: Decimal = DEFAULT_WARN_PCT
    tick_interval_s: int = DEFAULT_TICK_INTERVAL_S

    @classmethod
    def from_file(cls, path: str = DEFAULT_CONFIG_PATH) -> "PortfolioRiskConfig":
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            raw = json.loads(p.read_text())
            return cls(
                enabled=bool(raw.get("enabled", DEFAULT_ENABLED)),
                cap_pct=Decimal(str(raw.get("cap_pct", DEFAULT_CAP_PCT))),
                warn_pct=Decimal(str(raw.get("warn_pct", DEFAULT_WARN_PCT))),
                tick_interval_s=int(raw.get("tick_interval_s", DEFAULT_TICK_INTERVAL_S)),
            )
        except Exception as e:
            log.warning("PortfolioRiskMonitor config load failed: %s — using defaults", e)
            return cls()


@dataclass
class _PositionRisk:
    """Per-position risk attribution row (computed once per tick)."""
    instrument: str
    side: str                     # "long" or "short"
    qty: Decimal                  # absolute size
    entry: Decimal
    sl: Optional[Decimal]         # None → fell through to liq fallback
    sl_source: str                # "exchange" | "liquidation_fallback" | "none"
    risk_usd: Decimal             # |entry - sl| * qty


def _state_for(pct: Decimal, warn: Decimal, cap: Decimal) -> str:
    """Map cumulative risk fraction → alerting state."""
    if pct >= cap:
        return "critical"
    if pct >= warn:
        return "warning"
    return "safe"


class PortfolioRiskMonitorIterator:
    """Cumulative open-risk cap, alert-only, with optional entry throttle."""

    name = "portfolio_risk_monitor"

    def __init__(
        self,
        adapter: Any = None,
        config: Optional[PortfolioRiskConfig] = None,
    ):
        self._adapter = adapter
        self._cfg = config or PortfolioRiskConfig.from_file()
        self._last_tick: float = 0.0
        # State-change dedup — only re-alert when cumulative-risk state
        # transitions across a threshold, not every tick we stay over.
        self._last_state: str = "safe"
        # Cache of open trigger orders per tick (refreshed only when fetched).
        self._trigger_cache: Dict[str, List[Dict]] = {}

    def on_start(self, ctx: TickContext) -> None:
        log.info(
            "PortfolioRiskMonitor started — enabled=%s  cap=%.0f%%  warn=%.0f%%  interval=%ds",
            self._cfg.enabled,
            float(self._cfg.cap_pct) * 100,
            float(self._cfg.warn_pct) * 100,
            self._cfg.tick_interval_s,
        )

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        if not self._cfg.enabled:
            return

        now = time.monotonic()
        if now - self._last_tick < self._cfg.tick_interval_s:
            return
        self._last_tick = now

        equity = Decimal(str(ctx.total_equity or 0))
        if equity <= ZERO:
            # Equity not yet populated this session — nothing safe to compute.
            return

        positions = [p for p in ctx.positions if p.net_qty != ZERO]
        if not positions:
            self._maybe_clear(ctx)
            return

        # Refresh trigger-order cache once per tick.
        self._trigger_cache = self._fetch_triggers()

        rows = [self._row_for_position(p) for p in positions]
        cumulative_risk = sum((r.risk_usd for r in rows), ZERO)
        risk_pct = cumulative_risk / equity

        state = _state_for(risk_pct, self._cfg.warn_pct, self._cfg.cap_pct)

        # Throttle entries when over the cap. Existing positions untouched.
        # Per the user's "don't override my positioning" rule, this only
        # raises the gate; it never closes anything.
        if state == "critical":
            gate_severity = {RiskGate.OPEN: 0, RiskGate.COOLDOWN: 1, RiskGate.CLOSED: 2}
            if gate_severity.get(RiskGate.COOLDOWN, 0) > gate_severity.get(ctx.risk_gate, 0):
                ctx.risk_gate = RiskGate.COOLDOWN

        if state == self._last_state:
            return  # state-change dedup — no spam while we sit at the same level

        if state == "warning":
            ctx.alerts.append(Alert(
                severity="warning",
                source=self.name,
                message=self._format_alert(state, cumulative_risk, equity, risk_pct, rows),
                data={"risk_usd": str(cumulative_risk), "risk_pct": float(risk_pct)},
            ))
        elif state == "critical":
            ctx.alerts.append(Alert(
                severity="critical",
                source=self.name,
                message=self._format_alert(state, cumulative_risk, equity, risk_pct, rows),
                data={"risk_usd": str(cumulative_risk), "risk_pct": float(risk_pct)},
            ))
        elif state == "safe" and self._last_state != "safe":
            # Recovery from warn/critical → one info alert
            ctx.alerts.append(Alert(
                severity="info",
                source=self.name,
                message=(
                    f"*Portfolio risk recovered* — cumulative open risk "
                    f"${float(cumulative_risk):.2f} ({float(risk_pct) * 100:.1f}% of equity)"
                ),
            ))

        self._last_state = state

    # ── Internals ──────────────────────────────────────────────────────────

    def _maybe_clear(self, ctx: TickContext) -> None:
        if self._last_state != "safe":
            ctx.alerts.append(Alert(
                severity="info",
                source=self.name,
                message="*Portfolio risk recovered* — no open positions",
            ))
            self._last_state = "safe"

    def _fetch_triggers(self) -> Dict[str, List[Dict]]:
        """Pull open orders once and bucket trigger-stops by coin.

        Falls back to an empty cache on any failure — the per-position
        resolver then uses the liquidation fallback. Never raises.
        """
        if self._adapter is None:
            return {}
        try:
            orders = self._adapter.get_open_orders() or []
        except Exception as e:
            log.debug("get_open_orders failed in portfolio_risk_monitor: %s", e)
            return {}
        bucket: Dict[str, List[Dict]] = {}
        for o in orders:
            ot = o.get("orderType") or o.get("order_type") or {}
            trig = ot.get("trigger") if isinstance(ot, dict) else None
            if not trig or trig.get("tpsl") != "sl":
                continue
            coin = str(o.get("coin", ""))
            if not coin:
                continue
            bucket.setdefault(coin, []).append(o)
            # Match both stripped and prefixed forms — recurring xyz: bug.
            if coin.startswith("xyz:"):
                bucket.setdefault(coin.replace("xyz:", ""), []).append(o)
            else:
                bucket.setdefault(f"xyz:{coin}", []).append(o)
        return bucket

    def _row_for_position(self, pos: Any) -> _PositionRisk:
        """Compute a per-position risk row using the best SL we can find."""
        inst = pos.instrument
        qty = abs(pos.net_qty)
        entry = pos.avg_entry_price
        is_long = pos.net_qty > ZERO
        side = "long" if is_long else "short"
        liq = pos.liquidation_price or ZERO

        sl, sl_source = self._resolve_sl(inst, is_long, entry, liq)
        if sl is None:
            risk_usd = ZERO
        else:
            risk_usd = abs(entry - sl) * qty

        return _PositionRisk(
            instrument=inst,
            side=side,
            qty=qty,
            entry=entry,
            sl=sl,
            sl_source=sl_source,
            risk_usd=risk_usd,
        )

    def _resolve_sl(
        self,
        inst: str,
        is_long: bool,
        entry: Decimal,
        liq: Decimal,
    ) -> Tuple[Optional[Decimal], str]:
        """Return (sl_price, source). Source is 'exchange' or 'liquidation_fallback'."""
        triggers = self._trigger_cache.get(inst, [])
        # Pick the SAFEST SL among open triggers — closest to entry on the
        # right side. For longs that's max(SL); for shorts min(SL).
        best: Optional[Decimal] = None
        for o in triggers:
            ot = o.get("orderType") or o.get("order_type") or {}
            trig = ot.get("trigger") if isinstance(ot, dict) else None
            if not trig:
                continue
            try:
                sl_price = Decimal(str(trig.get("triggerPx", 0)))
            except Exception:
                continue
            if sl_price <= ZERO:
                continue
            if is_long and sl_price >= entry:
                continue  # not a real stop
            if not is_long and sl_price <= entry:
                continue
            if best is None:
                best = sl_price
            elif is_long and sl_price > best:
                best = sl_price
            elif not is_long and sl_price < best:
                best = sl_price
        if best is not None:
            return best, "exchange"

        # Fallback: assume worst case is the liquidation price (no SL = full loss).
        if liq > ZERO:
            return liq, "liquidation_fallback"
        return None, "none"

    @staticmethod
    def _format_alert(
        state: str,
        risk_usd: Decimal,
        equity: Decimal,
        risk_pct: Decimal,
        rows: List[_PositionRisk],
    ) -> str:
        header = (
            "*Portfolio risk WARNING*"
            if state == "warning"
            else "*Portfolio risk CAP REACHED — new entries throttled*"
        )
        lines = [
            header,
            f"  Cumulative open risk: ${float(risk_usd):,.2f} "
            f"({float(risk_pct) * 100:.1f}% of ${float(equity):,.2f} equity)",
        ]
        # Per-position breakdown (top contributors first)
        ranked = sorted(rows, key=lambda r: -float(r.risk_usd))
        for r in ranked[:5]:
            sl_str = f"{float(r.sl):.4f}" if r.sl is not None else "—"
            src = "" if r.sl_source == "exchange" else f" ({r.sl_source})"
            lines.append(
                f"  - {r.instrument} {r.side} qty={float(r.qty):.4f} "
                f"entry={float(r.entry):.4f} sl={sl_str}{src} "
                f"risk=${float(r.risk_usd):,.2f}"
            )
        return "\n".join(lines)
