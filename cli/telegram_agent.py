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

from common.watchlist import get_watchlist_coins, load_watchlist

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
_MAX_RESPONSE_TOKENS = 4096
_MAX_TG_MESSAGE = 4096
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_DEFAULT_MODEL = "stepfun/step-3.5-flash:free"
# Fallback waterfall: free models only
_FALLBACK_CHAIN = [
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "stepfun/step-3.5-flash:free",
    "deepseek/deepseek-chat-v3-0324:free",
]
_MODEL_CONFIG = _PROJECT_ROOT / "data" / "config" / "model_config.json"
_MODELS_JSON = Path.home() / ".openclaw" / "agents" / "default" / "agent" / "models.json"

_CACHE: Dict[str, dict] = {}

_MAX_TOOL_LOOPS = 3  # Hard limit — prevents infinite tool loops on fallback models

# Regex for text-based tool calls: [TOOL: name {"arg": "val"}]
import re
_TOOL_CALL_RE = re.compile(
    r'\[\s*TOOL:\s*(\w+)\s*(\{[^}]*\})?\s*\]',
    re.IGNORECASE,
)


def _parse_text_tool_calls(content: str) -> list:
    """Parse text-based tool invocations from model output.

    Free models can't use native function calling but can output:
      [TOOL: live_price {"market": "BTC"}]
      [TOOL: analyze_market {"coin": "xyz:BRENTOIL"}]
      [TOOL: account_summary]

    Returns list in the same format as native tool_calls, or empty list.
    """
    from cli.agent_tools import TOOL_DEFS
    valid_names = {t["function"]["name"] for t in TOOL_DEFS}

    calls = []
    for match in _TOOL_CALL_RE.finditer(content):
        name = match.group(1)
        args_str = match.group(2) or "{}"
        if name in valid_names:
            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                args = {}
            calls.append({
                "id": f"text_{name}",
                "function": {"name": name, "arguments": args},
            })
    return calls


def _strip_tool_calls(content: str) -> str:
    """Remove [TOOL: ...] invocations from text so they don't appear in the response."""
    return _TOOL_CALL_RE.sub("", content)


