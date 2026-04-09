"""BotPatternStrategyIterator — sub-system 5 of the Oil Bot-Pattern Strategy.

THE ONLY PLACE in the codebase where shorting BRENTOIL/CL is legal.
Behind a chain of hard gates plus two master kill switches.

Reads outputs of sub-systems 1-4 + existing thesis + funding tracker
from disk, runs the gate chain, computes conviction sizing, and emits
OrderIntents tagged strategy_name="oil_botpattern" with
intended_hold_hours in meta. Coexists with the existing thesis_engine
path per OIL_BOT_PATTERN_SYSTEM.md §5.

Every position immediately enters the existing exchange_protection
SL+TP chain via preferred_*_atr_mult in the OrderIntent meta.

Kill switches:
- data/config/oil_botpattern.json → enabled: false  (whole iterator)
- data/config/oil_botpattern.json → short_legs_enabled: false  (shorts only)

Registered in REBALANCE + OPPORTUNISTIC tiers only. NOT in WATCH.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from cli.daemon.context import Alert, OrderIntent, TickContext
from modules.oil_botpattern import (
    Decision,
    GateResult,
    StrategyState,
    append_decision,
    check_drawdown_brakes,
    compute_edge,
    compute_recent_outcome_bias,
    gate_classification_ok,
    gate_no_blocking_catalyst,
    gate_no_fresh_supply_upgrade,
    gate_short_daily_loss_cap,
    gate_short_grace_period,
    gate_thesis_conflict,
    gate_results_to_dicts,
    make_decision_id,
    maybe_reset_daily_window,
    maybe_reset_monthly_window,
    maybe_reset_weekly_window,
    read_state,
    short_should_force_close,
    should_exit_on_funding,
    size_from_edge,
    sizing_to_dict,
    write_state_atomic,
)
from modules.oil_botpattern_paper import (
    ShadowBalance,
    ShadowPosition,
    balance_from_dict,
    balance_to_dict,
    check_exit as paper_check_exit,
    close_shadow_position,
    new_balance,
    open_shadow_position,
    position_from_dict,
    position_to_dict,
    trade_to_dict,
    unrealized_pnl,
    update_balance_on_close,
)
from modules.oil_botpattern_adaptive import (
    AdaptiveAction,
    AdaptiveConfig,
    MarketSnapshot,
    PositionHypothesis,
    build_log_entry,
    config_from_dict as adaptive_config_from_dict,
    evaluate as adaptive_evaluate,
    should_log as adaptive_should_log,
)

log = logging.getLogger("daemon.oil_botpattern")

DEFAULT_CONFIG_PATH = "data/config/oil_botpattern.json"

# Coin name normalization (CLAUDE.md gotcha)
def _coin_for_instrument(instrument: str) -> str:
    if instrument in ("BRENTOIL", "GOLD", "SILVER"):
        return f"xyz:{instrument}"
    return instrument


def _instrument_matches(inst: str, raw: str) -> bool:
    if not raw:
        return False
    return raw == inst or raw.replace("xyz:", "") == inst


class BotPatternStrategyIterator:
    name = "oil_botpattern"

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
    ):
        self._config_path = config_path
        self._config: dict = {}
        self._risk_caps: dict = {}
        self._last_poll_mono: float = 0.0
        # Track when we last saw a thesis conflict per instrument for lockout
        self._last_conflict_at: dict[str, datetime] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_start(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            log.info("BotPatternStrategyIterator disabled — no-op")
            return
        state = self._load_state()
        if not state.enabled_since:
            state.enabled_since = datetime.now(tz=timezone.utc).isoformat()
            write_state_atomic(self._config["state_json"], state)
        log.info(
            "BotPatternStrategyIterator started — instruments=%s short_legs=%s",
            self._config.get("instruments", []),
            self._config.get("short_legs_enabled", False),
        )

    def on_stop(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            return

        now_mono = time.monotonic()
        interval = int(self._config.get("tick_interval_s", 60))
        if self._last_poll_mono != 0.0 and (now_mono - self._last_poll_mono) < interval:
            return
        self._last_poll_mono = now_mono

        now = datetime.now(tz=timezone.utc)
        state = self._load_state()

        # Window rollovers + seed enabled_since if missing
        maybe_reset_daily_window(state, now)
        maybe_reset_weekly_window(state, now)
        maybe_reset_monthly_window(state, now)
        if not state.enabled_since:
            state.enabled_since = now.isoformat()

        equity = self._equity_from_ctx(ctx)

        # Drawdown brakes — if tripped, we still manage existing positions
        # (honor stops/TPs via exchange_protection) but we DO NOT open new ones
        brakes_blocked, brake_reason = check_drawdown_brakes(
            state, equity,
            float(self._config["drawdown_brakes"]["daily_max_loss_pct"]),
            float(self._config["drawdown_brakes"]["weekly_max_loss_pct"]),
            float(self._config["drawdown_brakes"]["monthly_max_loss_pct"]),
        )

        # Pre-load shared inputs once per tick
        patterns_by_inst = self._load_latest_patterns_by_instrument()
        catalysts_24h = self._load_upcoming_catalysts(now)
        supply_state = self._load_supply_state()
        thesis_state = self._load_thesis_state()
        recent_trades = self._load_recent_oil_botpattern_trades()
        outcome_bias = compute_recent_outcome_bias(recent_trades)
        funding_map = self._load_funding_by_instrument()

        shadow_mode = bool(self._config.get("decisions_only", False))

        # Step 1: manage existing positions (exit triggers, hold caps)
        for instrument in list(state.open_positions.keys()):
            try:
                self._manage_existing(instrument, state, ctx, now, funding_map, equity)
            except Exception as e:  # noqa: BLE001
                log.warning("oil_botpattern: manage %s failed: %s", instrument, e)

        # Step 1b: manage shadow (paper) positions independently from live state.
        # Shadow mode persists positions across tick regardless of the current
        # decisions_only flag — this way, flipping shadow mode off doesn't orphan
        # open paper positions; they continue to be marked and can be closed out
        # on their own stops / tps.
        try:
            self._manage_shadow_positions(ctx, now)
        except Exception as e:  # noqa: BLE001
            log.warning("oil_botpattern: manage shadow failed: %s", e)

        # Step 2: evaluate each instrument for new entries
        if not brakes_blocked:
            for instrument in self._config.get("instruments", []):
                try:
                    self._evaluate_entry(
                        instrument, state, ctx, now, equity,
                        patterns_by_inst, catalysts_24h, supply_state,
                        thesis_state, outcome_bias,
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("oil_botpattern: evaluate %s failed: %s", instrument, e)
        else:
            log.info("oil_botpattern: new entries blocked — %s", brake_reason)

        # Persist state at end of tick
        write_state_atomic(self._config["state_json"], state)

    # ------------------------------------------------------------------
    # Existing-position management
    # ------------------------------------------------------------------

    def _manage_existing(
        self,
        instrument: str,
        state: StrategyState,
        ctx: TickContext,
        now: datetime,
        funding_map: dict[str, float],
        equity: float,
    ) -> None:
        pos = state.open_positions.get(instrument)
        if not pos:
            return

        # Update cumulative funding from funding_tracker
        funding_usd = funding_map.get(instrument, pos.get("cumulative_funding_usd", 0.0))
        pos["cumulative_funding_usd"] = funding_usd
        notional = float(pos.get("size", 0.0)) * float(pos.get("entry_price", 0.0))

        # Short-leg hard cap: 24h
        if pos.get("side") == "short":
            cap = int(self._config.get("short_max_hold_hours", 24))
            should_close, reason = short_should_force_close(
                pos.get("entry_ts", ""), now, cap,
            )
            if should_close:
                self._emit_close(instrument, pos, ctx, reason)
                return

        # Long-leg funding-cost exit
        if pos.get("side") == "long":
            action, reason = should_exit_on_funding(
                funding_usd, notional,
                float(self._config.get("funding_warn_pct", 0.5)),
                float(self._config.get("funding_exit_pct", 1.5)),
            )
            if action == "warn":
                ctx.alerts.append(Alert(
                    severity="warning", source=self.name,
                    message=f"oil_botpattern {instrument} long: {reason}",
                    data={"instrument": instrument, "action": "warn"},
                ))
            elif action == "exit":
                self._emit_close(instrument, pos, ctx, reason)
                return

        # Adaptive live evaluation — test the hypothesis each tick.
        # v1: EXIT-only for live positions (tighten_stop / trail require
        # exchange-side stop modification, deferred to a future wedge
        # that integrates with exchange_protection).
        if pos.get("entry_classification"):
            try:
                self._evaluate_live_adaptive(instrument, pos, ctx, now)
            except Exception as e:  # noqa: BLE001
                log.warning("oil_botpattern: live adaptive eval failed for %s: %s", instrument, e)

        # Protection audit: if protection_audit has flagged this position
        # as unprotected, force-close immediately. Read from ctx.alerts
        # if present; simpler: let exchange_protection do its job and
        # exit-on-failure lives in a future wedge.

    def _evaluate_live_adaptive(
        self,
        instrument: str,
        pos: dict,
        ctx: TickContext,
        now: datetime,
    ) -> None:
        """Run the adaptive evaluator against a LIVE position record.

        Emits a close OrderIntent on EXIT. Tighten/trail are logged + alerted
        but the exchange-side stop is NOT modified — that's a future wedge.
        """
        current_price = self._current_price(instrument, ctx)
        if current_price <= 0:
            return

        entry_price = float(pos.get("entry_price", 0.0) or 0.0)
        expected_reach = float(pos.get("expected_reach_price", 0.0) or 0.0)
        if expected_reach <= 0 and entry_price > 0:
            pct = float(self._config.get("adaptive_live_expected_reach_pct", 5.0))
            if pos.get("side") == "long":
                expected_reach = entry_price * (1.0 + pct / 100.0)
            else:
                expected_reach = entry_price * (1.0 - pct / 100.0)

        hypothesis = PositionHypothesis(
            instrument=instrument,
            side=str(pos.get("side", "long")),
            entry_ts=str(pos.get("entry_ts", "")),
            entry_price=entry_price,
            expected_reach_price=expected_reach,
            expected_reach_hours=float(
                pos.get("expected_reach_hours")
                or self._config.get("adaptive_expected_reach_hours", 48.0)
            ),
            entry_classification=str(pos.get("entry_classification", "")),
            entry_confidence=float(pos.get("entry_confidence", 0.0) or 0.0),
            entry_pattern_direction=str(pos.get("entry_pattern_direction", "")),
        )

        cfg = adaptive_config_from_dict(self._config.get("adaptive", {}))
        catalysts = self._load_upcoming_catalysts_for_adaptive(now)
        supply = self._load_supply_state()
        patterns = self._load_latest_patterns_by_instrument()
        latest_pattern = (
            patterns.get(instrument) or patterns.get(f"xyz:{instrument}")
        )
        snapshot = MarketSnapshot(
            current_price=current_price,
            latest_pattern=latest_pattern,
            recent_catalysts=catalysts,
            supply_state=supply,
            now=now,
        )
        decision = adaptive_evaluate(
            hypothesis, snapshot, cfg,
            current_stop_price=None,  # live stops are exchange-side, not in this record
        )
        self._log_live_adaptive_decision(hypothesis, snapshot, decision, pos, now)

        if decision.action == AdaptiveAction.EXIT:
            reason = f"adaptive: {decision.reason}"
            self._emit_close(instrument, pos, ctx, reason)
            ctx.alerts.append(Alert(
                severity="warning", source=self.name,
                message=(
                    f"🛑 LIVE ADAPTIVE EXIT {instrument} {pos.get('side', '?').upper()} "
                    f"@ {current_price:,.2f} — {decision.reason}"
                ),
                data={
                    "instrument": instrument,
                    "adaptive_action": "exit",
                    "reason": decision.reason,
                    "price_progress": decision.price_progress,
                    "time_progress": decision.time_progress,
                    "velocity_ratio": decision.velocity_ratio,
                },
            ))
            return

        if decision.action in (
            AdaptiveAction.TIGHTEN_STOP,
            AdaptiveAction.TRAIL_BREAKEVEN,
        ):
            # v1: log + alert only. Stop modification lives in a future
            # wedge that integrates with exchange_protection.
            ctx.alerts.append(Alert(
                severity="info", source=self.name,
                message=(
                    f"🔒 LIVE ADAPTIVE {decision.action.value.upper()} "
                    f"{instrument} {pos.get('side', '?').upper()} — "
                    f"suggests stop at {decision.new_stop_price:,.2f} "
                    f"({decision.reason}). Manual action required."
                ),
                data={
                    "instrument": instrument,
                    "adaptive_action": decision.action.value,
                    "suggested_stop": decision.new_stop_price,
                    "reason": decision.reason,
                    "price_progress": decision.price_progress,
                },
            ))

    def _log_live_adaptive_decision(
        self,
        hypothesis: PositionHypothesis,
        snapshot: MarketSnapshot,
        decision,
        pos: dict,
        now: datetime,
    ) -> None:
        """Persist a live-mode adaptive decision to the append-only log."""
        last_hb_str = pos.get("adaptive_last_heartbeat_ts")
        last_hb: datetime | None = None
        if last_hb_str:
            try:
                last_hb = datetime.fromisoformat(last_hb_str)
                if last_hb.tzinfo is None:
                    last_hb = last_hb.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                last_hb = None

        hb_minutes = float(self._config.get("adaptive_heartbeat_minutes", 15.0))
        if not adaptive_should_log(
            decision, last_heartbeat_at=last_hb, now=now,
            heartbeat_interval_minutes=hb_minutes,
        ):
            return

        entry = build_log_entry(hypothesis, snapshot, decision, now)
        # Tag live vs shadow so downstream consumers can filter
        entry["mode"] = "live"
        path = self._adaptive_log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
            pos["adaptive_last_heartbeat_ts"] = now.isoformat()
        except OSError as e:
            log.warning("oil_botpattern: failed to append live adaptive log: %s", e)

    def _emit_close(
        self,
        instrument: str,
        pos: dict,
        ctx: TickContext,
        reason: str,
    ) -> None:
        size = Decimal(str(abs(float(pos.get("size", 0.0)))))
        ctx.order_queue.append(OrderIntent(
            strategy_name=self.name,
            instrument=instrument,
            action="close",
            size=size,
            reduce_only=True,
            meta={
                "reason": reason,
                "strategy_id": "oil_botpattern",
                "intended_hold_hours": 0,
            },
        ))
        ctx.alerts.append(Alert(
            severity="info", source=self.name,
            message=f"oil_botpattern closing {instrument} {pos.get('side')}: {reason}",
            data={"instrument": instrument, "reason": reason},
        ))

    # ------------------------------------------------------------------
    # Entry evaluation
    # ------------------------------------------------------------------

    def _evaluate_entry(
        self,
        instrument: str,
        state: StrategyState,
        ctx: TickContext,
        now: datetime,
        equity: float,
        patterns_by_inst: dict[str, dict],
        catalysts_24h: list[dict],
        supply_state: dict | None,
        thesis_state: dict | None,
        outcome_bias: float,
    ) -> None:
        # If already in a position, do not stack in v1 (no averaging-in yet)
        if instrument in state.open_positions:
            return

        latest_pattern = patterns_by_inst.get(instrument)
        if latest_pattern is None:
            return  # silently — no decision record either; nothing to evaluate

        pat_dir = latest_pattern.get("direction", "flat")
        cls = latest_pattern.get("classification", "unclear")
        conf = float(latest_pattern.get("confidence", 0.0))

        # Determine proposed direction
        if pat_dir == "up":
            direction = "long"
        elif pat_dir == "down":
            direction = "short"
        else:
            return

        # Short-leg master kill switch
        if direction == "short" and not self._config.get("short_legs_enabled", False):
            return

        # Compute edge
        thesis_conv = float((thesis_state or {}).get("conviction", 0.0))
        thesis_dir = (thesis_state or {}).get("direction", "flat").lower()
        thesis_matches = (direction == "long" and thesis_dir == "long")
        edge = compute_edge(conf, thesis_conv, thesis_matches, outcome_bias)

        # Gate chain
        gates: list[GateResult] = []
        gates.append(gate_classification_ok(
            direction, latest_pattern,
            float(self._config.get("long_min_edge", 0.5)),
            float(self._config.get("short_min_edge", 0.7)),
        ))
        gates.append(gate_thesis_conflict(
            direction, thesis_state, instrument,
            self._last_conflict_at.get(instrument), now,
        ))
        if direction == "short":
            gates.append(gate_short_grace_period(
                state,
                int(self._config.get("short_legs_grace_period_s", 3600)),
                now,
            ))
            gates.append(gate_no_blocking_catalyst(
                catalysts_24h,
                int(self._config.get("short_blocking_catalyst_severity", 4)),
                direction,
            ))
            gates.append(gate_no_fresh_supply_upgrade(
                supply_state,
                int(self._config.get("short_blocking_supply_freshness_hours", 72)),
                direction, now,
            ))
            gates.append(gate_short_daily_loss_cap(
                state, equity,
                float(self._config.get("short_daily_loss_cap_pct", 1.5)),
            ))

        all_passed = all(g.passed for g in gates)

        # Record thesis conflict timestamp if tripped
        for g in gates:
            if g.name == "thesis_conflict" and not g.passed:
                self._last_conflict_at[instrument] = now

        # Sizing (even if gates failed — journal records the intended size)
        caps = (self._risk_caps.get("oil_botpattern", {}) or {}).get(instrument, {})
        sizing_mult = float(caps.get("sizing_multiplier", 1.0))
        price = float(ctx.prices.get(instrument, 0.0) or ctx.prices.get(_coin_for_instrument(instrument), 0.0))
        sizing = size_from_edge(
            edge,
            self._config.get("sizing_ladder", []),
            sizing_mult, equity, price,
        )

        action = "open" if (all_passed and sizing.rung >= 0) else "skip"

        # Journal the decision regardless
        decision = Decision(
            id=make_decision_id(instrument, now),
            instrument=instrument,
            decided_at=now,
            direction=direction,
            action=action,
            edge=edge,
            classification=cls,
            classifier_confidence=conf,
            thesis_conviction=thesis_conv,
            recent_outcome_bias=outcome_bias,
            sizing=sizing_to_dict(sizing),
            gate_results=gate_results_to_dicts(gates),
            notes=f"{direction} — {'passed' if all_passed else 'gated'}",
        )
        append_decision(self._config["decision_journal_jsonl"], decision)

        if action != "open":
            return

        # Shadow / decisions-only mode: open a paper position and emit a
        # Telegram notice instead of a real OrderIntent. The iterator never
        # contacts the exchange in this mode.
        if self._config.get("decisions_only", False):
            self._open_shadow(
                instrument=instrument,
                direction=direction,
                entry_price=price,
                sizing=sizing,
                edge=edge,
                ctx=ctx,
                now=now,
                entry_classification=cls,
                entry_confidence=conf,
                entry_pattern_direction=pat_dir,
            )
            # Also update the live-state record so that /oilbot keeps showing
            # a "current intent" for operator eyes. This does NOT cause any
            # live trade — the OrderIntent path is skipped above.
            state.open_positions[instrument] = {
                "side": direction,
                "entry_ts": now.isoformat(),
                "entry_price": price,
                "size": float(sizing.target_size),
                "leverage": float(sizing.leverage),
                "cumulative_funding_usd": 0.0,
                "realised_pnl_today_usd": 0.0,
                "shadow": True,
            }
            return

        # Emit the entry OrderIntent
        order_action = "buy" if direction == "long" else "sell"
        preferred_sl = float(self._config.get("preferred_sl_atr_mult", 0.8))
        preferred_tp = float(self._config.get("preferred_tp_atr_mult", 2.0))
        ctx.order_queue.append(OrderIntent(
            strategy_name=self.name,
            instrument=instrument,
            action=order_action,
            size=Decimal(str(round(sizing.target_size, 4))),
            meta={
                "strategy_id": "oil_botpattern",
                "intended_hold_hours": int(self._config.get("intended_hold_hours_default", 12)),
                "edge": edge,
                "rung": sizing.rung,
                "base_pct": sizing.base_pct,
                "leverage": sizing.leverage,
                "preferred_sl_atr_mult": preferred_sl,
                "preferred_tp_atr_mult": preferred_tp,
                "classifier_confidence": conf,
                "thesis_conviction": thesis_conv,
            },
        ))

        # Update state: open position record (optimistic — exchange_protection
        # will attach stops when the fill lands). Hypothesis fields are
        # captured here so the adaptive evaluator can test the thesis
        # every tick for live positions the same way it does for shadow.
        live_expected_reach_pct = float(
            self._config.get("adaptive_live_expected_reach_pct", 5.0)
        )
        if direction == "long":
            expected_reach_price = price * (1.0 + live_expected_reach_pct / 100.0)
        else:
            expected_reach_price = price * (1.0 - live_expected_reach_pct / 100.0)
        state.open_positions[instrument] = {
            "side": direction,
            "entry_ts": now.isoformat(),
            "entry_price": price,
            "size": float(sizing.target_size),
            "leverage": float(sizing.leverage),
            "cumulative_funding_usd": 0.0,
            "realised_pnl_today_usd": 0.0,
            "entry_classification": cls,
            "entry_confidence": conf,
            "entry_pattern_direction": pat_dir,
            "expected_reach_price": expected_reach_price,
            "expected_reach_hours": float(
                self._config.get("adaptive_expected_reach_hours", 48.0)
            ),
            "adaptive_last_heartbeat_ts": None,
        }

        # Warning alert on every short-leg open (visible in Telegram)
        sev = "warning" if direction == "short" else "info"
        ctx.alerts.append(Alert(
            severity=sev, source=self.name,
            message=(
                f"oil_botpattern {direction.upper()} {instrument} edge={edge:.2f} "
                f"rung={sizing.rung} lev={sizing.leverage}x notional=${sizing.target_notional_usd:,.0f}"
            ),
            data={
                "instrument": instrument,
                "direction": direction,
                "edge": edge,
                "notional_usd": sizing.target_notional_usd,
            },
        ))

    # ------------------------------------------------------------------
    # Config + state + input loaders
    # ------------------------------------------------------------------

    def _reload_config(self) -> None:
        try:
            self._config = json.loads(Path(self._config_path).read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.warning("oil_botpattern config unavailable (%s)", e)
            self._config = {"enabled": False}
            return
        try:
            caps_path = self._config.get("risk_caps_json", "data/config/risk_caps.json")
            self._risk_caps = json.loads(Path(caps_path).read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self._risk_caps = {}

    def _load_state(self) -> StrategyState:
        return read_state(self._config.get("state_json", "data/strategy/oil_botpattern_state.json"))

    def _equity_from_ctx(self, ctx: TickContext) -> float:
        try:
            total = 0.0
            for bal in ctx.balances.values():
                total += float(bal)
            return total
        except Exception:  # noqa: BLE001
            return 0.0

    def _load_latest_patterns_by_instrument(self) -> dict[str, dict]:
        path = Path(self._config.get("patterns_jsonl", "data/research/bot_patterns.jsonl"))
        if not path.exists():
            return {}
        latest: dict[str, dict] = {}
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
                    inst = row.get("instrument")
                    if not inst:
                        continue
                    prev = latest.get(inst)
                    if prev is None or row.get("detected_at", "") > prev.get("detected_at", ""):
                        latest[inst] = row
        except OSError:
            return {}
        return latest

    def _load_upcoming_catalysts(self, now: datetime) -> list[dict]:
        path = Path(self._config.get("catalysts_jsonl", "data/news/catalysts.jsonl"))
        if not path.exists():
            return []
        cutoff_hi = now + timedelta(hours=24)
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
                    ts_str = row.get("scheduled_at") or row.get("published_at")
                    if not ts_str:
                        continue
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
                    if now <= ts <= cutoff_hi:
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

    def _load_thesis_state(self) -> dict | None:
        path = Path(self._config.get("thesis_state_path", "data/thesis/xyz_brentoil_state.json"))
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def _load_recent_oil_botpattern_trades(self) -> list[dict]:
        """Last 5 closed oil_botpattern trades from main journal.jsonl."""
        path = Path(self._config.get("main_journal_jsonl", "data/research/journal.jsonl"))
        if not path.exists():
            return []
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
                    if row.get("strategy_id") == "oil_botpattern" and row.get("status") == "closed":
                        out.append(row)
        except OSError:
            return []
        return out[-5:]

    def _load_funding_by_instrument(self) -> dict[str, float]:
        """Map instrument → cumulative_funding_usd from funding_tracker.jsonl."""
        path = Path(self._config.get("funding_tracker_jsonl", "data/daemon/funding_tracker.jsonl"))
        if not path.exists():
            return {}
        latest: dict[str, float] = {}
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
                    inst = row.get("instrument")
                    if not inst:
                        continue
                    try:
                        latest[inst] = float(row.get("cumulative_usd", 0.0))
                    except (TypeError, ValueError):
                        continue
        except OSError:
            return {}
        return latest

    # ------------------------------------------------------------------
    # Shadow / paper mode (decisions_only=true)
    # ------------------------------------------------------------------

    def _shadow_positions_path(self) -> Path:
        return Path(self._config.get(
            "shadow_positions_json",
            "data/strategy/oil_botpattern_shadow_positions.json",
        ))

    def _shadow_trades_path(self) -> Path:
        return Path(self._config.get(
            "shadow_trades_jsonl",
            "data/strategy/oil_botpattern_shadow_trades.jsonl",
        ))

    def _shadow_balance_path(self) -> Path:
        return Path(self._config.get(
            "shadow_balance_json",
            "data/strategy/oil_botpattern_shadow_balance.json",
        ))

    def _load_shadow_positions(self) -> list[ShadowPosition]:
        path = self._shadow_positions_path()
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return []
        rows = data.get("positions", []) if isinstance(data, dict) else []
        return [position_from_dict(r) for r in rows]

    def _save_shadow_positions(self, positions: list[ShadowPosition]) -> None:
        path = self._shadow_positions_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        import os
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(
            {"positions": [position_to_dict(p) for p in positions]},
            indent=2,
        ))
        os.replace(tmp, path)

    def _load_shadow_balance(self) -> ShadowBalance:
        path = self._shadow_balance_path()
        seed = float(self._config.get("shadow_seed_balance_usd", 100_000.0))
        if not path.exists():
            return new_balance(seed)
        try:
            return balance_from_dict(json.loads(path.read_text()), default_seed=seed)
        except (OSError, json.JSONDecodeError):
            return new_balance(seed)

    def _save_shadow_balance(self, balance: ShadowBalance) -> None:
        path = self._shadow_balance_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        import os
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(balance_to_dict(balance), indent=2, sort_keys=True))
        os.replace(tmp, path)

    def _append_shadow_trade(self, trade) -> None:
        path = self._shadow_trades_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(trade_to_dict(trade)) + "\n")

    def _open_shadow(
        self,
        instrument: str,
        direction: str,
        entry_price: float,
        sizing,
        edge: float,
        ctx: TickContext,
        now: datetime,
        entry_classification: str = "",
        entry_confidence: float = 0.0,
        entry_pattern_direction: str = "",
    ) -> None:
        """Open a new paper position and emit a Telegram notice.

        No exchange contact — pure simulation + state + alert. The
        classification / confidence / direction at entry are captured
        on the position so the adaptive evaluator can test the
        thesis on subsequent ticks.
        """
        if entry_price <= 0 or sizing.target_size <= 0:
            return

        positions = self._load_shadow_positions()
        # v1: no stacking — skip if an open position for the same instrument exists
        for p in positions:
            if p.instrument == instrument:
                return

        sl_pct = float(self._config.get("shadow_sl_pct", 2.0))
        tp_pct = float(self._config.get("shadow_tp_pct", 5.0))
        expected_reach_hours = float(
            self._config.get("adaptive_expected_reach_hours", 48.0)
        )
        new_pos = open_shadow_position(
            instrument=instrument,
            side=direction,
            entry_price=entry_price,
            size=float(sizing.target_size),
            leverage=float(sizing.leverage),
            sl_pct=sl_pct,
            tp_pct=tp_pct,
            edge=edge,
            rung=int(sizing.rung),
            now=now,
            entry_classification=entry_classification,
            entry_confidence=entry_confidence,
            entry_pattern_direction=entry_pattern_direction,
            expected_reach_hours=expected_reach_hours,
        )
        positions.append(new_pos)
        try:
            self._save_shadow_positions(positions)
        except OSError as e:
            log.warning("oil_botpattern: failed to save shadow positions: %s", e)
            return

        balance = self._load_shadow_balance()
        ctx.alerts.append(Alert(
            severity="info", source=self.name,
            message=(
                f"🟡 SHADOW OPEN {direction.upper()} {instrument} @ "
                f"{entry_price:,.2f} size={new_pos.size:,.4f} "
                f"lev={new_pos.leverage}x notional=${new_pos.notional_usd:,.0f} "
                f"sl={new_pos.stop_price:,.2f} tp={new_pos.tp_price:,.2f} "
                f"edge={edge:.2f} | balance: ${balance.current_balance_usd:,.0f} "
                f"({balance.pnl_pct:+.2f}%)"
            ),
            data={
                "shadow": True,
                "instrument": instrument,
                "direction": direction,
                "entry_price": entry_price,
                "size": new_pos.size,
                "leverage": new_pos.leverage,
                "notional_usd": new_pos.notional_usd,
                "stop_price": new_pos.stop_price,
                "tp_price": new_pos.tp_price,
                "edge": edge,
                "balance_usd": balance.current_balance_usd,
            },
        ))

    def _current_price(self, instrument: str, ctx: TickContext) -> float:
        """Pull the best available mark price for an instrument.

        Priority: ctx.prices (live, set by ConnectorIterator) → latest
        bot_patterns.jsonl row → 0 (no exit decision possible).
        """
        price = 0.0
        try:
            raw = ctx.prices.get(instrument) if ctx and getattr(ctx, "prices", None) else None
            if raw is not None:
                price = float(raw)
        except (TypeError, ValueError):
            price = 0.0
        if price > 0:
            return price
        # Fallback: latest classifier detection price
        try:
            patterns = self._load_latest_patterns_by_instrument()
            row = patterns.get(instrument) or patterns.get(f"xyz:{instrument}")
            if row is not None:
                price = float(row.get("price_at_detection", 0.0) or 0.0)
        except Exception:  # noqa: BLE001
            price = 0.0
        return max(0.0, price)

    def _manage_shadow_positions(self, ctx: TickContext, now: datetime) -> None:
        """Mark open shadow positions to market and close on SL/TP hits.

        Runs regardless of decisions_only state — ensures existing paper
        positions continue to be watched even if mode is flipped off.

        Also runs the ADAPTIVE evaluator (modules.oil_botpattern_adaptive)
        on every tick, which tests the entry hypothesis against current
        market state and may:
          - EXIT early (thesis invalidated, adverse catalyst, stale, classifier drift)
          - SCALE_OUT at target
          - TIGHTEN_STOP or TRAIL_BREAKEVEN to lock in profit

        Every non-HOLD decision (and throttled HOLD heartbeats) is
        persisted to data/strategy/oil_botpattern_adaptive_log.jsonl
        as a flat, pre-featurized row for retrospective review + future
        ML / rule-tuning pipelines.
        """
        positions = self._load_shadow_positions()
        if not positions:
            return

        remaining: list[ShadowPosition] = []
        closed_any = False
        balance = self._load_shadow_balance()
        adaptive_cfg = adaptive_config_from_dict(self._config.get("adaptive", {}))
        adaptive_catalysts = self._load_upcoming_catalysts_for_adaptive(now)
        adaptive_supply = self._load_supply_state()
        adaptive_patterns = self._load_latest_patterns_by_instrument()

        for pos in positions:
            price = self._current_price(pos.instrument, ctx)
            if price <= 0:
                # Can't mark — keep the position as-is
                remaining.append(pos)
                continue

            pos.unrealized_pnl_usd = unrealized_pnl(pos, price)
            pos.last_mark_ts = now.isoformat()
            pos.last_mark_price = price

            # ------------------------------------------------------------
            # Adaptive evaluation — test the thesis against current state
            # ------------------------------------------------------------
            adaptive_decision = None
            if pos.entry_classification:  # only evaluate positions with captured hypothesis
                try:
                    hypothesis = PositionHypothesis(
                        instrument=pos.instrument,
                        side=pos.side,
                        entry_ts=pos.entry_ts,
                        entry_price=pos.entry_price,
                        expected_reach_price=pos.tp_price,
                        expected_reach_hours=pos.expected_reach_hours or float(
                            self._config.get("adaptive_expected_reach_hours", 48.0)
                        ),
                        entry_classification=pos.entry_classification,
                        entry_confidence=pos.entry_confidence,
                        entry_pattern_direction=pos.entry_pattern_direction,
                    )
                    latest_pattern = (
                        adaptive_patterns.get(pos.instrument)
                        or adaptive_patterns.get(f"xyz:{pos.instrument}")
                    )
                    snapshot = MarketSnapshot(
                        current_price=price,
                        latest_pattern=latest_pattern,
                        recent_catalysts=adaptive_catalysts,
                        supply_state=adaptive_supply,
                        now=now,
                    )
                    adaptive_decision = adaptive_evaluate(
                        hypothesis, snapshot, adaptive_cfg,
                        current_stop_price=pos.stop_price,
                    )
                    self._log_adaptive_decision(hypothesis, snapshot, adaptive_decision, pos, now)
                    # Apply the adaptive action
                    if adaptive_decision.action == AdaptiveAction.EXIT:
                        # Force an early exit at current mark price
                        trade = close_shadow_position(pos, price, "adaptive_exit", now)
                        try:
                            self._append_shadow_trade(trade)
                            balance = update_balance_on_close(balance, trade, now)
                            closed_any = True
                            self._emit_adaptive_close_alert(
                                ctx, pos, trade, balance,
                                reason_label="ADAPTIVE EXIT",
                                reason=adaptive_decision.reason,
                            )
                        except OSError as e:
                            log.warning("oil_botpattern: adaptive exit write failed: %s", e)
                            remaining.append(pos)
                        continue
                    if adaptive_decision.action == AdaptiveAction.SCALE_OUT and not pos.scaled_out:
                        # v1: close the full position at the scale-out price,
                        # mark as a "scale_out" exit. Partial closes are a
                        # future wedge.
                        trade = close_shadow_position(pos, price, "scale_out", now)
                        try:
                            self._append_shadow_trade(trade)
                            balance = update_balance_on_close(balance, trade, now)
                            closed_any = True
                            self._emit_adaptive_close_alert(
                                ctx, pos, trade, balance,
                                reason_label="ADAPTIVE SCALE-OUT",
                                reason=adaptive_decision.reason,
                            )
                        except OSError as e:
                            log.warning("oil_botpattern: scale-out write failed: %s", e)
                            remaining.append(pos)
                        continue
                    if adaptive_decision.action in (
                        AdaptiveAction.TIGHTEN_STOP,
                        AdaptiveAction.TRAIL_BREAKEVEN,
                    ) and adaptive_decision.new_stop_price is not None:
                        old_stop = pos.stop_price
                        pos.stop_price = adaptive_decision.new_stop_price
                        ctx.alerts.append(Alert(
                            severity="info", source=self.name,
                            message=(
                                f"🔒 SHADOW {adaptive_decision.action.value.upper()} "
                                f"{pos.instrument} {pos.side.upper()} — "
                                f"stop {old_stop:,.2f} → {pos.stop_price:,.2f} "
                                f"({adaptive_decision.reason})"
                            ),
                            data={
                                "shadow": True,
                                "instrument": pos.instrument,
                                "adaptive_action": adaptive_decision.action.value,
                                "old_stop": old_stop,
                                "new_stop": pos.stop_price,
                                "reason": adaptive_decision.reason,
                                "price_progress": adaptive_decision.price_progress,
                                "velocity_ratio": adaptive_decision.velocity_ratio,
                            },
                        ))
                except Exception as e:  # noqa: BLE001
                    log.warning("oil_botpattern: adaptive evaluation failed for %s: %s", pos.instrument, e)

            exit_reason, exit_price = paper_check_exit(pos, price)
            if exit_reason is None:
                remaining.append(pos)
                continue

            trade = close_shadow_position(pos, exit_price, exit_reason, now)
            try:
                self._append_shadow_trade(trade)
            except OSError as e:
                log.warning("oil_botpattern: failed to append shadow trade: %s", e)
                # Keep the position alive; we'll retry on the next tick
                remaining.append(pos)
                continue

            balance = update_balance_on_close(balance, trade, now)
            closed_any = True

            emoji = "🟢" if trade.realised_pnl_usd > 0 else "🔴"
            reason_label = {
                "tp_hit": "TP",
                "sl_hit": "SL",
                "manual": "manual",
                "mode_change": "mode change",
            }.get(exit_reason, exit_reason.upper())
            ctx.alerts.append(Alert(
                severity="info" if trade.realised_pnl_usd > 0 else "warning",
                source=self.name,
                message=(
                    f"{emoji} SHADOW {reason_label} {pos.instrument} "
                    f"{pos.side.upper()} @ {exit_price:,.2f} "
                    f"{'+$' if trade.realised_pnl_usd >= 0 else '-$'}"
                    f"{abs(trade.realised_pnl_usd):,.0f} "
                    f"({trade.roe_pct:+.2f}% ROE) hold {trade.hold_hours:.1f}h | "
                    f"balance: ${balance.current_balance_usd:,.0f} "
                    f"({balance.pnl_pct:+.2f}%) | "
                    f"{balance.closed_trades} trades, "
                    f"WR {balance.win_rate:.0%}"
                ),
                data={
                    "shadow": True,
                    "instrument": pos.instrument,
                    "side": pos.side,
                    "exit_reason": exit_reason,
                    "exit_price": exit_price,
                    "realised_pnl_usd": trade.realised_pnl_usd,
                    "roe_pct": trade.roe_pct,
                    "balance_usd": balance.current_balance_usd,
                    "closed_trades": balance.closed_trades,
                },
            ))

        # Persist whatever remains + balance
        if closed_any or any(p.last_mark_ts is not None for p in remaining):
            try:
                self._save_shadow_positions(remaining)
            except OSError as e:
                log.warning("oil_botpattern: failed to save shadow positions: %s", e)

        if closed_any:
            try:
                self._save_shadow_balance(balance)
            except OSError as e:
                log.warning("oil_botpattern: failed to save shadow balance: %s", e)

    # ------------------------------------------------------------------
    # Adaptive evaluator helpers
    # ------------------------------------------------------------------

    def _load_upcoming_catalysts_for_adaptive(self, now: datetime) -> list[dict]:
        """Load catalysts visible in the adaptive window — wider than the
        24h entry-gate window so we can see adverse events that appeared
        shortly after entry."""
        path = Path(self._config.get("catalysts_jsonl", "data/news/catalysts.jsonl"))
        if not path.exists():
            return []
        # 72h backward / 24h forward covers the 'appeared since entry' case
        cutoff_low = now - timedelta(hours=72)
        cutoff_hi = now + timedelta(hours=24)
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
                    ts_str = (
                        row.get("published_at")
                        or row.get("scheduled_at")
                        or row.get("created_at")
                    )
                    if not ts_str:
                        continue
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
                    if cutoff_low <= ts <= cutoff_hi:
                        out.append(row)
        except OSError:
            return []
        return out

    def _adaptive_log_path(self) -> Path:
        return Path(self._config.get(
            "adaptive_log_jsonl",
            "data/strategy/oil_botpattern_adaptive_log.jsonl",
        ))

    def _log_adaptive_decision(
        self,
        hypothesis: PositionHypothesis,
        snapshot: MarketSnapshot,
        decision,
        pos: ShadowPosition,
        now: datetime,
    ) -> None:
        """Persist an AdaptiveDecision to the append-only training log.

        Non-HOLD decisions are always logged. HOLD decisions are
        throttled to one heartbeat per position per
        `adaptive_heartbeat_minutes` (default 15m) — enough temporal
        coverage for retrospective review without exploding log volume.
        """
        last_hb: datetime | None = None
        if pos.adaptive_last_heartbeat_ts:
            try:
                last_hb = datetime.fromisoformat(pos.adaptive_last_heartbeat_ts)
                if last_hb.tzinfo is None:
                    last_hb = last_hb.replace(tzinfo=timezone.utc)
            except ValueError:
                last_hb = None

        hb_minutes = float(self._config.get("adaptive_heartbeat_minutes", 15.0))
        if not adaptive_should_log(
            decision, last_heartbeat_at=last_hb, now=now,
            heartbeat_interval_minutes=hb_minutes,
        ):
            return

        entry = build_log_entry(hypothesis, snapshot, decision, now)
        entry["mode"] = "shadow"
        path = self._adaptive_log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
            pos.adaptive_last_heartbeat_ts = now.isoformat()
        except OSError as e:
            log.warning("oil_botpattern: failed to append adaptive log: %s", e)

    def _emit_adaptive_close_alert(
        self,
        ctx: TickContext,
        pos: ShadowPosition,
        trade,
        balance: ShadowBalance,
        reason_label: str,
        reason: str,
    ) -> None:
        emoji = "🎯" if trade.realised_pnl_usd > 0 else "🛑"
        ctx.alerts.append(Alert(
            severity="info" if trade.realised_pnl_usd > 0 else "warning",
            source=self.name,
            message=(
                f"{emoji} SHADOW {reason_label} {pos.instrument} "
                f"{pos.side.upper()} @ {trade.exit_price:,.2f} "
                f"{'+$' if trade.realised_pnl_usd >= 0 else '-$'}"
                f"{abs(trade.realised_pnl_usd):,.0f} "
                f"({trade.roe_pct:+.2f}% ROE) hold {trade.hold_hours:.1f}h | "
                f"reason: {reason} | "
                f"balance: ${balance.current_balance_usd:,.0f} "
                f"({balance.pnl_pct:+.2f}%) | "
                f"{balance.closed_trades} trades, WR {balance.win_rate:.0%}"
            ),
            data={
                "shadow": True,
                "adaptive": True,
                "instrument": pos.instrument,
                "side": pos.side,
                "exit_reason": trade.exit_reason,
                "exit_price": trade.exit_price,
                "realised_pnl_usd": trade.realised_pnl_usd,
                "roe_pct": trade.roe_pct,
                "reason": reason,
                "balance_usd": balance.current_balance_usd,
                "closed_trades": balance.closed_trades,
            },
        ))
