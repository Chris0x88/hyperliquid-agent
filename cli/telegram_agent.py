"""Direct Telegram AI agent — handles free-text messages via OpenRouter.

Called from telegram_bot.py when a message doesn't match any slash command.
Slash commands are handled separately and never touch this module.

Design:
- System prompt from openclaw/AGENT.md + SOUL.md
- Live context injected every message (prices, account, thesis)
- Chat history (last 20 messages) for continuity
- OpenRouter API via requests (no SDK)
- Full chat history logged to JSONL for Claude Code to learn from
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Optional

import requests

log = logging.getLogger("telegram_agent")

# Paths
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HISTORY_FILE = _PROJECT_ROOT / "data" / "daemon" / "chat_history.jsonl"
_AGENT_MD = _PROJECT_ROOT / "openclaw" / "AGENT.md"
_SOUL_MD = _PROJECT_ROOT / "openclaw" / "SOUL.md"
_AUTH_PROFILES = Path.home() / ".openclaw" / "agents" / "default" / "agent" / "auth-profiles.json"

# Limits
_MAX_HISTORY = 20
_MAX_HISTORY_CHARS = 12000  # Cap total history chars to stay within context window
_MAX_RESPONSE_TOKENS = 1500
_MAX_TG_MESSAGE = 4096
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_MODEL = "stepfun/step-3.5-flash:free"


def handle_ai_message(token: str, chat_id: str, text: str, user_name: str = "") -> None:
    """Handle a free-text Telegram message with an AI response.

    Called from telegram_bot.py's polling loop. Blocks until response is sent.
    """
    try:
        # Log user message
        _log_chat("user", text, user_name=user_name)

        # Send typing indicator
        _tg_typing(token, chat_id)

        # Build messages for LLM
        system_prompt = _build_system_prompt()
        live_context = _build_live_context()
        history = _load_chat_history(_MAX_HISTORY)

        messages = [
            {"role": "system", "content": system_prompt + "\n\n" + live_context},
        ]
        # Add chat history as conversation turns
        for entry in history[:-1]:  # exclude the message we just logged
            messages.append({"role": entry["role"], "content": entry["text"]})
        # Add current user message
        messages.append({"role": "user", "content": text})

        # Call OpenRouter
        response_text = _call_openrouter(messages)
        if not response_text:
            response_text = "Sorry, I couldn't get a response from the AI. Try again or use /status for live data."

        # Send response
        _tg_send_markdown(token, chat_id, response_text)

        # Log assistant response
        _log_chat("assistant", response_text)

    except Exception as e:
        log.error("AI handler failed: %s", e, exc_info=True)
        try:
            _tg_send_plain(token, chat_id, f"AI error: {e}\n\nUse /status or /help for fixed commands.")
        except Exception:
            pass


def _build_system_prompt() -> str:
    """Load AGENT.md + SOUL.md as the system prompt."""
    parts = []
    for path in (_AGENT_MD, _SOUL_MD):
        if path.exists():
            parts.append(path.read_text().strip())
    return "\n\n---\n\n".join(parts) if parts else "You are a HyperLiquid trading assistant."


def _build_live_context() -> str:
    """Build token-budgeted, relevance-scored context using the context harness.

    Uses common.context_harness — the same system designed for thesis evaluation.
    Tiers: CRITICAL (alerts, position, snapshot) > RELEVANT (thesis, memory,
    learnings) > BACKGROUND (research notes, issues).
    """
    try:
        from common.context_harness import build_multi_market_context

        # Fetch account state for the harness
        account_state = _fetch_account_state_for_harness()

        # Build market snapshots (compact text per market)
        market_snapshots = _fetch_market_snapshots()

        # Assemble with token budget (2000 tokens for context, rest for history + response)
        assembled = build_multi_market_context(
            markets=["xyz:BRENTOIL", "BTC"],
            account_state=account_state,
            market_snapshots=market_snapshots,
            token_budget=2000,
        )

        header = "--- LIVE CONTEXT (fetched just now) ---"
        footer = f"[Context: {assembled.estimated_tokens}t, {assembled.budget_used_pct}% budget, blocks: {', '.join(assembled.blocks_included)}]"
        return f"{header}\n{assembled.text}\n{footer}"

    except Exception as e:
        log.warning("Context harness failed, using fallback: %s", e)
        return _build_live_context_fallback()


def _fetch_account_state_for_harness() -> dict:
    """Fetch account state in the format context_harness expects."""
    from common.account_resolver import resolve_main_wallet, resolve_vault_address

    main_addr = resolve_main_wallet(required=False)
    total_equity = 0.0
    alerts = []

    if main_addr:
        # XYZ clearinghouse
        r = requests.post("https://api.hyperliquid.xyz/info",
                          json={"type": "clearinghouseState", "user": main_addr, "dex": "xyz"},
                          timeout=8)
        if r.status_code == 200:
            data = r.json()
            total_equity += float(data.get("marginSummary", {}).get("accountValue", 0))

        time.sleep(0.2)
        # Spot USDC
        r = requests.post("https://api.hyperliquid.xyz/info",
                          json={"type": "spotClearinghouseState", "user": main_addr},
                          timeout=8)
        if r.status_code == 200:
            for bal in r.json().get("balances", []):
                if bal.get("coin") == "USDC":
                    total_equity += float(bal.get("total", 0))

    # Working state for escalation + alerts
    ws_path = _PROJECT_ROOT / "data" / "memory" / "working_state.json"
    escalation = "L0"
    if ws_path.exists():
        ws = json.loads(ws_path.read_text())
        escalation = ws.get("escalation_level", "L0")
        if ws.get("heartbeat_consecutive_failures", 0) > 5:
            alerts.append(f"Heartbeat failing ({ws['heartbeat_consecutive_failures']} consecutive)")

    return {
        "account": {"total_equity": total_equity},
        "alerts": alerts,
        "escalation": escalation,
    }


def _fetch_market_snapshots() -> dict:
    """Fetch compact price snapshots for watchlist markets."""
    snapshots = {}
    try:
        # All prices in one call each
        prices = {}
        r = requests.post("https://api.hyperliquid.xyz/info",
                          json={"type": "allMids"}, timeout=8)
        if r.status_code == 200:
            prices.update(r.json())
        time.sleep(0.2)
        r = requests.post("https://api.hyperliquid.xyz/info",
                          json={"type": "allMids", "dex": "xyz"}, timeout=8)
        if r.status_code == 200:
            prices.update(r.json())

        watchlist = {"BTC": "BTC", "xyz:BRENTOIL": "xyz:BRENTOIL",
                     "xyz:GOLD": "xyz:GOLD", "xyz:SILVER": "xyz:SILVER"}
        for display, key in watchlist.items():
            if key in prices:
                v = float(prices[key])
                snapshots[display] = f"PRICE ({display}): ${v:,.2f}"
    except Exception:
        pass
    return snapshots


def _build_live_context_fallback() -> str:
    """Minimal fallback if context harness fails."""
    lines = ["--- LIVE CONTEXT (fallback) ---"]
    try:
        prices = {}
        r = requests.post("https://api.hyperliquid.xyz/info",
                          json={"type": "allMids", "dex": "xyz"}, timeout=8)
        if r.status_code == 200:
            for coin, mid in r.json().items():
                prices[coin] = float(mid)
        r = requests.post("https://api.hyperliquid.xyz/info",
                          json={"type": "allMids"}, timeout=8)
        if r.status_code == 200:
            for coin, mid in r.json().items():
                prices[coin] = float(mid)
        for k in ["BTC", "xyz:BRENTOIL", "xyz:GOLD", "xyz:SILVER"]:
            if k in prices:
                lines.append(f"{k}: ${prices[k]:,.2f}")
    except Exception as e:
        lines.append(f"Prices unavailable: {e}")
    return "\n".join(lines)


def _load_chat_history(limit: int = 20) -> List[Dict]:
    """Load recent chat history from JSONL, respecting token budget.

    Takes the most recent messages that fit within _MAX_HISTORY_CHARS total.
    This prevents context window overflow on long conversations.
    """
    if not _HISTORY_FILE.exists():
        return []
    entries = []
    try:
        for line in _HISTORY_FILE.read_text().splitlines():
            if line.strip():
                entries.append(json.loads(line))
    except Exception:
        return []

    # Take last N entries
    recent = entries[-limit:]

    # Trim from the front if total chars exceed budget
    total_chars = sum(len(e.get("text", "")) for e in recent)
    while recent and total_chars > _MAX_HISTORY_CHARS:
        removed = recent.pop(0)
        total_chars -= len(removed.get("text", ""))

    return recent


def _log_chat(role: str, text: str, user_name: str = "", model: str = "") -> None:
    """Append a chat entry to history JSONL."""
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": int(time.time()),
        "role": role,
        "text": text,
    }
    if user_name:
        entry["user"] = user_name
    if model:
        entry["model"] = model
    with open(_HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _call_openrouter(messages: List[Dict]) -> Optional[str]:
    """Call OpenRouter API and return response text."""
    api_key = _get_openrouter_key()
    if not api_key:
        return "Error: No OpenRouter API key found."

    try:
        resp = requests.post(
            _OPENROUTER_URL,
            json={
                "model": _DEFAULT_MODEL,
                "messages": messages,
                "max_tokens": _MAX_RESPONSE_TOKENS,
                "temperature": 0.3,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            log.error("OpenRouter API error: %s %s", resp.status_code, resp.text[:200])
            return f"OpenRouter API error ({resp.status_code}). Try /status for live data."

        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return "No response from model."
    except requests.Timeout:
        return "AI response timed out. Try /status for instant data."
    except Exception as e:
        log.error("OpenRouter call failed: %s", e)
        return f"AI call failed: {e}"


def _get_openrouter_key() -> Optional[str]:
    """Read OpenRouter API key from auth-profiles.json."""
    try:
        if _AUTH_PROFILES.exists():
            data = json.loads(_AUTH_PROFILES.read_text())
            profiles = data.get("profiles", {})
            for name, profile in profiles.items():
                if profile.get("provider") == "openrouter" and profile.get("key"):
                    return profile["key"]
    except Exception:
        pass

    # Fallback: environment variable
    import os
    return os.environ.get("OPENROUTER_API_KEY")


def _tg_send_markdown(token: str, chat_id: str, text: str) -> None:
    """Send a Telegram message with Markdown formatting, split if needed.

    Tries Markdown first, falls back to plain text if parsing fails.
    Strips problematic markdown artifacts that LLMs sometimes produce.
    """
    # Clean up common LLM markdown artifacts that break Telegram
    text = text.replace("```json", "").replace("```", "")
    text = text.replace("<function_calls>", "").replace("</function_calls>", "")
    text = text.replace("<invoke", "").replace("</invoke>", "")
    text = text.replace("<parameter", "").replace("</parameter>", "")

    # Convert **bold** (standard markdown) to *bold* (Telegram markdown)
    import re
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)

    # Convert ### Heading to *Heading* (Telegram has no heading syntax)
    text = re.sub(r'^#{1,3}\s+(.+)$', r'*\1*', text, flags=re.MULTILINE)

    chunks = _split_message(text)
    for chunk in chunks:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            # If markdown parsing fails, retry as plain text
            if not r.json().get("ok"):
                _tg_send_plain(token, chat_id, chunk)
        except Exception:
            _tg_send_plain(token, chat_id, chunk)


def _tg_send_plain(token: str, chat_id: str, text: str) -> None:
    """Send plain text to Telegram (fallback)."""
    for chunk in _split_message(text):
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                timeout=10,
            )
        except Exception:
            pass


def _tg_typing(token: str, chat_id: str) -> None:
    """Send typing indicator so user knows we're working."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5,
        )
    except Exception:
        pass


def _split_message(text: str) -> List[str]:
    """Split text into chunks of max _MAX_TG_MESSAGE chars."""
    if len(text) <= _MAX_TG_MESSAGE:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= _MAX_TG_MESSAGE:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, _MAX_TG_MESSAGE)
        if split_at == -1:
            split_at = _MAX_TG_MESSAGE
        else:
            split_at += 1
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    return chunks