def handle_ai_message(token: str, chat_id: str, text: str, user_name: str = "") -> None:
    """Handle a free-text Telegram message with an AI response.

    Called from telegram_bot.py's polling loop. Blocks until response is sent.
    Supports tool-calling via OpenRouter function calling — READ tools execute
    automatically, WRITE tools require user approval via inline keyboard.
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

        # Import tool definitions
        from cli.agent_tools import (
            TOOL_DEFS, execute_tool, is_write_tool,
            store_pending, format_confirmation,
        )

        # Call OpenRouter with tool definitions
        response = _call_openrouter(messages, tools=TOOL_DEFS)

        # Track if we fell back from Anthropic rate limit — stay on fallback for remaining loops
        _session_fallback_model = getattr(_call_openrouter, "_last_fallback", None)

        # Tool-calling loop: handles three modes (tried in order):
        # 1. Native function calling (paid models)
        # 2. Text-based [TOOL: name {args}] (regex, free models)
        # 3. Python code blocks (AST-parsed, free models)
        for _loop in range(_MAX_TOOL_LOOPS):
            tool_calls = response.get("tool_calls")
            code_parsed = []  # Python code block results

            # If no native tool_calls, check for text-based tool invocations
            # Format: [TOOL: name {"arg": "val"}] anywhere in the content
            if not tool_calls:
                content = response.get("content") or ""
                parsed = _parse_text_tool_calls(content)
                if parsed:
                    tool_calls = parsed
                    # Strip tool invocations from content for the final response
                    response["content"] = _strip_tool_calls(content)

            # If still no tool calls, try Python code block parsing
            if not tool_calls:
                content = response.get("content") or ""
                from common.code_tool_parser import parse_tool_calls as parse_code_calls
                from common.tools import TOOL_REGISTRY, WRITE_TOOLS as CORE_WRITE_TOOLS
                code_parsed = parse_code_calls(content, TOOL_REGISTRY)
                if code_parsed:
                    log.info("Parsed %d tool calls from Python code blocks", len(code_parsed))

            if not tool_calls and not code_parsed:
                break

            if code_parsed:
                # Handle Python code block tool calls via the new system
                from common.code_tool_parser import execute_parsed_calls, strip_code_blocks
                from common.tool_renderers import render_for_ai
                from common.tools import WRITE_TOOLS as CORE_WRITE_TOOLS

                # Strip code blocks BEFORE appending to history (avoid mutation)
                cleaned_content = strip_code_blocks(response.get("content") or "")
                messages.append({"role": "assistant", "content": cleaned_content})

                results = execute_parsed_calls(code_parsed, TOOL_REGISTRY, CORE_WRITE_TOOLS)

                result_parts = []
                for r in results:
                    if r.error:
                        result_parts.append(f"[{r.name}] ERROR: {r.error}")
                    elif r.data.get("_pending"):
                        # WRITE tool — go through approval flow
                        fn_args = r.data.get("kwargs", {})
                        # Also merge positional args
                        import inspect
                        fn = TOOL_REGISTRY.get(r.name)
                        if fn and r.data.get("args"):
                            sig = inspect.signature(fn)
                            params = list(sig.parameters.keys())
                            for i, val in enumerate(r.data["args"]):
                                if i < len(params):
                                    fn_args[params[i]] = val

                        action_id = store_pending(r.name, fn_args, chat_id)
                        conf_text, buttons = format_confirmation(r.name, fn_args, action_id)
                        from cli.telegram_bot import tg_send_buttons
                        tg_send_buttons(token, chat_id, conf_text, buttons)
                        result_parts.append(f"[{r.name}] Action requires user approval. Confirmation sent.")
                        log.info("Write tool %s pending approval: %s", r.name, action_id)
                    else:
                        rendered = render_for_ai(r.name, r.data)
                        result_parts.append(f"[{r.name}] {rendered}")
                        log.info("Read tool %s executed via code parser", r.name)

                messages.append({
                    "role": "system",
                    "content": "[Tool results]:\n" + "\n".join(result_parts) + "\n\nRespond to the user using this data. Do NOT call the tools again.",
                })
            else:
                # Handle native/text-parsed tool calls (existing path)
                messages.append(response)
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    raw_args = tc["function"]["arguments"]
                    fn_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    call_id = tc.get("id", f"text_{_loop}_{fn_name}")

                    if is_write_tool(fn_name):
                        # Store pending, send confirmation buttons
                        action_id = store_pending(fn_name, fn_args, chat_id)
                        conf_text, buttons = format_confirmation(fn_name, fn_args, action_id)
                        from cli.telegram_bot import tg_send_buttons
                        tg_send_buttons(token, chat_id, conf_text, buttons)
                        messages.append({
                            "role": "tool" if response.get("tool_calls") else "user",
                            "tool_call_id": call_id,
                            "content": "Action requires user approval. Confirmation sent to Telegram.",
                        })
                        log.info("Write tool %s pending approval: %s", fn_name, action_id)
                    else:
                        # READ tool — execute immediately
                        result = execute_tool(fn_name, fn_args)
                        if response.get("tool_calls"):
                            # Native tool calling — use proper tool message
                            messages.append({
                                "role": "tool",
                                "tool_call_id": call_id,
                                "content": result,
                            })
                        else:
                            # Text-parsed — inject result as system message
                            messages.append({
                                "role": "user",
                                "content": f"[Tool result for {fn_name}]:\n{result}\n\nNow respond to the user using this data. Do NOT call the tool again.",
                            })
                        log.info("Read tool %s executed", fn_name)

            _tg_typing(token, chat_id)
            # If we fell back from Anthropic rate limit, stay on fallback model
            if _session_fallback_model:
                response = _call_openrouter_direct(messages, tools=TOOL_DEFS, model_override=_session_fallback_model)
            else:
                response = _call_openrouter(messages, tools=TOOL_DEFS)
                _session_fallback_model = _call_openrouter._last_fallback

        # Extract final text response
        response_text = response.get("content") or ""
        # Clean any remaining tool call syntax from final response
        response_text = _strip_tool_calls(response_text)
        # Also strip Python code blocks that were tool calls
        from common.code_tool_parser import strip_code_blocks
        response_text = strip_code_blocks(response_text).strip()
        if not response_text:
            response_text = "Sorry, I couldn't get a response from the AI. Try again or use /status for live data."

        # Extract thought tag for intent-based memory
        import re
        thought_match = re.search(r'<thought>(.*?)</thought>', response_text, re.IGNORECASE | re.DOTALL)
        if thought_match:
            memory_intent = thought_match.group(1).strip()
            # Strip the thought tag from what the user sees
            tg_text = re.sub(r'<thought>.*?</thought>\s*', '', response_text, flags=re.IGNORECASE | re.DOTALL).strip()
        else:
            memory_intent = _sanitize_assistant_history(response_text)
            tg_text = response_text

        # Send response
        _tg_send_markdown(token, chat_id, tg_text)

        # Log memory intent instead of raw sanitized response
        _log_chat("assistant", memory_intent)

    except Exception as e:
        log.error("AI handler failed: %s", e, exc_info=True)
        try:
            _tg_send_plain(token, chat_id, f"AI error: {e}\n\nUse /status or /help for fixed commands.")
        except Exception:
            pass


def _build_system_prompt() -> str:
    """Load AGENT.md + SOUL.md + agent memory as the system prompt."""
    parts = []
    for path in (_AGENT_MD, _SOUL_MD):
        if path.exists():
            parts.append(path.read_text().strip())
    # Load agent memory index if it exists
    memory_path = _PROJECT_ROOT / "data" / "agent_memory" / "MEMORY.md"
    if memory_path.exists():
        memory_content = memory_path.read_text().strip()
        if memory_content:
            parts.append(f"--- AGENT MEMORY ---\n\n{memory_content}")
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

        # Build market snapshots with position-aware signals
        market_snapshots = _fetch_market_snapshots(positions=account_state.get("positions", []))

        # Build market list: watchlist + any coins with open positions
        # This ensures we ALWAYS show position data even for unwatched markets
        markets = list(get_watchlist_coins())
        for pos in account_state.get("positions", []):
            coin = pos.get("coin", "")
            # Normalize: position coins may lack xyz: prefix
            if coin and coin not in markets:
                # Try with xyz: prefix too
                if f"xyz:{coin}" not in markets:
                    markets.append(coin)

        # Assemble with token budget (3500 tokens for context + signal summaries)
        assembled = build_multi_market_context(
            markets=markets,
            account_state=account_state,
            market_snapshots=market_snapshots,
            token_budget=3500,
        )

        header = "--- LIVE CONTEXT (fetched just now) ---"
        footer = f"[Context: {assembled.estimated_tokens}t, {assembled.budget_used_pct}% budget, blocks: {', '.join(assembled.blocks_included)}]"
        return f"{header}\n{assembled.text}\n{footer}"

    except Exception as e:
        log.warning("Context harness failed, using fallback: %s", e)
        return _build_live_context_fallback()


def _fetch_account_state_for_harness() -> dict:
    """Fetch account state + positions in the format context_harness expects."""
    now = time.time()
    if "account_state" in _CACHE and now - _CACHE["account_state"].get("ts", 0) < 10:
        return _CACHE["account_state"]["data"]

    from common.account_resolver import resolve_main_wallet, resolve_vault_address

    main_addr = resolve_main_wallet(required=False)
    total_equity = 0.0
    alerts = []
    positions = []

    if main_addr:
        # Both clearinghouses — equity + positions
        for dex in ['', 'xyz']:
            try:
                payload = {"type": "clearinghouseState", "user": main_addr}
                if dex:
                    payload["dex"] = dex
                r = requests.post("https://api.hyperliquid.xyz/info",
                                  json=payload, timeout=8)
                if r.status_code == 200:
                    data = r.json()
                    total_equity += float(data.get("marginSummary", {}).get("accountValue", 0))
                    for p in data.get("assetPositions", []):
                        pos = p.get("position", {})
                        size = float(pos.get("szi", 0))
                        if size != 0:
                            positions.append({
                                "coin": pos.get("coin", "?"),
                                "size": size,
                                "entry": float(pos.get("entryPx", 0)),
                                "upnl": float(pos.get("unrealizedPnl", 0)),
                                "leverage": pos.get("leverage", {}).get("value", "?") if isinstance(pos.get("leverage"), dict) else pos.get("leverage", "?"),
                                "liq": pos.get("liquidationPx"),
                                "dex": dex or "native",
                            })
            except Exception:
                pass
            time.sleep(0.2)

        # Spot USDC
        try:
            r = requests.post("https://api.hyperliquid.xyz/info",
                              json={"type": "spotClearinghouseState", "user": main_addr},
                              timeout=8)
            if r.status_code == 200:
                for bal in r.json().get("balances", []):
                    if bal.get("coin") == "USDC":
                        total_equity += float(bal.get("total", 0))
        except Exception:
            pass

    # Working state for escalation + alerts
    ws_path = _PROJECT_ROOT / "data" / "memory" / "working_state.json"
    escalation = "L0"
    if ws_path.exists():
        try:
            ws = json.loads(ws_path.read_text())
            escalation = ws.get("escalation_level", "L0")
            if ws.get("heartbeat_consecutive_failures", 0) > 5:
                alerts.append(f"Heartbeat failing ({ws['heartbeat_consecutive_failures']} consecutive)")
        except Exception:
            pass

    result = {
        "account": {"total_equity": total_equity},
        "positions": positions,
        "alerts": alerts,
        "escalation": escalation,
    }
    _CACHE["account_state"] = {"ts": now, "data": result}
    return result


def _refresh_candle_cache(cache, coins: list, intervals: list = None, lookback_hours: int = 168) -> None:
    """Fetch fresh candles from HL API and write to cache.

    Called before every prompt build so technicals are never stale.
    Fetches 1h, 4h, 1d by default — all three needed for full signal engine.
    Only fetches from the last cached candle (or lookback_hours if empty).
    """
    if intervals is None:
        intervals = ["1h", "4h", "1d"]

    now_ms = int(time.time() * 1000)

    for coin in coins:
        for interval in intervals:
            try:
                date_range = cache.date_range(coin, interval)
                if date_range and (now_ms - date_range[1]) < 3_600_000:
                    continue  # Fresh enough

                start_ms = date_range[1] if date_range else now_ms - (lookback_hours * 3_600_000)

                payload = {
                    "type": "candleSnapshot",
                    "req": {"coin": coin, "interval": interval,
                            "startTime": start_ms, "endTime": now_ms},
                }
                r = requests.post("https://api.hyperliquid.xyz/info",
                                  json=payload, timeout=10)
                if r.status_code == 200:
                    candles = r.json()
                    if isinstance(candles, list) and candles:
                        stored = cache.store_candles(coin, interval, candles)
                        if stored:
                            log.info("Refreshed %d %s candles for %s", stored, interval, coin)
                time.sleep(0.15)
            except Exception as e:
                log.debug("Candle refresh failed for %s %s: %s", coin, interval, e)


def _fetch_market_snapshots(positions: Optional[list] = None) -> dict:
    """Fetch rich market snapshots with technicals + position-aware signals.

    Uses build_snapshot + render_snapshot + render_signal_summary to compress
    candle data into actionable text per market. Signal summaries include
    position-specific guidance (e.g. "Signal SUPPORTS your SHORT").
    Falls back to price-only if snapshot building fails.

    FRESHNESS: Fetches fresh candles from HL API before building snapshots
    so technicals are never stale. If candles are still >4h old after refresh,
    skips technicals and shows price-only with a staleness warning.
    """
    now = time.time()
    if "market_snapshots" in _CACHE and now - _CACHE["market_snapshots"].get("ts", 0) < 10:
        return _CACHE["market_snapshots"]["data"]

    snapshots = {}

    # Try rich snapshots first (candle-based technicals)
    try:
        from modules.candle_cache import CandleCache
        from common.market_snapshot import build_snapshot, render_snapshot, render_signal_summary
        cache = CandleCache()

        watchlist = {c: c for c in get_watchlist_coins()}

        # Also include coins with open positions (even if not watchlisted)
        for pos in (positions or []):
            c = pos.get("coin", "")
            if c and c not in watchlist:
                if f"xyz:{c}" not in watchlist:
                    watchlist[c] = c

        # ── FRESH CANDLE INJECTION ──
        # Fetch fresh candles (1h, 4h, 1d) from HL API BEFORE building snapshots
        _refresh_candle_cache(cache, list(watchlist.values()))

        # Get current prices for snapshot building
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

        now_ms = int(time.time() * 1000)
        _MAX_CANDLE_AGE_MS = 4 * 3_600_000  # 4 hours

        for display, key in watchlist.items():
            price = float(prices.get(key, 0))
            if not price:
                continue
            try:
                # ── FRESHNESS GUARD ──
                # Check if candle data is actually fresh enough for technicals
                date_range = cache.date_range(key, "1h")
                if not date_range or (now_ms - date_range[1]) > _MAX_CANDLE_AGE_MS:
                    age_hrs = (now_ms - date_range[1]) / 3_600_000 if date_range else float('inf')
                    snapshots[display] = (
                        f"PRICE ({display}): ${price:,.2f}\n"
                        f"⚠️ TECHNICALS UNAVAILABLE — candle data is {age_hrs:.0f}h stale. "
                        f"Price is LIVE but RSI/BB/signals are unreliable."
                    )
                    continue

                snap = build_snapshot(key, cache, price)
                text = render_snapshot(snap, detail="brief")
                # Find position for this market (if any)
                pos_data = None
                if positions:
                    bare_key = key.replace("xyz:", "")
                    for p in positions:
                        bare_coin = p.get("coin", "").replace("xyz:", "")
                        if bare_coin == bare_key:
                            pos_data = {
                                "direction": "long" if p.get("size", 0) > 0 else "short",
                                "size": abs(p.get("size", 0)),
                            }
                            break
                # Add position-aware signal interpretation
                signal = render_signal_summary(snap, position=pos_data)
                snapshots[display] = f"{text}\n{signal}"
            except Exception:
                snapshots[display] = f"PRICE ({display}): ${price:,.2f}"

    except Exception:
        # Fallback: price-only if snapshot system unavailable
        try:
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
            for k in get_watchlist_coins():
                if k in prices:
                    snapshots[k] = f"PRICE ({k}): ${float(prices[k]):,.2f}"
        except Exception:
            pass

    # Cross-market correlation (BTC vs Oil)
    try:
        from common.market_structure import cross_market_correlation, OHLCV
        if "market_snapshots" not in _CACHE:  # only if we have fresh cache with candle access
            from modules.candle_cache import CandleCache
            cache = CandleCache()
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - (7 * 86_400_000)  # 7 days
            btc_raw = cache.get_candles("BTC", "1h", start_ms, now_ms)
            oil_raw = cache.get_candles("xyz:BRENTOIL", "1h", start_ms, now_ms)
            if btc_raw and oil_raw:
                btc_candles = OHLCV.from_hl_list(btc_raw)
                oil_candles = OHLCV.from_hl_list(oil_raw)
                corr, interp = cross_market_correlation(btc_candles, oil_candles, window=48)
                if abs(corr) > 0.25:  # only show if meaningful
                    snapshots["cross_correlation"] = f"BTC/OIL CORRELATION (48h): {corr:+.2f} — {interp}"
    except Exception:
        pass

    # Add thesis data if available
    thesis_dir = _PROJECT_ROOT / "data" / "thesis"
    if thesis_dir.exists():
        for tf in thesis_dir.glob("*_state.json"):
            try:
                td = json.loads(tf.read_text())
                market = td.get("market", "")
                conv = float(td.get("conviction", 0))
                direction = td.get("direction", "?")
                summary = td.get("summary", "")[:150]
                tp = td.get("take_profit_price")
                sl = td.get("stop_loss_price")
                if conv > 0 and market:
                    thesis_line = f"THESIS ({market}): {direction} conviction={conv:.2f}"
                    if tp:
                        thesis_line += f" TP=${tp}"
                    if sl:
                        thesis_line += f" SL=${sl}"
                    if summary:
                        thesis_line += f" — {summary}"
                    # Attach to matching snapshot or add standalone
                    matched = False
                    for key in snapshots:
                        if market.upper() in key.upper():
                            snapshots[key] += f"\n{thesis_line}"
                            matched = True
                            break
                    if not matched:
                        snapshots[f"thesis_{market}"] = thesis_line
            except Exception:
                pass

    _CACHE["market_snapshots"] = {"ts": now, "data": snapshots}
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
        for k in get_watchlist_coins():
            if k in prices:
                lines.append(f"{k}: ${prices[k]:,.2f}")
    except Exception as e:
        lines.append(f"Prices unavailable: {e}")
    return "\n".join(lines)


def _sanitize_assistant_history(text: str) -> str:
    """Strip stale data snapshots from assistant messages in history.

    Old assistant messages contain data claims (prices, positions, equity)
    that become stale. If fed back as history, the AI repeats stale info
    instead of trusting the fresh LIVE CONTEXT. Strip data-heavy sections
    but keep the conversational analysis and recommendations.
    """
    import re
    # Remove code blocks (often contain ACCOUNT: $xxx, POSITIONS: etc)
    text = re.sub(r'```[^`]*```', '[data snapshot removed]', text, flags=re.DOTALL)
    # Remove inline data lines using dynamic regex to catch Markdown Variations
    lines = text.split('\n')
    clean = []
    
    # Lines matching this regex contain portfolio numbers/data or technical indicators
    data_pattern = re.compile(
        r'^[\s\W]*(Equity|Open Positions|Positions|Direction|Entry|Current|uPnL|Leverage|Liquidation|Account|Price'
        r'|RSI|Signal|VWAP|BB |EMA|ATR|Bollinger|Support|Resist|MECH|FLAGS'
        r'|PRICE OUTLOOK|Money flow|OBV|Volatility|vol_regime)[\s\W]*[:=]',
        re.IGNORECASE
    )

    # Lines containing these are stale claims about data state
    contains = [
        'No position', 'no position', 'POSITIONS: (none',
        'not seeing any open position', 'not show any open',
        'does not show any open', 'position data is',
        'No Position Detected', 'none listed',
        # Stale funding claims from memory (actual data comes from live API)
        '58% annualized', 'earn funding', 'earning funding',
        'paying funding', 'funding costs compound',
        # Stale technical indicators (fresh ones come from LIVE CONTEXT)
        'RSI 69', 'RSI 20', 'RSI:', 'overbought', 'oversold',
        'EXHAUSTION', 'CAPITULATION', 'BEARISH exhaustion', 'BULLISH exhaustion',
        'SIGNAL:', 'STRONGLY BULLISH', 'STRONGLY BEARISH',
        'YOUR SHORT:', 'YOUR LONG:',
    ]
    for line in lines:
        if data_pattern.search(line):
            continue
        if any(p in line for p in contains):
            continue
        clean.append(line)
    return '\n'.join(clean).strip()


def _load_chat_history(limit: int = 20) -> List[Dict]:
    """Load recent chat history from JSONL, respecting token budget.

    Takes the most recent messages that fit within _MAX_HISTORY_CHARS total.
    Assistant messages are sanitized to remove stale data snapshots that
    would poison the AI's understanding of current state.
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

    # Sanitize assistant messages to remove stale data claims
    for entry in recent:
        if entry.get("role") == "assistant":
            entry["text"] = _sanitize_assistant_history(entry["text"])

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


