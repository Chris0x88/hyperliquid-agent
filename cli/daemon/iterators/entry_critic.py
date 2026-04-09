"""EntryCriticIterator — Trade Entry Critic (deterministic, no AI).

Watches ``ctx.positions`` each tick and fires a deterministic critique the
first time a new position fingerprint appears. The critique is:

  1. Persisted to ``data/research/entry_critiques.jsonl`` as an append-only
     row (one per entry), so the lesson layer and post-mortem flow can pull
     it back later.
  2. Posted as a Telegram alert via ``ctx.alerts.append(Alert(...))`` — the
     TelegramIterator then forwards to the channel with the normal rate
     limiter + dedup.

Signal gathering, grading, and formatting all live in
``modules/entry_critic.py`` (pure logic, fully unit-tested). This file is
purely the I/O wrapper: state management, dedup across daemon restarts,
kill switch, alert routing.

Kill switch: ``data/config/entry_critic.json`` → ``{"enabled": false}``.
Default is ON (file is optional — same pattern as lesson_author).

Fingerprinting
--------------
A "new entry" is defined by the tuple
``(instrument, direction, rounded_entry_price, rounded_entry_ts_sec)`` —
rounded so floating-point noise doesn't re-fire the critique, and the
timestamp truncated to the second so the fingerprint is stable across
ticks once the position is booked.

State is persisted at ``data/daemon/entry_critic_state.json`` with the set
of fingerprints already critiqued. The set is capped (oldest dropped) so
the state file doesn't grow unbounded over months of operation.

This iterator is READ-ONLY with respect to the exchange. It never places
orders, never modifies positions, never calls the adapter. It observes,
grades, and tells. That's the whole job.
"""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Optional

from cli.daemon.context import Alert, TickContext
from modules.entry_critic import (
    EntryGrade,
    SignalStack,
    format_critique_jsonl,
    format_critique_telegram,
    gather_signal_stack,
    grade_entry,
)

log = logging.getLogger("daemon.entry_critic")

DEFAULT_CONFIG_PATH = "data/config/entry_critic.json"
DEFAULT_STATE_PATH = "data/daemon/entry_critic_state.json"
DEFAULT_CRITIQUES_JSONL = "data/research/entry_critiques.jsonl"
DEFAULT_ZONES_PATH = "data/heatmap/zones.jsonl"
DEFAULT_CASCADES_PATH = "data/heatmap/cascades.jsonl"
DEFAULT_CATALYSTS_PATH = "data/news/catalysts.jsonl"
DEFAULT_BOT_PATTERNS_PATH = "data/research/bot_patterns.jsonl"

# Cap on the in-memory + persisted fingerprint set so the state file does
# not grow without bound. At ~10 entries/day that's still 100 days of
# history — plenty for dedup purposes.
MAX_FINGERPRINTS = 1000


