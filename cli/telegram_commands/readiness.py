"""/readiness — preflight checklist for activating sub-system 5.

Runs a battery of green/yellow/red checks against the data files and
config that sub-system 5 depends on. Deterministic — reads state files,
no AI.

The command answers one question: "is it safe to flip the master kill
switch RIGHT NOW?" — by checking everything sub-system 5 will
immediately try to consume.

Checks:
- Catalyst feed freshness (data/news/catalysts.jsonl)
- Supply ledger freshness (data/supply/state.json)
- Heatmap population (data/heatmap/zones.jsonl)
- Bot classifier activity (data/research/bot_patterns.jsonl)
- Thesis file freshness (data/thesis/xyz_brentoil_state.json)
- Risk caps configured (data/config/risk_caps.json)
- Drawdown brake state (data/strategy/oil_botpattern_state.json)
- Master kill-switch status (data/config/oil_botpattern.json)

Each check returns a symbol + one-line verdict. Overall verdict at the
bottom: 🟢 GO, 🟡 PROCEED WITH CAUTION, or 🔴 DO NOT ACTIVATE.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# Paths are module-level constants so tests can patch them.
CATALYSTS_JSONL = "data/news/catalysts.jsonl"
SUPPLY_STATE_JSON = "data/supply/state.json"
HEATMAP_ZONES_JSONL = "data/heatmap/zones.jsonl"
BOT_PATTERNS_JSONL = "data/research/bot_patterns.jsonl"
BRENTOIL_THESIS_JSON = "data/thesis/xyz_brentoil_state.json"
RISK_CAPS_JSON = "data/config/risk_caps.json"
OIL_BOTPATTERN_CONFIG_JSON = "data/config/oil_botpattern.json"
OIL_BOTPATTERN_STATE_JSON = "data/strategy/oil_botpattern_state.json"


# Thresholds (in hours)
FRESH_CATALYSTS_H = 12
FRESH_SUPPLY_H = 24
FRESH_HEATMAP_H = 6
FRESH_BOT_PATTERNS_H = 24
FRESH_THESIS_H = 72


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _latest_jsonl_ts(path: str, ts_field: str = "detected_at") -> datetime | None:
    """Return the newest timestamp across all rows of a JSONL file.

    Tries `ts_field` first, then a small set of common fallbacks so
    the call site can stay schema-agnostic. Heatmap zones use
    `snapshot_at`, catalyst rows use `published_at`/`scheduled_at`,
    bot_patterns use `detected_at`, misc rows use `created_at` — all
    get picked up.
    """
    p = Path(path)
    if not p.exists():
        return None
    latest: datetime | None = None
    fallback_fields = (
        "snapshot_at",
        "detected_at",
        "scheduled_at",
        "published_at",
        "created_at",
    )
    try:
        with p.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_str = row.get(ts_field)
                if not ts_str:
                    for fb in fallback_fields:
                        if fb == ts_field:
                            continue
                        ts_str = row.get(fb)
                        if ts_str:
                            break
                ts = _parse_iso(ts_str)
                if ts is None:
                    continue
                if latest is None or ts > latest:
                    latest = ts
    except OSError:
        return None
    return latest


def _age_hours(ts: datetime | None, now: datetime) -> float | None:
    if ts is None:
        return None
    return (now - ts).total_seconds() / 3600.0


def _read_json(path: str) -> Any:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Individual checks — each returns (symbol, name, verdict_line, severity)
# severity: "green" | "yellow" | "red"
# ---------------------------------------------------------------------------

def check_catalyst_feed(now: datetime) -> tuple[str, str, str, str]:
    latest = _latest_jsonl_ts(CATALYSTS_JSONL, ts_field="published_at")
    age = _age_hours(latest, now)
    if age is None:
        return ("🔴", "Catalyst feed", "no data", "red")
    if age <= FRESH_CATALYSTS_H:
        return ("🟢", "Catalyst feed", f"fresh ({age:.1f}h old)", "green")
    if age <= FRESH_CATALYSTS_H * 2:
        return ("🟡", "Catalyst feed", f"stale ({age:.1f}h old)", "yellow")
    return ("🔴", "Catalyst feed", f"very stale ({age:.1f}h old)", "red")


def check_supply_ledger(now: datetime) -> tuple[str, str, str, str]:
    state = _read_json(SUPPLY_STATE_JSON)
    if not isinstance(state, dict):
        return ("🔴", "Supply ledger", "no state file", "red")
    ts = _parse_iso(state.get("computed_at"))
    age = _age_hours(ts, now)
    active = int(state.get("active_disruption_count", 0) or 0)
    if age is None:
        return ("🔴", "Supply ledger", "no computed_at", "red")
    if age <= FRESH_SUPPLY_H:
        return (
            "🟢", "Supply ledger",
            f"fresh ({age:.1f}h, {active} active disruption(s))",
            "green",
        )
    if age <= FRESH_SUPPLY_H * 2:
        return (
            "🟡", "Supply ledger",
            f"stale ({age:.1f}h, {active} active)",
            "yellow",
        )
    return ("🔴", "Supply ledger", f"very stale ({age:.1f}h)", "red")


def check_heatmap(now: datetime) -> tuple[str, str, str, str]:
    # Heatmap rows use `snapshot_at`, not `detected_at`. _latest_jsonl_ts
    # falls through to other common timestamp fields anyway, but being
    # explicit keeps the intent clear.
    latest = _latest_jsonl_ts(HEATMAP_ZONES_JSONL, ts_field="snapshot_at")
    age = _age_hours(latest, now)
    if age is None:
        return ("🔴", "Liquidity heatmap", "no zones data", "red")
    if age <= FRESH_HEATMAP_H:
        return ("🟢", "Liquidity heatmap", f"fresh ({age:.1f}h)", "green")
    if age <= FRESH_HEATMAP_H * 2:
        return ("🟡", "Liquidity heatmap", f"stale ({age:.1f}h)", "yellow")
    return ("🔴", "Liquidity heatmap", f"very stale ({age:.1f}h)", "red")


def check_bot_classifier(now: datetime) -> tuple[str, str, str, str]:
    latest = _latest_jsonl_ts(BOT_PATTERNS_JSONL, ts_field="detected_at")
    age = _age_hours(latest, now)
    if age is None:
        return (
            "🔴", "Bot classifier",
            "no classifications yet — #4 not producing",
            "red",
        )
    if age <= FRESH_BOT_PATTERNS_H:
        return ("🟢", "Bot classifier", f"active ({age:.1f}h)", "green")
    if age <= FRESH_BOT_PATTERNS_H * 2:
        return ("🟡", "Bot classifier", f"quiet ({age:.1f}h)", "yellow")
    return ("🔴", "Bot classifier", f"silent ({age:.1f}h)", "red")


def check_thesis(now: datetime) -> tuple[str, str, str, str]:
    state = _read_json(BRENTOIL_THESIS_JSON)
    if not isinstance(state, dict):
        return ("🟡", "BRENTOIL thesis", "no thesis file (optional)", "yellow")
    ts = _parse_iso(
        state.get("updated_at")
        or state.get("last_updated")
        or state.get("timestamp")
    )
    # Fallback: thesis files written by the AI agent use `last_evaluation_ts`
    # as a Unix millisecond epoch. Parse that format too.
    if ts is None:
        last_eval = state.get("last_evaluation_ts")
        if isinstance(last_eval, (int, float)):
            try:
                # Heuristic: > 1e12 = milliseconds, < 1e12 = seconds
                epoch = float(last_eval)
                if epoch > 1e12:
                    epoch = epoch / 1000.0
                from datetime import datetime as _dt
                ts = _dt.fromtimestamp(epoch, tz=timezone.utc)
            except (OSError, OverflowError, ValueError):
                ts = None
    age = _age_hours(ts, now)
    conviction = state.get("conviction", state.get("score"))
    if age is None:
        return ("🟡", "BRENTOIL thesis", "no timestamp", "yellow")
    if age <= FRESH_THESIS_H:
        return (
            "🟢", "BRENTOIL thesis",
            f"current ({age:.1f}h, conviction={conviction})",
            "green",
        )
    if age <= FRESH_THESIS_H * 2:
        return (
            "🟡", "BRENTOIL thesis",
            f"aging ({age:.1f}h, conviction={conviction})",
            "yellow",
        )
    return ("🔴", "BRENTOIL thesis", f"stale ({age:.1f}h — clamped)", "red")


def check_risk_caps() -> tuple[str, str, str, str]:
    caps = _read_json(RISK_CAPS_JSON)
    if not isinstance(caps, dict):
        return ("🔴", "Risk caps", "no config file", "red")
    bot_caps = caps.get("oil_botpattern") or {}
    if not bot_caps:
        return ("🔴", "Risk caps", "no oil_botpattern section", "red")
    if not isinstance(bot_caps, dict) or not bot_caps:
        return ("🔴", "Risk caps", "empty oil_botpattern section", "red")
    instruments = sorted(bot_caps.keys())
    return (
        "🟢", "Risk caps",
        f"configured for {', '.join(instruments)}",
        "green",
    )


def check_drawdown_brakes() -> tuple[str, str, str, str]:
    state = _read_json(OIL_BOTPATTERN_STATE_JSON)
    if not isinstance(state, dict):
        return ("🟢", "Drawdown brakes", "clean (no state yet)", "green")
    tripped = []
    if state.get("daily_brake_tripped_at"):
        tripped.append("daily")
    if state.get("weekly_brake_tripped_at"):
        tripped.append("weekly")
    if state.get("monthly_brake_tripped_at"):
        tripped.append("monthly")
    cleared = state.get("brake_cleared_at")
    if tripped and not cleared:
        return (
            "🔴", "Drawdown brakes",
            f"TRIPPED: {', '.join(tripped)} — MANUAL CLEAR REQUIRED",
            "red",
        )
    if tripped and cleared:
        return (
            "🟡", "Drawdown brakes",
            f"recently tripped ({', '.join(tripped)}) — manually cleared",
            "yellow",
        )
    return ("🟢", "Drawdown brakes", "clean", "green")


def check_master_switch() -> tuple[str, str, str, str]:
    cfg = _read_json(OIL_BOTPATTERN_CONFIG_JSON)
    if not isinstance(cfg, dict):
        return ("🔴", "Sub-system 5 config", "no config file", "red")
    enabled = bool(cfg.get("enabled", False))
    shorts = bool(cfg.get("short_legs_enabled", False))
    decisions_only = bool(cfg.get("decisions_only", False))
    if not enabled:
        return (
            "🟢", "Sub-system 5 config",
            "master kill switch OFF (ready to promote to shadow mode)",
            "green",
        )
    if decisions_only:
        return (
            "🟡", "Sub-system 5 config",
            f"SHADOW mode (no live orders)  shorts={shorts}",
            "yellow",
        )
    return (
        "🔴", "Sub-system 5 config",
        f"LIVE mode (real orders active)  shorts={shorts}",
        "red",
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def compute_readiness(now: datetime | None = None) -> tuple[list[tuple[str, str, str, str]], str]:
    """Run all checks and return (results, overall_verdict).

    overall_verdict is one of:
    - 🟢 GO — all green
    - 🟡 PROCEED WITH CAUTION — at least one yellow, no red
    - 🔴 DO NOT ACTIVATE — at least one red
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    results = [
        check_master_switch(),
        check_catalyst_feed(now),
        check_supply_ledger(now),
        check_heatmap(now),
        check_bot_classifier(now),
        check_thesis(now),
        check_risk_caps(),
        check_drawdown_brakes(),
    ]

    has_red = any(r[3] == "red" for r in results)
    has_yellow = any(r[3] == "yellow" for r in results)
    if has_red:
        overall = "🔴 *DO NOT ACTIVATE* — at least one red flag, resolve before promoting"
    elif has_yellow:
        overall = "🟡 *PROCEED WITH CAUTION* — yellow flags present, review before promoting"
    else:
        overall = "🟢 *GO* — all preflight checks green"
    return (results, overall)


def cmd_readiness(token: str, chat_id: str, _args: str) -> None:
    """Run the activation preflight checklist and render to Telegram."""
    from cli.telegram_bot import tg_send

    now = datetime.now(tz=timezone.utc)
    results, overall = compute_readiness(now)

    lines = ["🛫 *Sub-system 5 activation preflight*", ""]
    for symbol, name, verdict, _severity in results:
        lines.append(f"{symbol} *{name}:* {verdict}")
    lines.append("")
    lines.append(overall)
    lines.append("")
    lines.append(
        "_See_ `docs/wiki/operations/sub_system_5_activation.md` "
        "_for the activation runbook._"
    )

    tg_send(token, chat_id, "\n".join(lines), markdown=True)