_OR_MAX_RETRIES = 3
_OR_BACKOFF_BASE = 2.0


def _try_fallback_chain(messages: List[Dict], tools: Optional[list] = None):
    """Try each model in the fallback chain. Returns (response, model_name) or (None, None).
    
    IMPORTANT: tools are stripped for fallback models. Free models don't support
    function calling — they return 404, causing infinite retry loops.
    """
    for model in _FALLBACK_CHAIN:
        log.info("Trying fallback: %s", model)
        # Always strip tools for fallback — free models 404 on tool_use requests
        result = _call_openrouter_direct(messages, tools=None, model_override=model)
        content = result.get("content") or ""
        # Skip if rate limited or error
        if "rate limited" in content.lower() or "API error" in content:
            log.warning("Fallback %s failed: %s", model, content[:80])
            continue
        # Got a real response
        short_name = model.split("/")[-1].split(":")[0]
        if content:
            result["content"] = f"[\u26a1 {short_name}] {content}"
        return result, model
    return None, None


def _call_anthropic(messages: List[Dict], tools: Optional[list] = None) -> dict:
    """Call Anthropic Messages API directly for anthropic/* models.

    Converts OpenAI-style messages to Anthropic format and returns
    an OpenAI-compatible message dict for downstream compatibility.
    """
    api_key = _get_anthropic_key()
    if not api_key:
        return {"content": "Error: No Anthropic API key found."}

    model = _get_active_model()
    # Strip "anthropic/" prefix for the Anthropic API
    anthropic_model = model.replace("anthropic/", "", 1)

    # Convert OpenAI-format messages to Anthropic format.
    # Key differences:
    #   OpenAI: role="tool" with tool_call_id + content string
    #   Anthropic: role="user" with [{"type":"tool_result","tool_use_id":...,"content":...}]
    #   OpenAI assistant: tool_calls=[{id, function:{name,arguments}}]
    #   Anthropic assistant: content=[{"type":"tool_use","id":...,"name":...,"input":...}]
    system_text = ""
    conv_messages = []
    pending_tool_results = []  # collect tool results to batch into one user message
    for msg in messages:
        if msg.get("role") == "system":
            system_text += msg.get("content", "") + "\n"
        elif msg.get("role") == "assistant":
            # Flush any pending tool results first
            if pending_tool_results:
                conv_messages.append({"role": "user", "content": pending_tool_results})
                pending_tool_results = []
            # Convert assistant message: may have tool_calls (OpenAI) → tool_use (Anthropic)
            assistant_content = []
            if msg.get("content"):
                assistant_content.append({"type": "text", "text": msg["content"]})
            for tc in msg.get("tool_calls", []):
                fn = tc.get("function", {})
                raw_input = fn.get("arguments", "{}")
                try:
                    parsed_input = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
                except (json.JSONDecodeError, TypeError):
                    parsed_input = {}
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "input": parsed_input,
                })
            conv_messages.append({"role": "assistant", "content": assistant_content or msg.get("content", "")})
        elif msg.get("role") == "tool":
            # Collect tool results — they must be batched into a single user message
            pending_tool_results.append({
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": msg.get("content", ""),
            })
        elif msg.get("role") == "user":
            # Flush any pending tool results first
            if pending_tool_results:
                conv_messages.append({"role": "user", "content": pending_tool_results})
                pending_tool_results = []
            conv_messages.append({"role": "user", "content": msg.get("content", "")})
    # Flush remaining tool results
    if pending_tool_results:
        conv_messages.append({"role": "user", "content": pending_tool_results})

    payload: dict = {
        "model": anthropic_model,
        "max_tokens": _MAX_RESPONSE_TOKENS,
        "messages": conv_messages,
    }
    if system_text.strip():
        payload["system"] = system_text.strip()

    # Convert OpenAI tool format to Anthropic tool format
    if tools:
        anthropic_tools = []
        for t in tools:
            func = t.get("function", {})
            anthropic_tools.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        payload["tools"] = anthropic_tools

    # Session tokens (sk-ant-oat01-...) require OAuth headers — same as claude-cli.
    # Console API keys (sk-ant-api03-...) use x-api-key.
    if api_key.startswith("sk-ant-oat"):
        headers = {
            "Authorization": f"Bearer {api_key}",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "claude-code-20250219,oauth-2025-04-20",
            "x-app": "cli",
            "user-agent": "claude-cli/2.1.75",
            "Content-Type": "application/json",
        }
    else:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    for attempt in range(_OR_MAX_RETRIES):
        try:
            resp = requests.post(
                _ANTHROPIC_URL, json=payload, headers=headers, timeout=60,
            )
            if resp.status_code == 429:
                delay = _OR_BACKOFF_BASE * (2 ** attempt)
                log.warning("Anthropic 429 (attempt %d/%d), backing off %.1fs",
                            attempt + 1, _OR_MAX_RETRIES, delay)
                if attempt < _OR_MAX_RETRIES - 1:
                    time.sleep(delay)
                    continue
                return {"content": "AI rate limited — try again in a minute."}

            if resp.status_code != 200:
                log.error("Anthropic API error: %s %s", resp.status_code, resp.text[:200])
                return {"content": f"Anthropic API error ({resp.status_code}). Try /status for live data."}

            data = resp.json()

            # Convert Anthropic response to OpenAI-compatible format
            content_blocks = data.get("content", [])
            text_parts = []
            tool_calls = []
            for block in content_blocks:
                if block.get("type") == "text":
                    text_parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    })

            result: dict = {"role": "assistant"}
            if text_parts:
                result["content"] = "\n".join(text_parts)
            if tool_calls:
                result["tool_calls"] = tool_calls
            if not text_parts and not tool_calls:
                result["content"] = ""
            return result

        except requests.Timeout:
            return {"content": "AI response timed out. Try /status for instant data."}
        except Exception as e:
            log.error("Anthropic call failed: %s", e)
            return {"content": f"AI call failed: {e}"}

    return {"content": "AI unavailable after retries. Try /status for live data."}


