"""Agent runtime control commands for Telegram.

Five deterministic slash commands that let the operator control a running
agent session without touching AI:

  /stop        — abort current run (current tool finishes, no further tools)
  /steer <msg> — inject a steering message before the next LLM turn
  /cancel      — abort + clear all pending approvals (I-changed-my-mind flow)
  /follow <msg>— queue a follow-up that runs after the current run finishes
  /agentstate  — pretty-print the live agent state file

All are pure Python — NO AI calls. See CLAUDE.md "Slash commands are FIXED CODE".

Runtime API is defined in agent/control/CONTRACT.md. The AgentControl class
is imported lazily so the module loads even when agent_control.py isn't yet
on disk (tests mock it).
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger("telegram.commands.agent_control")

# Path to the state file — matches CONTRACT.md definition.
_STATE_PATH = "data/agent/state.json"


def _get_control():
    """Import and return an AgentControl instance (lazy, no module-level crash)."""
    from agent.control.agent_control import AgentControl  # noqa: PLC0415
    return AgentControl()


def _read_state() -> dict | None:
    """Read state file directly (safe even if AgentControl isn't wired yet)."""
    import os
    path = _STATE_PATH
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Could not read state file: %s", exc)
        return None


# ── /stop ────────────────────────────────────────────────────────────────────

def cmd_stop(token: str, chat_id: str, _args: str) -> None:
    """Abort the current agent run.

    The current tool (if any) will complete. No further tool calls will be
    made. The abort reason is logged to the state file.
    """
    from telegram.api import tg_send

    state = _read_state()
    if not state or not state.get("is_running"):
        tg_send(token, chat_id, "No active agent run.")
        return

    try:
        ctrl = _get_control()
        ctrl.abort("user_requested via /stop")
        tg_send(token, chat_id,
                "Stopping\u2026 current tool will finish, no further tools will run.")
    except Exception as exc:
        log.error("cmd_stop error: %s", exc)
        tg_send(token, chat_id, f"Stop failed: `{exc}`")


# ── /steer ───────────────────────────────────────────────────────────────────

def cmd_steer(token: str, chat_id: str, args: str) -> None:
    """Inject a steering message before the next LLM turn.

    Usage: /steer <message>
    The message is queued in the state file and consumed by the runtime
    before it builds the next prompt.
    """
    from telegram.api import tg_send

    msg = args.strip()
    if not msg:
        tg_send(token, chat_id,
                "Usage: `/steer <message>`\nExample: `/steer focus on BRENTOIL funding`")
        return

    state = _read_state()
    if not state or not state.get("is_running"):
        tg_send(token, chat_id, "No active agent run.")
        return

    try:
        ctrl = _get_control()
        ctrl.steer(msg)
        preview = msg[:80] + ("\u2026" if len(msg) > 80 else "")
        tg_send(token, chat_id,
                f"Steering queued: \u2018{preview}\u2019. "
                "Will be injected before next agent turn.")
    except Exception as exc:
        log.error("cmd_steer error: %s", exc)
        tg_send(token, chat_id, f"Steer failed: `{exc}`")


# ── /cancel ──────────────────────────────────────────────────────────────────

def cmd_cancel(token: str, chat_id: str, _args: str) -> None:
    """Abort the current run AND clear all pending approval requests.

    Two-in-one for the "I changed my mind" scenario: the agent stops, and any
    queued Approve/Reject buttons become inert.
    """
    from telegram.api import tg_send

    # Count + clear pending approvals first (works even if agent isn't running).
    dropped = 0
    try:
        from agent.tools import _pending_actions
        dropped = len(_pending_actions)
        _pending_actions.clear()
    except Exception as exc:
        log.warning("Could not clear pending approvals: %s", exc)

    state = _read_state()
    if state and state.get("is_running"):
        try:
            ctrl = _get_control()
            ctrl.abort("user_requested via /cancel")
        except Exception as exc:
            log.error("cmd_cancel abort error: %s", exc)
            tg_send(token, chat_id, f"Abort failed: `{exc}`")
            return

    tg_send(token, chat_id,
            f"Cancelled \u2014 abort flag set + {dropped} pending approval(s) dropped.")


# ── /follow ──────────────────────────────────────────────────────────────────

def cmd_follow(token: str, chat_id: str, args: str) -> None:
    """Queue a follow-up message that runs after the current agent run finishes.

    Usage: /follow <message>
    The runtime will pick this up from the follow_up_queue and execute it
    as the next agent turn once the current run settles.
    """
    from telegram.api import tg_send

    msg = args.strip()
    if not msg:
        tg_send(token, chat_id,
                "Usage: `/follow <message>`\nExample: `/follow check GOLD thesis`")
        return

    try:
        ctrl = _get_control()
        ctrl.follow_up(msg)
        preview = msg[:80] + ("\u2026" if len(msg) > 80 else "")
        tg_send(token, chat_id,
                f"Follow-up queued: \u2018{preview}\u2019. "
                "Will run after current turn settles.")
    except Exception as exc:
        log.error("cmd_follow error: %s", exc)
        tg_send(token, chat_id, f"Follow-up failed: `{exc}`")


# ── /agentstate ───────────────────────────────────────────────────────────────

def cmd_agentstate(token: str, chat_id: str, _args: str) -> None:
    """Pretty-print the current agent state file.

    Shows: is_running, current_turn, current_tool (if any), abort_flag,
    steering/follow-up queue depths, and token budget usage.
    """
    from telegram.api import tg_send

    state = _read_state()
    if not state:
        tg_send(token, chat_id,
                "*Agent State*\n\nNo state file found. Agent is not running.")
        return

    is_running = state.get("is_running", False)
    run_icon = "\U0001f7e2" if is_running else "\u26ab"  # green circle : black circle
    abort_flag = state.get("abort_flag", False)
    abort_reason = state.get("abort_reason") or "\u2014"
    current_turn = state.get("current_turn", 0)
    session_id = state.get("session_id", "\u2014")

    # Tool info
    tool_info = state.get("current_tool")
    if tool_info:
        tool_str = (
            f"`{tool_info.get('name', '?')}`"
            + (f" — {tool_info['args_summary']}" if tool_info.get("args_summary") else "")
        )
    else:
        tool_str = "\u2014"

    # Queues
    steering_q = state.get("steering_queue", [])
    follow_q = state.get("follow_up_queue", [])

    # Tokens
    tokens_used = state.get("tokens_used_session", 0)
    tokens_budget = state.get("tokens_budget_session", 0)
    if tokens_budget:
        pct = int(100 * tokens_used / tokens_budget)
        token_str = f"{tokens_used:,} / {tokens_budget:,} ({pct}%%)"
    else:
        token_str = f"{tokens_used:,} / \u2014"

    lines = [
        "*Agent State*",
        "",
        f"{run_icon} *Running:* {'yes' if is_running else 'no'}",
        f"  Session: `{str(session_id)[:8]}\u2026`" if session_id != "\u2014" else "  Session: \u2014",
        f"  Turn: {current_turn}",
        f"  Current tool: {tool_str}",
        "",
        f"\U0001f6a7 *Abort flag:* {'SET' if abort_flag else 'clear'}"
        + (f" — _{abort_reason}_" if abort_flag else ""),
        "",
        f"\U0001f4e8 *Queues*",
        f"  Steering:  {len(steering_q)} item(s)",
        f"  Follow-up: {len(follow_q)} item(s)",
        "",
        f"\U0001f4ca *Tokens:* {token_str}",
    ]

    tg_send(token, chat_id, "\n".join(lines))