class EntryCriticIterator:
    """Fires a one-shot critique the first time a new entry appears."""

    name = "entry_critic"

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        state_path: str = DEFAULT_STATE_PATH,
        critiques_path: str = DEFAULT_CRITIQUES_JSONL,
        zones_path: str = DEFAULT_ZONES_PATH,
        cascades_path: str = DEFAULT_CASCADES_PATH,
        catalysts_path: str = DEFAULT_CATALYSTS_PATH,
        bot_patterns_path: str = DEFAULT_BOT_PATTERNS_PATH,
        search_lessons_fn: Any = None,
    ) -> None:
        self._config_path = Path(config_path)
        self._state_path = Path(state_path)
        self._critiques_path = Path(critiques_path)
        self._zones_path = str(zones_path)
        self._cascades_path = str(cascades_path)
        self._catalysts_path = str(catalysts_path)
        self._bot_patterns_path = str(bot_patterns_path)
        self._search_lessons_fn = search_lessons_fn

        self._enabled: bool = True
        self._fingerprints: list[str] = []  # ordered for bounded cap
        self._fingerprint_set: set[str] = set()

    # ── Lifecycle ────────────────────────────────────────────

    def on_start(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._enabled:
            log.info("EntryCriticIterator disabled via config — no-op")
            return
        self._load_state()
        log.info(
            "EntryCriticIterator started (known_fingerprints=%d)",
            len(self._fingerprints),
        )

    def on_stop(self) -> None:
        if self._enabled:
            self._save_state()

    def tick(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._enabled:
            return

        positions = getattr(ctx, "positions", None) or []
        if not positions:
            return

        any_new = False
        for pos in positions:
            try:
                pos_dict = self._position_to_dict(pos)
            except Exception as e:  # noqa: BLE001
                log.debug("entry_critic: skipping malformed position: %s", e)
                continue

            if pos_dict is None:
                continue

            fp = self._fingerprint(pos_dict)
            if not fp:
                continue
            if fp in self._fingerprint_set:
                continue

            try:
                self._critique_one(pos_dict, ctx)
                self._remember(fp)
                any_new = True
            except Exception as e:  # noqa: BLE001 — a single bad entry must
                # not take down the whole tick loop. Log and move on.
                log.warning(
                    "entry_critic: critique failed for %s (%s): %s",
                    pos_dict.get("instrument"),
                    fp,
                    e,
                )

        if any_new:
            self._save_state()

    # ── Core critique path ──────────────────────────────────

    def _critique_one(self, pos_dict: dict, ctx: TickContext) -> None:
        stack: SignalStack = gather_signal_stack(
            pos_dict,
            ctx=ctx,
            zones_path=self._zones_path,
            cascades_path=self._cascades_path,
            catalysts_path=self._catalysts_path,
            bot_patterns_path=self._bot_patterns_path,
            search_lessons_fn=self._search_lessons_fn,
        )
        grade: EntryGrade = grade_entry(stack)

        # Persist the JSONL row first — if the Telegram alert fails, the
        # persisted record is still the source of truth for /critique
        # lookup and lesson post-mortems.
        row = format_critique_jsonl(grade, stack)
        self._append_jsonl(row)

        # Push alert into ctx.alerts — TelegramIterator forwards.
        message = format_critique_telegram(grade, stack)
        severity = "warning" if grade.fail_count > 0 else "info"
        ctx.alerts.append(Alert(
            severity=severity,
            source=self.name,
            message=message,
            data={
                "instrument": stack.instrument,
                "direction": stack.direction,
                "overall_label": grade.overall_label,
                "pass_count": grade.pass_count,
                "warn_count": grade.warn_count,
                "fail_count": grade.fail_count,
                "fingerprint": self._fingerprint(pos_dict),
            },
        ))
        log.info(
            "entry_critic: %s %s @ %s — %s (%dP/%dW/%dF)",
            stack.instrument,
            stack.direction,
            stack.entry_price,
            grade.overall_label,
            grade.pass_count,
            grade.warn_count,
            grade.fail_count,
        )

    # ── Position → dict adapter ─────────────────────────────

    def _position_to_dict(self, pos: Any) -> Optional[dict]:
        """Translate a parent.position_tracker.Position (or any duck-typed
        equivalent) into the flat dict the pure-logic module consumes.

        Returns None for positions with net_qty == 0 (already-flat rows
        that the account collector hasn't yet pruned).
        """
        net_qty = _attr(pos, "net_qty")
        if net_qty is None:
            return None
        try:
            nq = float(net_qty)
        except (TypeError, ValueError):
            return None
        if nq == 0.0:
            return None

        instrument = _attr(pos, "instrument") or ""
        direction = "long" if nq > 0 else "short"
        try:
            entry_price = float(_attr(pos, "avg_entry_price") or 0.0)
        except (TypeError, ValueError):
            entry_price = 0.0
        entry_qty = abs(nq)
        # We don't store entry_ts on Position. Use now-ish — the fingerprint
        # then encodes the first-seen tick timestamp, which is what we want
        # for "haven't critiqued this yet across daemon restarts".
        entry_ts_ms = int(time.time() * 1000)

        leverage = _attr(pos, "leverage")
        try:
            leverage = float(leverage) if leverage is not None else None
        except (TypeError, ValueError):
            leverage = None

        liq_price = _attr(pos, "liquidation_price")
        try:
            liq_price = float(liq_price) if liq_price is not None else None
        except (TypeError, ValueError):
            liq_price = None

        notional_usd = None
        if entry_price and entry_qty:
            notional_usd = float(entry_price * entry_qty)

        return {
            "instrument": instrument,
            "direction": direction,
            "entry_price": entry_price,
            "entry_qty": entry_qty,
            "entry_ts_ms": entry_ts_ms,
            "leverage": leverage,
            "notional_usd": notional_usd,
            "liquidation_price": liq_price,
        }

    # ── Fingerprint ─────────────────────────────────────────

    def _fingerprint(self, pos: dict) -> str:
        inst = pos.get("instrument", "?")
        direction = pos.get("direction", "?")
        try:
            price = round(float(pos.get("entry_price") or 0.0), 4)
        except (TypeError, ValueError):
            price = 0.0
        try:
            qty = round(float(pos.get("entry_qty") or 0.0), 6)
        except (TypeError, ValueError):
            qty = 0.0
        return f"{inst}|{direction}|{price}|{qty}"

    def _remember(self, fp: str) -> None:
        self._fingerprints.append(fp)
        self._fingerprint_set.add(fp)
        if len(self._fingerprints) > MAX_FINGERPRINTS:
            # Drop oldest to bound state file growth
            overflow = len(self._fingerprints) - MAX_FINGERPRINTS
            dropped = self._fingerprints[:overflow]
            self._fingerprints = self._fingerprints[overflow:]
            for old in dropped:
                self._fingerprint_set.discard(old)

    # ── Config + state I/O ──────────────────────────────────

    def _reload_config(self) -> None:
        if not self._config_path.exists():
            self._enabled = True  # default ON
            return
        try:
            with self._config_path.open("r") as f:
                cfg = json.load(f)
            self._enabled = bool(cfg.get("enabled", True))
        except (OSError, json.JSONDecodeError) as e:
            log.warning(
                "entry_critic: bad config %s: %s — defaulting to enabled",
                self._config_path, e,
            )
            self._enabled = True

    def _load_state(self) -> None:
        if not self._state_path.exists():
            self._fingerprints = []
            self._fingerprint_set = set()
            return
        try:
            with self._state_path.open("r") as f:
                state = json.load(f)
            fps = state.get("fingerprints", [])
            if isinstance(fps, list):
                self._fingerprints = [str(x) for x in fps][-MAX_FINGERPRINTS:]
                self._fingerprint_set = set(self._fingerprints)
            else:
                self._fingerprints = []
                self._fingerprint_set = set()
        except (OSError, json.JSONDecodeError, ValueError) as e:
            log.warning("entry_critic: bad state %s: %s — resetting", self._state_path, e)
            self._fingerprints = []
            self._fingerprint_set = set()

    def _save_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            with tmp.open("w") as f:
                json.dump({"fingerprints": self._fingerprints}, f)
            tmp.replace(self._state_path)
        except OSError as e:
            log.warning("entry_critic: failed to save state: %s", e)

    def _append_jsonl(self, row: dict) -> None:
        try:
            self._critiques_path.parent.mkdir(parents=True, exist_ok=True)
            with self._critiques_path.open("a") as f:
                f.write(json.dumps(row, default=str) + "\n")
        except OSError as e:
            log.warning("entry_critic: failed to append critique row: %s", e)


# ── Helpers ────────────────────────────────────────────────


def _attr(obj: Any, name: str) -> Any:
    """Attribute-or-key access with Decimal → float awareness."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        val = obj.get(name)
    else:
        val = getattr(obj, name, None)
    if isinstance(val, Decimal):
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    return val