def _call_openrouter(messages: List[Dict], tools: Optional[list] = None) -> dict:
    """Call OpenRouter API with retry/backoff for 429 rate limits.

    Returns the full message dict from the response (may contain tool_calls
    or content). Free models that don't support tools will ignore the tools
    parameter and return a normal content response.

    For anthropic/* models, routes to Anthropic API directly.
    See docs/wiki/operations/api-reference.md for maintenance notes.

    Sets _call_openrouter._last_fallback to the fallback model name if
    Anthropic rate-limited, so the tool loop can stay on the fallback.
    """
    _call_openrouter._last_fallback = None  # reset each call

    # Route anthropic models directly to Anthropic API
    model = _get_active_model()
    if _is_anthropic_model(model):
        result = _call_anthropic(messages, tools)
        # If Anthropic is rate limited, fall back to free model
        if result.get("content", "").startswith("AI rate limited"):
            result, fallback_model = _try_fallback_chain(messages, tools)
            if result:
                _call_openrouter._last_fallback = fallback_model
                return result
            return {"content": "All models busy — try again in a minute. Use /status for instant data."}
        return result

    return _call_openrouter_direct(messages, tools, model_override=model)


def _call_openrouter_direct(
    messages: List[Dict],
    tools: Optional[list] = None,
    model_override: Optional[str] = None,
) -> dict:
    """Raw OpenRouter API call. Used by _call_openrouter and as fallback."""
    api_key = _get_openrouter_key()
    if not api_key:
        return {"content": "Error: No OpenRouter API key found."}

    use_model = model_override or _get_active_model()
    payload: dict = {
        "model": use_model,
        "messages": messages,
        "max_tokens": _MAX_RESPONSE_TOKENS,
        "temperature": 0.3,
    }
    if tools:
        payload["tools"] = tools
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://openclaw.ai",
        "X-Title": "OpenClaw",
    }

    for attempt in range(_OR_MAX_RETRIES):
        try:
            resp = requests.post(
                _OPENROUTER_URL, json=payload, headers=headers, timeout=60,
            )
            if resp.status_code == 429:
                delay = _OR_BACKOFF_BASE * (2 ** attempt)
                log.warning("OpenRouter 429 (attempt %d/%d), backing off %.1fs",
                            attempt + 1, _OR_MAX_RETRIES, delay)
                if attempt < _OR_MAX_RETRIES - 1:
                    time.sleep(delay)
                    continue
                return {"content": "AI rate limited — try again in a minute. Use /status for instant data."}

            if resp.status_code != 200:
                log.error("OpenRouter API error: %s %s", resp.status_code, resp.text[:200])
                return {"content": f"OpenRouter API error ({resp.status_code}). Try /status for live data."}

            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                # Reasoning models may return content=null with reasoning in a separate field
                if not msg.get("content") and not msg.get("tool_calls"):
                    reasoning = msg.get("reasoning") or msg.get("reasoning_content") or ""
                    if reasoning:
                        msg["content"] = reasoning[:_MAX_RESPONSE_TOKENS * 2]  # use reasoning as content
                    else:
                        msg["content"] = "(Model returned empty response. Try again or switch models.)"
                return msg
            return {"content": "No response from model."}
        except requests.Timeout:
            return {"content": "AI response timed out. Try /status for instant data."}
        except Exception as e:
            log.error("OpenRouter call failed: %s", e)
            return {"content": f"AI call failed: {e}"}

    return {"content": "AI unavailable after retries. Try /status for live data."}


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


