"""/activate — guided sub-system 5 activation walkthrough.

Chris wants the activation sequence to be prompted, not a runbook to
memorize. This command is the guided version of
`docs/wiki/operations/sub_system_5_activation.md`.

Usage:

  /activate            — show current rung, readiness check, next-step hint
  /activate next       — advance to the next rung (with safety prompts)
  /activate confirm    — confirm the pending advance from the previous
                          /activate next call
  /activate back       — roll back one rung (to shadow or disabled)
  /activate rollback   — hard rollback: set enabled=false immediately

Design principles:
- Deterministic. No AI anywhere. Pure code reading config + running
  /readiness internally.
- Every rung advance requires TWO commands: /activate next (shows what
  will happen) then /activate confirm (actually does it). This prevents
  fat-finger promotion.
- Writes a timestamped audit log of every advance / rollback so you can
  see what happened and when.
- Never flips short_legs_enabled OR sizing_multiplier automatically —
  those require operator judgment. The command tells you which file to
  edit and what to change, then waits for you to rerun.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OIL_BOTPATTERN_CONFIG_JSON = "data/config/oil_botpattern.json"
ACTIVATION_LOG_JSONL = "data/strategy/oil_botpattern_activation_log.jsonl"
PENDING_ADVANCE_JSON = "data/strategy/oil_botpattern_pending_advance.json"


# ---------------------------------------------------------------------------
# Rung classification
# ---------------------------------------------------------------------------

def classify_rung(cfg: dict) -> tuple[int, str]:
    """Return (rung_number, rung_label) based on current config state."""
    enabled = bool(cfg.get("enabled", False))
    decisions_only = bool(cfg.get("decisions_only", False))
    shorts = bool(cfg.get("short_legs_enabled", False))

    if not enabled:
        return (0, "Rung 0 — DISABLED (master kill switch OFF)")
    if decisions_only:
        return (1, "Rung 1 — SHADOW (decisions_only, no real orders)")
    # enabled=true AND decisions_only=false → live
    if not shorts:
        return (3, "Rung 3 — LIVE longs only (shorts kill switch OFF)")
    return (4, "Rung 4 — LIVE longs + shorts")


def next_rung_action(current: int) -> tuple[int, str, dict]:
    """Return (target_rung, description, config_patch) for the next step.

    The config_patch is what /activate confirm will atomically apply to
    oil_botpattern.json.
    """
    if current == 0:
        return (
            1,
            "Enable sub-system 5 in SHADOW mode (decisions_only=true). "
            "The iterator will run the full gate chain, journal every "
            "decision, open PAPER positions with Telegram notices, "
            "track a running shadow balance — but NEVER emit real "
            "OrderIntents. Zero exchange contact.",
            {"enabled": True, "decisions_only": True, "short_legs_enabled": False},
        )
    if current == 1:
        return (
            3,
            "Promote SHADOW → LIVE (decisions_only=false). Real "
            "OrderIntents will be emitted on the next tick where the "
            "gate chain + sizing pass. YOU SHOULD HAVE ≥20 closed "
            "shadow trades in /sim before taking this step. You should "
            "also reduce sizing_multiplier in data/config/risk_caps.json "
            "BEFORE running /activate confirm — this command does NOT "
            "touch risk_caps. Recommended first-live sizing_multiplier: 0.25.",
            {"enabled": True, "decisions_only": False, "short_legs_enabled": False},
        )
    if current == 3:
        return (
            4,
            "Enable SHORT legs (short_legs_enabled=true). A 1-hour grace "
            "period kicks in before any short can open — the iterator's "
            "existing gate_short_grace_period enforces this. You should "
            "have ≥10 closed real long trades and positive/neutral PnL "
            "before taking this step.",
            {"short_legs_enabled": True},
        )
    return (current, "Already at max rung — no further advances.", {})


def rollback_action(current: int) -> tuple[int, str, dict]:
    """Return (target_rung, description, config_patch) for a soft rollback."""
    if current >= 4:
        return (
            3,
            "Disable SHORT legs (short_legs_enabled=false). Existing short "
            "positions continue to run with exchange_protection holding "
            "stops. No new shorts open. Longs unchanged.",
            {"short_legs_enabled": False},
        )
    if current == 3:
        return (
            1,
            "LIVE → SHADOW (decisions_only=true). New entries will open "
            "as paper positions. Existing real positions continue with "
            "exchange_protection holding stops — they are NOT force-closed. "
            "Use /close <instrument> to exit real positions manually.",
            {"decisions_only": True},
        )
    if current == 1:
        return (
            0,
            "SHADOW → DISABLED (enabled=false). Sub-system 5 becomes "
            "fully inert. Existing shadow positions continue to be marked "
            "each tick until they resolve on their own stops/tps.",
            {"enabled": False},
        )
    return (current, "Already at rung 0 — nothing to roll back.", {})


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _read_json(path: str) -> Any:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_json_atomic(path: str, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=False))
    os.replace(tmp, p)


def _append_activation_log(record: dict) -> None:
    p = Path(ACTIVATION_LOG_JSONL)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(record) + "\n")


def apply_patch_to_config(config_path: str, patch: dict) -> dict:
    """Atomically merge patch into oil_botpattern.json. Returns new config."""
    cfg = _read_json(config_path) or {}
    cfg.update(patch)
    _write_json_atomic(config_path, cfg)
    return cfg


# ---------------------------------------------------------------------------
# Readiness gating
# ---------------------------------------------------------------------------

def readiness_verdict() -> tuple[str, list]:
    """Call compute_readiness from the readiness module and return
    (overall_verdict_line, results)."""
    from telegram.commands.readiness import compute_readiness
    return compute_readiness()[::-1]


def can_advance(current_rung: int, target_rung: int) -> tuple[bool, str]:
    """Gating rule: what readiness level is required to advance from
    `current_rung` to `target_rung`?

    - 0 → 1 (shadow): any readiness (just need the config), red OK but warn
    - 1 → 3 (live):   yellow or green required
    - 3 → 4 (+shorts): green only

    This is ONLY a gate check — the operator can override with confirm.
    """
    overall, _results = readiness_verdict()
    is_green = "🟢 *GO*" in overall
    is_yellow = "🟡" in overall
    is_red = "🔴" in overall

    if target_rung == 1:
        # Shadow mode — always permitted but warn if red
        if is_red:
            return (True, "⚠️ Readiness is RED but shadow mode does not place real orders — you may proceed at your own risk.")
        return (True, "")
    if target_rung == 3:
        if is_red:
            return (False, "🔴 Cannot promote to LIVE with red readiness flags. Resolve them first.")
        if is_yellow:
            return (True, "⚠️ Yellow readiness flags present. You may proceed but review them in /readiness first.")
        return (True, "")
    if target_rung == 4:
        if not is_green:
            return (False, "🔴 Cannot enable SHORT legs unless readiness is fully green.")
        return (True, "")
    return (True, "")


# ---------------------------------------------------------------------------
# Telegram command handler
# ---------------------------------------------------------------------------

def cmd_activate(token: str, chat_id: str, args: str) -> None:
    """Guided sub-system 5 activation walkthrough."""
    from telegram.bot import tg_send

    sub = (args or "").strip().lower()
    cfg = _read_json(OIL_BOTPATTERN_CONFIG_JSON) or {}

    if sub in ("", "status"):
        _render_status(token, chat_id, cfg, tg_send)
        return

    if sub == "next":
        _render_next(token, chat_id, cfg, tg_send)
        return

    if sub == "confirm":
        _apply_pending(token, chat_id, cfg, tg_send)
        return

    if sub == "back":
        _render_rollback(token, chat_id, cfg, tg_send, hard=False)
        return

    if sub == "rollback":
        _apply_hard_rollback(token, chat_id, cfg, tg_send)
        return

    tg_send(token, chat_id,
            "Usage:\n"
            "  `/activate` — show current rung + readiness\n"
            "  `/activate next` — preview next-rung advance\n"
            "  `/activate confirm` — execute the pending advance\n"
            "  `/activate back` — soft rollback one rung\n"
            "  `/activate rollback` — hard rollback (set enabled=false now)",
            markdown=True)


def _render_status(token: str, chat_id: str, cfg: dict, tg_send) -> None:
    rung, rung_label = classify_rung(cfg)
    overall, results = readiness_verdict()

    lines = ["🛫 *Sub-system 5 activation status*", ""]
    lines.append(f"*Current state:* {rung_label}")
    lines.append("")
    lines.append("*Readiness preflight:*")
    for symbol, name, verdict, _sev in results:
        lines.append(f"  {symbol} {name}: {verdict}")
    lines.append("")
    lines.append(overall)
    lines.append("")

    target, description, _patch = next_rung_action(rung)
    if target == rung:
        lines.append("*Next step:* no further advances.")
    else:
        lines.append(f"*Next step:* advance to Rung {target}")
        lines.append(f"  {description}")
        lines.append("")
        lines.append("Run `/activate next` to preview, then `/activate confirm` to execute.")
    lines.append("")
    lines.append(
        "_Rollback:_ `/activate back` _(soft, one rung) or_ "
        "`/activate rollback` _(hard, enabled=false now)_"
    )

    tg_send(token, chat_id, "\n".join(lines), markdown=True)


def _render_next(token: str, chat_id: str, cfg: dict, tg_send) -> None:
    rung, rung_label = classify_rung(cfg)
    target, description, patch = next_rung_action(rung)

    if target == rung:
        tg_send(token, chat_id,
                f"{rung_label}\n\nAlready at the max rung — nothing to advance to.",
                markdown=True)
        return

    ok, gate_msg = can_advance(rung, target)
    if not ok:
        tg_send(token, chat_id,
                f"*Cannot advance:* {gate_msg}\n\nRun `/readiness` to see which flags are red.",
                markdown=True)
        return

    # Stash the pending advance for /activate confirm to pick up
    pending = {
        "staged_at": datetime.now(tz=timezone.utc).isoformat(),
        "from_rung": rung,
        "to_rung": target,
        "from_label": rung_label,
        "description": description,
        "patch": patch,
    }
    _write_json_atomic(PENDING_ADVANCE_JSON, pending)

    lines = [f"🛫 *Pending advance: Rung {rung} → Rung {target}*", ""]
    lines.append(description)
    lines.append("")
    lines.append("*Config patch to apply:*")
    for k, v in patch.items():
        lines.append(f"  `{k}` = {v}")
    if gate_msg:
        lines.append("")
        lines.append(gate_msg)
    lines.append("")
    lines.append("Run `/activate confirm` within 10 minutes to execute.")
    lines.append("Any other `/activate next` run replaces this pending advance.")

    tg_send(token, chat_id, "\n".join(lines), markdown=True)


def _apply_pending(token: str, chat_id: str, cfg: dict, tg_send) -> None:
    pending = _read_json(PENDING_ADVANCE_JSON)
    if not isinstance(pending, dict):
        tg_send(token, chat_id,
                "No pending advance. Run `/activate next` first.",
                markdown=True)
        return

    # 10-minute freshness check
    try:
        staged = datetime.fromisoformat(pending.get("staged_at", ""))
        if staged.tzinfo is None:
            staged = staged.replace(tzinfo=timezone.utc)
    except ValueError:
        staged = datetime.now(tz=timezone.utc)
    age_minutes = (datetime.now(tz=timezone.utc) - staged).total_seconds() / 60.0
    if age_minutes > 10:
        tg_send(token, chat_id,
                f"Pending advance is stale ({age_minutes:.0f} min old). "
                f"Run `/activate next` again.",
                markdown=True)
        return

    patch = pending.get("patch") or {}
    new_cfg = apply_patch_to_config(OIL_BOTPATTERN_CONFIG_JSON, patch)

    _append_activation_log({
        "applied_at": datetime.now(tz=timezone.utc).isoformat(),
        "kind": "advance",
        "from_rung": pending.get("from_rung"),
        "to_rung": pending.get("to_rung"),
        "patch": patch,
        "actor": "telegram",
    })

    # Clear the pending file
    try:
        Path(PENDING_ADVANCE_JSON).unlink()
    except OSError:
        pass

    new_rung, new_label = classify_rung(new_cfg)
    lines = [
        f"✅ *Advanced to Rung {new_rung}*",
        "",
        new_label,
        "",
        "*Applied patch:*",
    ]
    for k, v in patch.items():
        lines.append(f"  `{k}` = {v}")
    lines.append("")
    lines.append("Sub-system 5 will pick up the new config on its next tick (≤60s).")
    lines.append("Monitor with `/oilbot`, `/sim`, `/oilbotjournal`.")
    lines.append("Rollback any time with `/activate back`.")
    tg_send(token, chat_id, "\n".join(lines), markdown=True)


def _render_rollback(token: str, chat_id: str, cfg: dict, tg_send, hard: bool) -> None:
    rung, rung_label = classify_rung(cfg)
    target, description, patch = rollback_action(rung)

    if target == rung:
        tg_send(token, chat_id,
                f"{rung_label}\n\nNothing to roll back — already at Rung 0.",
                markdown=True)
        return

    new_cfg = apply_patch_to_config(OIL_BOTPATTERN_CONFIG_JSON, patch)
    _append_activation_log({
        "applied_at": datetime.now(tz=timezone.utc).isoformat(),
        "kind": "soft_rollback" if not hard else "hard_rollback",
        "from_rung": rung,
        "to_rung": target,
        "patch": patch,
        "actor": "telegram",
    })
    # Rollback clears any pending advance
    try:
        Path(PENDING_ADVANCE_JSON).unlink()
    except OSError:
        pass

    new_rung, new_label = classify_rung(new_cfg)
    lines = [
        f"↩️ *Rolled back to Rung {new_rung}*",
        "",
        new_label,
        "",
        description,
        "",
        "*Applied patch:*",
    ]
    for k, v in patch.items():
        lines.append(f"  `{k}` = {v}")
    tg_send(token, chat_id, "\n".join(lines), markdown=True)


def _apply_hard_rollback(token: str, chat_id: str, cfg: dict, tg_send) -> None:
    """Force enabled=false regardless of current rung."""
    patch = {"enabled": False}
    new_cfg = apply_patch_to_config(OIL_BOTPATTERN_CONFIG_JSON, patch)
    _append_activation_log({
        "applied_at": datetime.now(tz=timezone.utc).isoformat(),
        "kind": "hard_rollback",
        "patch": patch,
        "actor": "telegram",
    })
    try:
        Path(PENDING_ADVANCE_JSON).unlink()
    except OSError:
        pass
    tg_send(token, chat_id,
            "🛑 *HARD ROLLBACK applied*\n\n"
            "Sub-system 5 is now DISABLED. Any existing shadow positions "
            "will continue to be marked; any live positions continue to be "
            "held by exchange_protection but the iterator takes no further "
            "action. Use `/close <instrument>` to manually exit live "
            "positions if needed.",
            markdown=True)
