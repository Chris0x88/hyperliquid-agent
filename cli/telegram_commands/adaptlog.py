"""/adaptlog — query the adaptive evaluator decision log.

The adaptive evaluator writes every non-HOLD decision (plus HOLD
heartbeats) to `data/strategy/oil_botpattern_adaptive_log.jsonl` as
a flat, pre-featurized row. This command makes that log queryable
from Telegram.

Usage:

  /adaptlog                      — last 10 decisions (any mode, any action)
  /adaptlog 25                   — last 25 decisions
  /adaptlog exits                — last 10 EXIT decisions
  /adaptlog trails               — last 10 TRAIL_BREAKEVEN decisions
  /adaptlog tightens             — last 10 TIGHTEN_STOP decisions
  /adaptlog live                 — last 10 live-mode decisions only
  /adaptlog shadow               — last 10 shadow-mode decisions only
  /adaptlog BRENTOIL             — last 10 decisions for a specific instrument

Shows for each row: timestamp, mode (shadow/live), instrument, side,
action, reason, and the three derived metrics (price_progress,
time_progress, velocity_ratio) that drove the decision.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ADAPTIVE_LOG_JSONL = "data/strategy/oil_botpattern_adaptive_log.jsonl"


def _load_log_rows(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict] = []
    try:
        with p.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return rows


def _filter_rows(
    rows: list[dict],
    *,
    action: str | None = None,
    mode: str | None = None,
    instrument: str | None = None,
) -> list[dict]:
    out = []
    for r in rows:
        if action is not None:
            if (r.get("decision") or {}).get("action") != action:
                continue
        if mode is not None:
            if r.get("mode") != mode:
                continue
        if instrument is not None:
            if (r.get("position") or {}).get("instrument") != instrument:
                continue
        out.append(r)
    return out


def parse_args(arg: str) -> tuple[int, str | None, str | None, str | None]:
    """Parse the /adaptlog argument string into (limit, action, mode, instrument).

    Returns defaults (10, None, None, None) when nothing matches.
    """
    limit = 10
    action: str | None = None
    mode: str | None = None
    instrument: str | None = None

    tokens = (arg or "").strip().split()
    for tok in tokens:
        tok_lower = tok.lower()
        # Integer → limit
        try:
            n = int(tok)
            if 1 <= n <= 100:
                limit = n
                continue
        except ValueError:
            pass
        # Action shorthand
        if tok_lower in ("exit", "exits"):
            action = "exit"
            continue
        if tok_lower in ("trail", "trails", "trail_breakeven", "breakeven"):
            action = "trail_breakeven"
            continue
        if tok_lower in ("tighten", "tightens", "tighten_stop"):
            action = "tighten_stop"
            continue
        if tok_lower in ("scale", "scale_out", "scaleout"):
            action = "scale_out"
            continue
        if tok_lower == "hold":
            action = "hold"
            continue
        # Mode
        if tok_lower in ("shadow", "paper"):
            mode = "shadow"
            continue
        if tok_lower == "live":
            mode = "live"
            continue
        # Otherwise treat as instrument symbol (uppercased)
        instrument = tok.upper()
    return (limit, action, mode, instrument)


def cmd_adaptlog(token: str, chat_id: str, args: str) -> None:
    """Query the adaptive evaluator decision log."""
    from cli.telegram_bot import tg_send

    limit, action, mode, instrument = parse_args(args)
    rows = _load_log_rows(ADAPTIVE_LOG_JSONL)
    rows = _filter_rows(rows, action=action, mode=mode, instrument=instrument)

    if not rows:
        lines = ["🧠 *Adaptive log*", ""]
        lines.append("No decisions logged yet matching the filter.")
        lines.append("")
        lines.append("_Log is written by sub-system 5's adaptive evaluator_")
        lines.append("_on every non-HOLD decision + a 15-min HOLD heartbeat._")
        lines.append("_Flip_ `decisions_only=true` _or promote to LIVE mode_")
        lines.append("_to start seeing decisions here._")
        tg_send(token, chat_id, "\n".join(lines), markdown=True)
        return

    # Show the most recent `limit` rows (log is append-only, last = latest)
    recent = rows[-limit:][::-1]

    # Header
    filter_parts = []
    if action:
        filter_parts.append(f"action={action}")
    if mode:
        filter_parts.append(f"mode={mode}")
    if instrument:
        filter_parts.append(f"instrument={instrument}")
    filter_str = f" ({', '.join(filter_parts)})" if filter_parts else ""

    lines = [f"🧠 *Adaptive log — last {len(recent)} of {len(rows)}{filter_str}*", ""]

    action_emoji = {
        "exit": "🛑",
        "scale_out": "🎯",
        "tighten_stop": "🔒",
        "trail_breakeven": "🔒",
        "hold": "⏸️",
    }

    for r in recent:
        ts = (r.get("logged_at") or "")[:19].replace("T", " ")
        row_mode = r.get("mode", "?")
        pos = r.get("position", {}) or {}
        dec = r.get("decision", {}) or {}
        snap = r.get("snapshot", {}) or {}

        inst = pos.get("instrument", "?")
        side = str(pos.get("side", "?")).upper()
        act = dec.get("action", "?")
        emoji = action_emoji.get(act, "•")
        reason = dec.get("reason", "")

        pp = dec.get("price_progress", 0.0) or 0.0
        tp = dec.get("time_progress", 0.0) or 0.0
        vr = dec.get("velocity_ratio", 0.0) or 0.0
        cp = snap.get("current_price")
        ep = pos.get("entry_price")

        lines.append(
            f"{emoji} `{ts}` *{act}* {row_mode.upper()} {side} {inst}"
        )
        if cp is not None and ep is not None:
            try:
                delta_pct = (float(cp) - float(ep)) / float(ep) * 100.0 * (
                    1 if side == "LONG" else -1
                )
                lines.append(
                    f"    entry {float(ep):,.2f} → mark {float(cp):,.2f} "
                    f"({delta_pct:+.2f}%)"
                )
            except (TypeError, ValueError):
                pass
        lines.append(
            f"    progress: price {pp:.1%}  time {tp:.1%}  v={vr:.2f}"
        )
        if reason:
            lines.append(f"    _{reason}_")
        lines.append("")

    tg_send(token, chat_id, "\n".join(lines), markdown=True)