def _get_anthropic_key() -> Optional[str]:
    """Read Anthropic session token or API key from auth-profiles.json.

    Session tokens (sk-ant-oat01-...) are the preferred credential —
    they are tied to your Anthropic subscription (no per-token billing).
    Console API keys (sk-ant-api03-...) are expensive and not preferred.
    """
    try:
        if _AUTH_PROFILES.exists():
            data = json.loads(_AUTH_PROFILES.read_text())
            profiles = data.get("profiles", {})
            for name, profile in profiles.items():
                if profile.get("provider") == "anthropic":
                    # Prefer token (session) over key (console API)
                    return profile.get("token") or profile.get("key")
    except Exception:
        pass
    import os
    return os.environ.get("ANTHROPIC_API_KEY")


def _is_anthropic_model(model: str) -> bool:
    """Check if a model ID should route to Anthropic directly."""
    return model.startswith("anthropic/") and not model.endswith(":free")


def _get_active_model() -> str:
    """Get the currently selected model from config, or fall back to default."""
    try:
        if _MODEL_CONFIG.exists():
            data = json.loads(_MODEL_CONFIG.read_text())
            model = data.get("model", "")
            if model:
                return model
    except Exception:
        pass
    return _DEFAULT_MODEL


def set_active_model(model_id: str) -> None:
    """Save the selected model to config."""
    _MODEL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _MODEL_CONFIG.write_text(json.dumps({"model": model_id}, indent=2) + "\n")


# Curated model list — free models at top, paid below.
# Free: 20 RPM / ~200 req/day limits. Paid: require OR credit balance.
# To update: see docs/wiki/operations/api-reference.md
_CURATED_MODELS = [
    # ── Free (OpenRouter) ──
    {"id": "stepfun/step-3.5-flash:free", "name": "Step 3.5", "tier": "free"},
    {"id": "qwen/qwen3.6-plus-preview:free", "name": "Qwen 3.6+", "tier": "free"},
    {"id": "qwen/qwen3-coder:free", "name": "Qwen3 Coder", "tier": "free"},
    {"id": "deepseek/deepseek-chat-v3-0324:free", "name": "DeepSeek V3", "tier": "free"},
    {"id": "openai/gpt-oss-120b:free", "name": "GPT-OSS 120B", "tier": "free"},
    {"id": "nvidia/nemotron-3-super-120b-a12b:free", "name": "Nemotron 3", "tier": "free"},
    {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Llama 3.3 70B", "tier": "free"},
    {"id": "nousresearch/hermes-3-llama-3.1-405b:free", "name": "Hermes 405B", "tier": "free"},
    {"id": "google/gemma-3-27b-it:free", "name": "Gemma 3 27B", "tier": "free"},
    {"id": "minimax/minimax-m2.5:free", "name": "MiniMax M2.5", "tier": "free"},
    # ── Anthropic (direct API — free via token) ──
    {"id": "anthropic/claude-opus-4-6", "name": "Opus 4.6", "tier": "anthropic"},
    {"id": "anthropic/claude-sonnet-4-6", "name": "Sonnet 4.6", "tier": "anthropic"},
    {"id": "anthropic/claude-haiku-4-5", "name": "Haiku 4.5", "tier": "anthropic"},
    # ── Paid (OpenRouter credits) ──
    {"id": "google/gemini-2.5-flash", "name": "Gemini Flash", "tier": "paid"},
    {"id": "google/gemini-2.5-pro", "name": "Gemini Pro", "tier": "paid"},
    {"id": "deepseek/deepseek-r1-0528", "name": "DS R1", "tier": "paid"},
    {"id": "deepseek/deepseek-v3.2", "name": "DS V3.2", "tier": "paid"},
    {"id": "openrouter/hunter-alpha", "name": "Hunter", "tier": "paid"},
    {"id": "openrouter/healer-alpha", "name": "Healer", "tier": "paid"},
]


def get_available_models() -> list:
    """Return curated model list for the /models selector.

    Merges the built-in curated list with any extra models from the
    OpenClaw models.json. See docs/wiki/operations/api-reference.md for maintenance.
    """
    models = list(_CURATED_MODELS)
    seen_ids = {m["id"] for m in models}

    # Merge any extra models from OpenClaw models.json
    try:
        if _MODELS_JSON.exists():
            data = json.loads(_MODELS_JSON.read_text())
            or_provider = data.get("providers", {}).get("openrouter", {})
            for m in or_provider.get("models", []):
                if m["id"] not in seen_ids:
                    tier = "free" if ":free" in m["id"] else "paid"
                    models.append({"id": m["id"], "name": m.get("name", m["id"]), "tier": tier})
                    seen_ids.add(m["id"])
    except Exception:
        pass

    return models


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
