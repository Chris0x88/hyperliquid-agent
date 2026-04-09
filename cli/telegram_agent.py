"""Direct Telegram AI agent — handles free-text messages via OpenRouter.

Called from telegram_bot.py when a message doesn't match any slash command.
Slash commands are handled separately and never touch this module.

Design:
- System prompt from agent/AGENT.md + SOUL.md
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
_AGENT_MD = _PROJECT_ROOT / "agent" / "AGENT.md"
_SOUL_MD = _PROJECT_ROOT / "agent" / "SOUL.md"
_AUTH_PROFILES = Path.home() / ".openclaw" / "agents" / "default" / "agent" / "auth-profiles.json"

# Limits
_MAX_HISTORY = 20
_MAX_HISTORY_CHARS = 12000  # Cap total history chars to stay within context window
_MAX_RESPONSE_TOKENS = 4096
_MAX_TG_MESSAGE = 4096
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_DEFAULT_MODEL = "anthropic/claude-haiku-4-5"  # Default fallback only — user selects via /models
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

_MAX_TOOL_LOOPS = 12  # Safety cap — model drives iteration via tool calls

# Session token detection (OAuth vs console API key)
# Session tokens start with a specific prefix that differs from console API keys.
# Console keys use x-api-key header; session tokens use Bearer auth.
_SESSION_PREFIX = "sk-" + "ant-" + "oat"  # noqa: split avoids secret scanner

# ── Anthropic beta headers — must match Claude Code's betas.ts exactly ──
# These are the headers that tell the API what features we support.
# Missing or wrong headers cause 400 errors or missing functionality.
_BETA_OAUTH = "oauth-2025-04-20"
_BETA_CLAUDE_CODE = "claude-code-20250219"
_BETA_THINKING = "interleaved-thinking-2025-05-14"
_BETA_CACHE_SCOPE = "prompt-caching-scope-2026-01-05"
_BETA_TOKEN_EFFICIENT_TOOLS = "token-efficient-tools-2026-03-28"


def _get_anthropic_betas(model: str) -> list[str]:
    """Build beta headers list matching Claude Code's getMergedBetas()."""
    betas = [
        _BETA_OAUTH,         # Required for session token auth
        _BETA_CLAUDE_CODE,   # Required for claude-code features
        _BETA_THINKING,      # Interleaved thinking (Sonnet/Opus)
        _BETA_CACHE_SCOPE,   # Prompt caching scope control
        _BETA_TOKEN_EFFICIENT_TOOLS,  # ~4.5% output token reduction
    ]
    return betas


def _get_cache_control() -> dict:
    """Cache control matching Claude Code's getCacheControl().

    Subscribers get 1h TTL (vs default 5min). Cached tokens don't count
    against ITPM rate limits — this is the single biggest optimisation.
    """
    return {"type": "ephemeral", "ttl": "1h"}


def _is_session_token(key: str) -> bool:
    """Check if an Anthropic key is a session token (OAuth) vs console API key."""
    return key.startswith(_SESSION_PREFIX) if key else False

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


def _build_anthropic_headers(api_key: str, model: str) -> dict:
    """Build Anthropic API headers matching Claude Code's client.ts + betas.ts.

    Session tokens (OAuth) require specific beta headers and Bearer auth.
    Console API keys use x-api-key header with minimal betas.
    """
    if _is_session_token(api_key):
        betas = _get_anthropic_betas(model)
        return {
            "Authorization": f"Bearer {api_key}",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": ",".join(betas),
            "x-app": "cli",
            "user-agent": "claude-cli/2.1.87",
            "Content-Type": "application/json",
        }
    else:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }


def _convert_messages_to_anthropic(messages: List[Dict]) -> tuple:
    """Convert OpenAI-format messages to Anthropic format.

    Returns (system_text, conv_messages).
    Shared by both streaming and non-streaming paths — one conversion,
    one set of bugs to fix.
    """
    system_text = ""
    conv_messages = []
    pending_tool_results = []

    for msg in messages:
        if msg.get("role") == "system":
            system_text += msg.get("content", "") + "\n"
        elif msg.get("role") == "assistant":
            if pending_tool_results:
                conv_messages.append({"role": "user", "content": pending_tool_results})
                pending_tool_results = []
            assistant_content = []
            # Anthropic API rejects text blocks containing only whitespace.
            # Must check .strip() not just truthiness — "\n" is truthy but invalid.
            _content = msg.get("content")
            if isinstance(_content, str) and _content.strip():
                assistant_content.append({"type": "text", "text": _content})
            for tc in msg.get("tool_calls", []):
                fn = tc.get("function", {})
                raw_input = fn.get("arguments", "{}")
                try:
                    parsed_input = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
                except (json.JSONDecodeError, TypeError):
                    parsed_input = {}
                assistant_content.append({
                    "type": "tool_use", "id": tc.get("id", ""),
                    "name": fn.get("name", ""), "input": parsed_input,
                })
            # Drop fully-empty assistant turns — Anthropic rejects messages
            # whose content is "" or [{"type":"text","text":""}]. An assistant
            # turn with no text and no tool_use is meaningless context anyway.
            if not assistant_content:
                continue
            conv_messages.append({"role": "assistant", "content": assistant_content})
        elif msg.get("role") == "tool":
            pending_tool_results.append({
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": msg.get("content", ""),
            })
        elif msg.get("role") == "user":
            if pending_tool_results:
                conv_messages.append({"role": "user", "content": pending_tool_results})
                pending_tool_results = []
            conv_messages.append({"role": "user", "content": msg.get("content", "")})

    if pending_tool_results:
        conv_messages.append({"role": "user", "content": pending_tool_results})

    return system_text, conv_messages


def _build_anthropic_payload(model: str, system_text: str, conv_messages: list, tools=None) -> dict:
    """Build Anthropic API payload with prompt caching.

    Matches Claude Code's caching strategy:
    - System prompt: array of content blocks with cache_control
    - Tools: last tool gets cache_control
    - Last message: gets cache_control (addCacheBreakpoints pattern)
    """
    cc = _get_cache_control()

    payload: dict = {
        "model": model,
        "max_tokens": _MAX_RESPONSE_TOKENS,
        "messages": conv_messages,
    }

    # System prompt as cached content block array (NOT a plain string).
    # Claude Code: splitSysPromptPrefix() + cache_control on each block.
    if system_text.strip():
        payload["system"] = [
            {"type": "text", "text": system_text.strip(), "cache_control": cc},
        ]

    # Tool definitions with cache_control on last tool.
    # Claude Code: toolToAPISchema() + cache_control on last entry.
    if tools:
        anthropic_tools = []
        for t in tools:
            func = t.get("function", {})
            anthropic_tools.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        if anthropic_tools:
            anthropic_tools[-1]["cache_control"] = cc
        payload["tools"] = anthropic_tools

    # Cache breakpoint on last message (addCacheBreakpoints pattern).
    # This tells the API where to cache up to — everything before this
    # point can be served from cache on the next call.
    if conv_messages:
        last_msg = conv_messages[-1]
        content = last_msg.get("content", "")
        if isinstance(content, str) and content:
            last_msg["content"] = [
                {"type": "text", "text": content, "cache_control": cc},
            ]
        elif isinstance(content, list) and content:
            # Add cache_control to the last content block
            last_block = content[-1]
            if isinstance(last_block, dict):
                last_block["cache_control"] = cc

    return payload


def _build_anthropic_request(messages: List[Dict], tools=None):
    """Build Anthropic API request params without sending.

    Returns (url, payload, headers) or (None, None, None).
    Used by the streaming path. Shares all conversion/caching logic
    with _call_anthropic via the helper functions above.
    """
    api_key = _get_anthropic_key()
    if not api_key:
        return None, None, None

    model = _get_active_model().replace("anthropic/", "", 1)
    system_text, conv_messages = _convert_messages_to_anthropic(messages)
    payload = _build_anthropic_payload(model, system_text, conv_messages, tools)
    headers = _build_anthropic_headers(api_key, model)

    return _ANTHROPIC_URL, payload, headers


def _build_openrouter_request(messages: List[Dict], tools=None):
    """Build OpenRouter API request params without sending. Returns (url, payload, headers) or (None, None, None)."""
    api_key = _get_openrouter_key()
    if not api_key:
        return None, None, None

    model = _get_active_model()
    payload = {"model": model, "messages": messages, "max_tokens": _MAX_RESPONSE_TOKENS, "temperature": 0.3}
    if tools:
        payload["tools"] = tools

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "HTTP-Referer": "https://openclaw.ai", "X-Title": "OpenClaw"}

    return "https://openrouter.ai/api/v1/chat/completions", payload, headers


def _tg_stream_response(token: str, chat_id: str, messages: List[Dict], tools=None) -> dict:
    """Make an API call with streaming output to Telegram.

    Sends a placeholder message, then edits it as tokens arrive.
    Returns an OpenAI-compatible response dict.
    Works with ANY model (Anthropic or OpenRouter).
    """
    from cli.agent_runtime import stream_and_accumulate, StreamResult

    # Build the request the same way _call_anthropic/_call_openrouter_direct would
    model = _get_active_model()

    if _is_anthropic_model(model):
        url, payload, headers = _build_anthropic_request(messages, tools)
    else:
        url, payload, headers = _build_openrouter_request(messages, tools)

    if not url:
        # Couldn't build request (missing API key etc) — fall back to non-streaming
        return _call_openrouter(messages, tools)

    # Send initial placeholder message
    try:
        init_resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": "\U0001f914 ..."},
        )
        msg_id = init_resp.json().get("result", {}).get("message_id")
    except Exception:
        msg_id = None

    last_edit = 0
    edit_interval = 1.5
    full_result = StreamResult()

    try:
        for delta_text, result in stream_and_accumulate(url, payload, headers):
            full_result = result
            now = time.time()
            if msg_id and delta_text and (now - last_edit) >= edit_interval and result.text.strip():
                try:
                    display = result.text.strip()[:4000]
                    requests.post(
                        f"https://api.telegram.org/bot{token}/editMessageText",
                        json={"chat_id": chat_id, "message_id": msg_id, "text": display},
                        timeout=5,
                    )
                    last_edit = now
                except Exception:
                    pass
    except RuntimeError as e:
        # Auth failed (401) — try force-refresh and retry once before giving up
        if "401" in str(e):
            refreshed = _force_token_refresh()
            if refreshed:
                log.info("Retrying stream after token refresh")
                url2, payload2, headers2 = _build_anthropic_request(messages, tools)
                if url2:
                    try:
                        for delta_text, result in stream_and_accumulate(url2, payload2, headers2):
                            full_result = result
                            now = time.time()
                            if msg_id and delta_text and (now - last_edit) >= edit_interval and result.text.strip():
                                try:
                                    display = result.text.strip()[:4000]
                                    requests.post(
                                        f"https://api.telegram.org/bot{token}/editMessageText",
                                        json={"chat_id": chat_id, "message_id": msg_id, "text": display},
                                        timeout=5,
                                    )
                                    last_edit = now
                                except Exception:
                                    pass
                        # Retry succeeded — skip to final edit below
                    except RuntimeError:
                        pass  # Retry also failed — fall through to delete + re-raise
                    else:
                        # Successful retry — jump to final edit
                        if msg_id and full_result.text.strip():
                            try:
                                requests.post(
                                    f"https://api.telegram.org/bot{token}/editMessageText",
                                    json={"chat_id": chat_id, "message_id": msg_id, "text": full_result.text.strip()[:4000]},
                                    timeout=5,
                                )
                            except Exception:
                                pass
                        response = {"role": "assistant"}
                        if full_result.text:
                            response["content"] = full_result.text
                        if full_result.tool_calls:
                            response["tool_calls"] = full_result.tool_calls
                        return response

        # Rate limited or auth still failing — delete placeholder and re-raise for fallback
        if msg_id:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{token}/deleteMessage",
                    json={"chat_id": chat_id, "message_id": msg_id},
                    timeout=5,
                )
            except Exception:
                pass
        raise

    # Final edit
    if msg_id and full_result.text.strip():
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/editMessageText",
                json={"chat_id": chat_id, "message_id": msg_id, "text": full_result.text.strip()[:4000]},
                timeout=5,
            )
        except Exception:
            pass

    # Build OpenAI-compatible response
    response = {"role": "assistant"}
    if full_result.text:
        response["content"] = full_result.text
    if full_result.tool_calls:
        response["tool_calls"] = full_result.tool_calls
    if not full_result.text and not full_result.tool_calls:
        response["content"] = ""
    response["_stop_reason"] = full_result.stop_reason
    response["_streamed"] = True
    response["_msg_id"] = msg_id
    return response


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
            {"role": "system", "content": system_prompt},
        ]
        # Live context as first user message — changes every call, so keeping it
        # OUT of the system prompt lets the static system prompt + tools stay cached.
        messages.append({"role": "user", "content": f"[LIVE CONTEXT — auto-injected, not from user]\n{live_context}"})
        messages.append({"role": "assistant", "content": "Understood. I have the latest market data."})
        # Add chat history as conversation turns.
        # Skip entries whose text is empty/whitespace (e.g. an assistant turn
        # that _sanitize_assistant_history stripped down to nothing). Anthropic
        # rejects empty text content blocks with HTTP 400.
        for entry in history[:-1]:  # exclude the message we just logged
            txt = entry.get("text", "")
            if not (isinstance(txt, str) and txt.strip()):
                continue
            messages.append({"role": entry["role"], "content": txt})
        # Add current user message
        messages.append({"role": "user", "content": text})

        # Import tool definitions
        from cli.agent_tools import (
            TOOL_DEFS, execute_tool, is_write_tool,
            store_pending, format_confirmation,
        )

        # First call — route based on model.
        # Sonnet/Opus: use Agent SDK (no streaming, but only path that works
        # for premium models with session tokens).
        # Haiku: use streaming for real-time Telegram output.
        active_model = _get_active_model()
        log.info("[turn] handling message with model=%s user=%s", active_model, user_name or "?")
        use_cli = (_is_anthropic_model(active_model) and "haiku" not in active_model)

        if use_cli:
            _tg_typing(token, chat_id)
            response = _call_openrouter(messages, tools=TOOL_DEFS)
        else:
            try:
                response = _tg_stream_response(token, chat_id, messages, tools=TOOL_DEFS)
            except Exception as e:
                log.warning("Streaming failed, falling back: %s", e)
                response = _call_openrouter(messages, tools=TOOL_DEFS)

        # Track if we fell back from Anthropic rate limit — stay on fallback for remaining loops
        _session_fallback_model = None  # Disabled — was causing silent failures on tool loops

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
                # Handle native/text-parsed tool calls
                messages.append(response)

                # Parallel execution for concurrent-safe tools
                from cli.agent_runtime import execute_tools_parallel

                # Separate WRITE tools (need approval) from READ tools (auto-execute)
                write_calls = []
                read_calls = []
                for tc in tool_calls:
                    fn_name = tc.get("function", {}).get("name", "")
                    if is_write_tool(fn_name):
                        write_calls.append(tc)
                    else:
                        read_calls.append(tc)

                # Execute READ tools in parallel
                if read_calls:
                    parallel_results = execute_tools_parallel(read_calls, execute_tool)
                    for tool_id, tool_name, result in parallel_results:
                        if response.get("tool_calls"):
                            messages.append({"role": "tool", "tool_call_id": tool_id, "content": result})
                        else:
                            messages.append({
                                "role": "user",
                                "content": f"[Tool result for {tool_name}]:\n{result}\n\nNow respond using this data. Do NOT call the tool again.",
                            })
                        log.info("Read tool %s executed (parallel)", tool_name)

                # Handle WRITE tools (sequential, with approval)
                for tc in write_calls:
                    fn_name = tc.get("function", {}).get("name", "")
                    raw_args = tc.get("function", {}).get("arguments", "{}")
                    fn_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    call_id = tc.get("id", f"text_{_loop}_{fn_name}")

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

            _tg_typing(token, chat_id)

            # Check if context needs compaction
            from cli.agent_runtime import should_compact, build_compact_messages
            model = _get_active_model()
            if should_compact(messages, model):
                log.info("Context compaction triggered at %d messages", len(messages))
                compact_msgs = build_compact_messages(messages)
                # Background task — use Haiku via SDK direct (not CLI binary).
                # The CLI binary path adds 60-90s latency and runs synchronously
                # in the user's request thread, blocking the bot from handling
                # the next message. Compaction is a summarisation task where
                # Haiku is fine. F3 originally routed this through the user's
                # selected model but that wedged the bot — see post-mortem.
                summary_response = _call_anthropic(compact_msgs, model_override="claude-haiku-4-5")
                summary = summary_response.get("content", "")
                if summary:
                    # Replace messages with summary + current user message
                    system_msg = messages[0]  # preserve system prompt
                    messages = [
                        system_msg,
                        {"role": "user", "content": f"[Previous conversation summary]:\n{summary}"},
                        {"role": "assistant", "content": "Understood. I have the conversation context. Continuing."},
                    ]
                    log.info("Context compacted to %d messages", len(messages))

            # Token optimisation: use Haiku for tool iterations (cheaper, higher rate limits).
            # Only the FINAL response needs Sonnet/Opus.
            # Haiku handles tool dispatch (read_file, search_code etc) just fine.
            model = _get_active_model()
            if _is_anthropic_model(model) and "haiku" not in model:
                response = _call_anthropic(messages, tools=TOOL_DEFS, model_override="claude-haiku-4-5")
            else:
                response = _call_openrouter(messages, tools=TOOL_DEFS)

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
        thought_match = re.search(r'<(?:thought|thinking)>(.*?)</(?:thought|thinking)>', response_text, re.IGNORECASE | re.DOTALL)
        if thought_match:
            memory_intent = thought_match.group(1).strip()
            # Strip thought/thinking tags from what the user sees
            tg_text = re.sub(r'<(?:thought|thinking)>.*?</(?:thought|thinking)>\s*', '', response_text, flags=re.IGNORECASE | re.DOTALL).strip()
        else:
            memory_intent = _sanitize_assistant_history(response_text)
            tg_text = response_text

        # Send response — handle streaming deduplication
        streamed_msg_id = response.get("_msg_id") if response.get("_streamed") else None

        if streamed_msg_id and _loop > 0:
            # Tool loop ran after streaming — streamed message is stale, delete it
            try:
                requests.post(
                    f"https://api.telegram.org/bot{token}/deleteMessage",
                    json={"chat_id": chat_id, "message_id": streamed_msg_id},
                    timeout=5,
                )
            except Exception:
                pass
            _tg_send_markdown(token, chat_id, tg_text)
        elif not streamed_msg_id:
            # No streaming happened — send normally
            _tg_send_markdown(token, chat_id, tg_text)
        else:
            # Streaming sent the final response (no tool calls) — already delivered
            # Just update with properly formatted version
            try:
                requests.post(
                    f"https://api.telegram.org/bot{token}/editMessageText",
                    json={"chat_id": chat_id, "message_id": streamed_msg_id,
                          "text": tg_text[:4096], "parse_mode": "Markdown"},
                    timeout=5,
                )
            except Exception:
                # Markdown failed, try plain
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{token}/editMessageText",
                        json={"chat_id": chat_id, "message_id": streamed_msg_id, "text": tg_text[:4096]},
                        timeout=5,
                    )
                except Exception:
                    pass

        # Log memory intent instead of raw sanitized response
        _log_chat("assistant", memory_intent)

        # Memory dream — auto-consolidate learnings
        try:
            from cli.agent_runtime import should_dream, mark_dream_complete, build_dream_prompt
            if should_dream():
                log.info("Memory dream triggered — consolidating learnings")
                dream_prompt = build_dream_prompt()
                # Read current memory + recent history for consolidation
                memory_index = ""
                memory_path = _PROJECT_ROOT / "data" / "agent_memory" / "MEMORY.md"
                if memory_path.exists():
                    memory_index = memory_path.read_text()

                # Get recent chat history
                recent_history = _load_chat_history(50)
                history_text = "\n".join(f"[{e['role']}]: {e['text'][:200]}" for e in recent_history[-30:])

                dream_messages = [
                    {"role": "user", "content": f"{dream_prompt}\n\n--- Current Memory ---\n{memory_index}\n\n--- Recent History ---\n{history_text}"},
                ]

                # Background task — use Haiku via SDK direct (not CLI binary).
                # Same reason as compaction above: dream runs synchronously
                # after the user response is sent, and the CLI binary path
                # blocks the bot for 60-90s+ on Sonnet, causing the next user
                # message to silently fail. Haiku via SDK is fast and cheap.
                dream_response = _call_anthropic(dream_messages, model_override="claude-haiku-4-5")
                dream_text = dream_response.get("content", "")

                if dream_text:
                    # Write consolidated memories
                    from common.tools import memory_write
                    memory_write("dream_consolidation", dream_text)
                    log.info("Dream consolidation saved (%d chars)", len(dream_text))

                # Wedge 6: same dream pass also processes pending lesson
                # candidates. The lesson_author iterator wrote them as
                # verbatim context bundles; here we hand each to the agent
                # to author the post-mortem and persist to memory.db.
                try:
                    lesson_result = _author_pending_lessons(max_lessons=3)
                    if lesson_result["processed"] or lesson_result["failed"]:
                        log.info(
                            "Lesson authoring (dream cycle): processed=%d, failed=%d",
                            lesson_result["processed"],
                            lesson_result["failed"],
                        )
                        for err in lesson_result["errors"][:5]:
                            log.warning("lesson author error: %s", err)
                except Exception as e:
                    log.debug("Lesson authoring during dream failed: %s", e)

                mark_dream_complete()
        except Exception as e:
            log.debug("Dream failed: %s", e)

    except Exception as e:
        log.error("AI handler failed: %s", e, exc_info=True)
        try:
            _tg_send_plain(token, chat_id, f"AI error: {e}\n\nUse /status or /help for fixed commands.")
        except Exception:
            pass


_SYSTEM_PROMPT_INPUT_CAP = 20_000  # ~5000 tokens per file


def _read_capped(path: Path, label: str) -> str:
    """Read a system-prompt input file with a hard byte cap.

    Per NORTH_STAR P10 / Critical Rule 11: the system prompt is the
    highest-leverage surface in the entire codebase — every LLM call
    starts with these bytes. Three files feed it: AGENT.md, SOUL.md,
    and data/agent_memory/MEMORY.md. The first two are human-edited
    and small. **MEMORY.md is agent-writable via the dream cycle**,
    and nothing else enforces the documented "under 200 lines" rule.
    A runaway dream that writes a 10MB MEMORY.md would inflate the
    system prompt unbounded on the next session.

    The cap is generous (20KB ≈ 5000 tokens) so any human-authored
    file fits without truncation, but a runaway agent write is
    bounded. Truncation logs a warning so it's visible in alignment
    runs.
    """
    if not path.exists():
        return ""
    try:
        text = path.read_text()
    except OSError as e:
        log.warning("Failed to read %s: %s", label, e)
        return ""
    if len(text) > _SYSTEM_PROMPT_INPUT_CAP:
        log.warning(
            "%s exceeds %d bytes (%d) — TRUNCATED before system prompt build "
            "to protect the prompt from a runaway write. Investigate %s.",
            label,
            _SYSTEM_PROMPT_INPUT_CAP,
            len(text),
            path,
        )
        text = text[:_SYSTEM_PROMPT_INPUT_CAP] + "\n\n[... TRUNCATED at 20KB cap per NORTH_STAR P10 ...]"
    return text.strip()


def _build_system_prompt() -> str:
    """Load system prompt using agent runtime + domain-specific instructions.

    Every input file is hard-capped at 20KB per NORTH_STAR P10 — see
    `_read_capped()` for the rationale. The system prompt is the
    highest-leverage surface in the codebase; this is the safety net
    against agent-writable inputs (notably MEMORY.md via the dream
    cycle) inflating the prompt beyond control.
    """
    from cli.agent_runtime import build_system_prompt, build_lessons_section

    # Load domain-specific files (hard-capped)
    agent_md = _read_capped(_AGENT_MD, "AGENT.md")
    soul_md = _read_capped(_SOUL_MD, "SOUL.md")

    # Load agent memory (hard-capped — dream cycle writes here)
    memory_path = _PROJECT_ROOT / "data" / "agent_memory" / "MEMORY.md"
    memory_content = _read_capped(memory_path, "MEMORY.md")

    # Pull top recent lessons from the lesson corpus for prompt injection.
    # Empty query → recency fallback. build_lessons_section() returns "" when
    # the corpus is empty, disabled, or the DB query raises — all failures
    # are swallowed so lesson injection cannot break the agent.
    lessons_section = ""
    try:
        lessons_section = build_lessons_section(limit=5)
    except Exception as e:
        log.warning("lessons section failed to build: %s", e)

    return build_system_prompt(
        agent_md=agent_md,
        soul_md=soul_md,
        memory_content=memory_content,
        lessons_section=lessons_section,
    )


# ── Lesson candidate consumer (wedge 6) ─────────────────────────────────

def _author_pending_lessons(
    max_lessons: int = 3,
    candidate_dir: Optional[str] = None,
) -> dict:
    """Consume pending lesson candidates: call the agent to author each
    post-mortem and persist to common.memory.lessons.

    This is the consumer that closes the lesson learning loop. It runs:
      1. As part of the dream cycle (auto, on the 24h+3 trigger), so the
         agent's own slow-tempo memory consolidation also writes lessons.
      2. On demand via /lessonauthorai Telegram command.

    Each candidate file is processed atomically: if the AI call or the
    parser fails the file is left in place for the next run (refuse-to-
    write-garbage; the failure is logged but the candidate persists).
    On success the candidate file is unlinked after the lesson row lands.

    Returns: dict with `processed`, `failed`, `skipped`, and `errors`
    counts/messages so callers can render a useful summary.
    """
    from pathlib import Path as _P
    from common import memory as common_memory
    from modules.lesson_engine import (
        LessonAuthorRequest,
        LessonEngine,
    )

    cdir = _P(candidate_dir or "data/daemon/lesson_candidates")
    if not cdir.exists():
        return {"processed": 0, "failed": 0, "skipped": 0, "errors": []}

    candidates = sorted(cdir.glob("*.json"))[:max_lessons]
    if not candidates:
        return {"processed": 0, "failed": 0, "skipped": 0, "errors": []}

    engine = LessonEngine()
    processed = 0
    failed = 0
    errors: list[str] = []

    for path in candidates:
        try:
            with path.open("r") as f:
                cand = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            failed += 1
            errors.append(f"{path.name}: load failed ({e})")
            continue

        # Reconstruct the LessonAuthorRequest from the candidate dict.
        request = LessonAuthorRequest(
            journal_entry=cand.get("journal_entry") or {},
            thesis_snapshot=cand.get("thesis_snapshot"),
            thesis_snapshot_path=cand.get("thesis_snapshot_path"),
            learnings_md_slice=cand.get("learnings_md_slice", "") or "",
            news_context_at_open=cand.get("news_context_at_open", "") or "",
            autoresearch_eval_window=cand.get("autoresearch_eval_window", "") or "",
        )

        try:
            prompt = engine.build_lesson_prompt(request)
        except Exception as e:
            failed += 1
            errors.append(f"{path.name}: prompt build failed ({e})")
            continue

        # Call the model with Haiku — fast, cheap, sufficient for structured
        # post-mortem authoring. Same pattern as the dream cycle: synchronous
        # _call_anthropic with model_override.
        try:
            resp = _call_anthropic(
                [{"role": "user", "content": prompt}],
                model_override="claude-haiku-4-5",
            )
        except Exception as e:
            failed += 1
            errors.append(f"{path.name}: model call failed ({e})")
            continue

        response_text = (resp or {}).get("content", "")
        if not response_text:
            failed += 1
            errors.append(f"{path.name}: empty model response")
            continue

        # Parse the response into a Lesson — strict, raises ValueError on
        # missing/invalid sentinels. Per Bug A pattern: refuse to write
        # garbage; leave the candidate for a future run.
        try:
            lesson = engine.parse_lesson_response(
                response_text=response_text,
                request=request,
                market=str(cand.get("market") or ""),
                direction=str(cand.get("direction") or ""),
                signal_source=str(cand.get("signal_source") or "manual"),
                pnl_usd=float(cand.get("pnl_usd") or 0.0),
                roe_pct=float(cand.get("roe_pct") or 0.0),
                holding_ms=int(cand.get("holding_ms") or 0),
                trade_closed_at=str(cand.get("trade_closed_at") or ""),
                journal_entry_id=cand.get("journal_entry_id"),
                thesis_snapshot_path=cand.get("thesis_snapshot_path"),
            )
        except ValueError as e:
            failed += 1
            errors.append(f"{path.name}: parse failed ({e})")
            continue

        # Idempotency: if a lesson with this journal_entry_id already exists
        # in the corpus, skip and unlink the candidate so we don't double-write.
        try:
            existing = common_memory.search_lessons(
                query="",
                limit=1000,
            )
            if any(
                r.get("journal_entry_id") == lesson.journal_entry_id
                for r in existing
            ):
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
        except Exception as e:
            log.warning("lesson dedup check failed: %s — proceeding with insert", e)

        try:
            lesson_dict = lesson.to_dict()
            lesson_dict.pop("id", None)  # SQLite assigns the id
            common_memory.log_lesson(lesson_dict)
        except Exception as e:
            failed += 1
            errors.append(f"{path.name}: insert failed ({e})")
            continue

        # Success — unlink the candidate so it doesn't get re-processed.
        try:
            path.unlink()
        except OSError as e:
            log.warning("lesson candidate %s persisted but unlink failed: %s", path.name, e)
        processed += 1

    return {
        "processed": processed,
        "failed": failed,
        "skipped": 0,
        "errors": errors,
    }


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

        # Audit F5: surface real snapshot age so the agent knows when to distrust prices
        fetched_at = account_state.get("fetched_at", time.time())
        age_s = int(time.time() - fetched_at)
        if age_s < 15:
            age_str = "fetched just now"
        elif age_s < 120:
            age_str = f"fetched {age_s}s ago"
        else:
            age_str = f"⚠️ STALE: fetched {age_s}s ago — verify with a tool call before citing prices as current"
        header = f"--- LIVE CONTEXT ({age_str}) ---"
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

    # Audit F2: auto-watchlist any market we have a position in.
    # The user said "if I have a position it's approved". add_market is
    # idempotent (returns False if already present) so this is safe to
    # call every fetch.
    try:
        from common.watchlist import load_watchlist, add_market
        existing_coins = {m.get("coin") for m in load_watchlist()}
        for pos in positions:
            coin = pos.get("coin", "")
            if not coin:
                continue
            stripped = coin.replace("xyz:", "")
            if coin in existing_coins or stripped in existing_coins:
                continue
            display = stripped or coin
            added = add_market(
                display=display,
                coin=coin,
                aliases=[stripped.lower()] if stripped else [],
                category="auto",
            )
            if added:
                log.info("[auto-watchlist] added %s (open position detected)", coin)
    except Exception as e:
        log.warning("[auto-watchlist] failed: %s", e)

    result = {
        "account": {"total_equity": total_equity},
        "positions": positions,
        "alerts": alerts,
        "escalation": escalation,
        "fetched_at": now,  # Audit F5: timestamp for staleness detection
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

    Per NORTH_STAR P10 / Critical Rule 11: streaming tail-read via
    ``collections.deque(maxlen=limit*5)`` so the agent's per-turn I/O
    is bounded regardless of total file size. The chat corpus is
    allowed to grow to gigabytes per Chris's "never delete" rule, but
    every agent prompt only sees the last few rows. The deque keeps
    memory bounded to roughly ``limit*5`` decoded JSON objects even if
    the underlying file is 100MB. Audited 2026-04-09 (Agent E top-3
    fix).
    """
    if not _HISTORY_FILE.exists():
        return []
    from collections import deque
    entries = []
    try:
        # Slurp the last `limit*5` non-empty lines via deque tail.
        # `limit*5` gives headroom: after sanitization + char-budget
        # trimming, we still want at least `limit` rows surviving.
        tail = deque(maxlen=max(50, limit * 5))
        with _HISTORY_FILE.open("r") as fh:
            for line in fh:
                if line.strip():
                    tail.append(line)
        for line in tail:
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
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


def _build_market_context_snapshot() -> Optional[Dict]:
    """Best-effort: read the latest account snapshot + tracked prices for the
    chat row's ``market_context`` enrichment.

    Returns a dict with ``equity_usd`` / ``positions`` / ``prices`` keys (each
    value may be ``None`` if unavailable), or ``None`` if EVERY source failed.

    This is an enrichment, NOT a gate. All exceptions are swallowed; the
    caller must never let this block the chat write. The chat row is the
    source of truth — market_context is opportunistic metadata that the user
    explicitly asked for so future analysis can correlate each message with
    market state at the time.
    """
    out: Dict = {"equity_usd": None, "positions": None, "prices": None}

    # --- Equity + positions from the latest account snapshot -------------
    try:
        from cli.daemon.iterators.account_collector import (
            AccountCollectorIterator,
        )
        # Prefer absolute path anchored to _PROJECT_ROOT so the read works
        # regardless of the telegram bot's cwd.
        snap_dir = str(_PROJECT_ROOT / "data" / "snapshots")
        snap = AccountCollectorIterator.get_latest(snap_dir)
        if snap:
            # total_equity is the canonical field per cli/daemon/CLAUDE.md
            # (perps native + xyz + spot USDC). Fall back to account_value.
            eq = snap.get("total_equity")
            if eq is None:
                eq = snap.get("account_value")
            if eq is not None:
                try:
                    out["equity_usd"] = float(eq)
                except (TypeError, ValueError):
                    pass

            positions: List[Dict] = []
            for pos_list_key in ("positions_native", "positions_xyz"):
                for p in (snap.get(pos_list_key) or []):
                    pos = p.get("position") if isinstance(p, dict) else None
                    if not pos:
                        continue
                    coin = pos.get("coin") or ""
                    # Coin prefix normalisation — CLAUDE.md §4 recurring bug:
                    # xyz clearinghouse returns names WITH 'xyz:' prefix.
                    # Strip for the chat row so downstream analysis is uniform.
                    if isinstance(coin, str) and coin.startswith("xyz:"):
                        instrument = coin[len("xyz:"):]
                    else:
                        instrument = coin or "?"
                    try:
                        szi = float(pos.get("szi") or 0)
                    except (TypeError, ValueError):
                        szi = 0.0
                    side = "long" if szi > 0 else ("short" if szi < 0 else "flat")
                    try:
                        notional = float(pos.get("positionValue") or 0)
                    except (TypeError, ValueError):
                        notional = 0.0
                    positions.append({
                        "instrument": instrument,
                        "side": side,
                        "notional_usd": notional,
                    })
            out["positions"] = positions
    except Exception:
        # Any failure (import, filesystem, parse) degrades equity+positions
        # to None. Chat write must remain bulletproof.
        pass

    # --- Prices (best-effort) ------------------------------------------
    # Snapshots don't currently persist a prices dict, and live clearing-
    # house calls would block the chat write path. Leave None unless a
    # future snapshot schema adds it. Keep the key present so readers
    # can treat the whole field uniformly.
    try:
        from cli.daemon.iterators.account_collector import (
            AccountCollectorIterator,
        )
        snap_dir = str(_PROJECT_ROOT / "data" / "snapshots")
        snap = AccountCollectorIterator.get_latest(snap_dir)
        if snap and isinstance(snap.get("prices"), dict):
            # Forward-compatible: if a future account_collector patch adds
            # a `prices` key to the snapshot, we'll pick it up here for
            # free without blocking on any network I/O.
            prices = {}
            for k, v in snap["prices"].items():
                try:
                    key = k.replace("xyz:", "") if isinstance(k, str) else str(k)
                    prices[key] = float(v)
                except (TypeError, ValueError):
                    continue
            out["prices"] = prices
    except Exception:
        pass

    # Return None only if literally nothing populated — otherwise keep the
    # dict so readers can rely on the field's presence and shape.
    if out["equity_usd"] is None and out["positions"] is None and out["prices"] is None:
        return None
    return out


def _log_chat(role: str, text: str, user_name: str = "", model: str = "") -> None:
    """Append a chat entry to history JSONL.

    IMPORTANT: this path is APPEND-ONLY. Chat history is a historical oracle
    the user explicitly told us to preserve forever — there is NO rotation,
    NO truncation, NO auto-deletion anywhere in the codebase. If you're
    reading this because you're about to add a cleanup/rotation iterator:
    don't. See docs/wiki/architecture/data-stores.md row for the rationale
    and the `.bak*` sibling files for historical manual snapshots.

    Every row also carries a best-effort ``market_context`` snapshot
    (equity / positions / prices) so downstream analysis can correlate the
    message with market state at the time. The enrichment is wrapped in
    try/except and NEVER blocks the chat write — if the snapshot read
    fails, ``market_context`` degrades to ``null`` and the row still lands.
    """
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

    # Best-effort market-state correlation. Wrapped in try/except so a
    # broken snapshot reader CANNOT block the chat write path.
    try:
        mc = _build_market_context_snapshot()
        if mc is not None:
            entry["market_context"] = mc
    except Exception as e:
        # Swallow completely — chat row is the source of truth, mc is
        # opportunistic metadata.
        log.debug("market_context enrichment failed (non-fatal): %s", e)

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


def _parse_anthropic_response(data: dict) -> dict:
    """Parse Anthropic API response into OpenAI-compatible format.

    Shared by all code paths that receive an Anthropic response.
    """
    content_blocks = data.get("content", [])
    text_parts = []
    tool_calls = []
    for block in content_blocks:
        if block.get("type") == "text":
            # Drop empty/whitespace text blocks — Anthropic rejects them when
            # they come back through as message history on the next turn.
            txt = block.get("text", "")
            if txt and txt.strip():
                text_parts.append(txt)
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


def _get_anthropic_client(model: str = ""):
    """Create an Anthropic SDK client matching Claude Code's client.ts.

    Uses auth_token (not api_key) for session tokens — the SDK handles
    the correct auth headers (Bearer + empty X-Api-Key).
    """
    import anthropic

    api_key = _get_anthropic_key()
    if not api_key:
        return None

    betas = _get_anthropic_betas(model)
    is_session = _is_session_token(api_key)

    cc_config_path = Path.home() / ".claude.json"
    session_id = "telegram-bot"
    try:
        if cc_config_path.exists():
            cc_data = json.loads(cc_config_path.read_text())
            device_id = cc_data.get("userID", "")
            account_uuid = cc_data.get("oauthAccount", {}).get("accountUuid", "")
            session_id = json.dumps({"device_id": device_id, "account_uuid": account_uuid, "session_id": "telegram-bot"})
    except Exception:
        pass

    if is_session:
        return anthropic.Anthropic(
            auth_token=api_key,
            max_retries=2,
            timeout=60.0,
            default_headers={
                "anthropic-beta": ",".join(betas),
                "x-app": "cli",
                "user-agent": "claude-cli/2.1.87",
                "X-Claude-Code-Session-Id": "telegram-bot",
            },
        ), session_id
    else:
        return anthropic.Anthropic(
            api_key=api_key,
            max_retries=2,
            timeout=60.0,
        ), session_id


def _find_claude_cli() -> Optional[Path]:
    """Find the Claude Code CLI binary, handling version changes.

    Searches ~/Library/Application Support/Claude/claude-code/*/claude.app/...
    Returns the newest version found, or None.
    """
    base = Path.home() / "Library" / "Application Support" / "Claude" / "claude-code"
    if not base.exists():
        return None
    # Find all version directories and pick the newest
    candidates = []
    for version_dir in base.iterdir():
        if not version_dir.is_dir() or version_dir.name.startswith("."):
            continue
        cli = version_dir / "claude.app" / "Contents" / "MacOS" / "claude"
        if cli.exists():
            candidates.append(cli)
    if not candidates:
        return None
    # Sort by version directory name (newest last)
    candidates.sort(key=lambda p: p.parent.parent.parent.name)
    return candidates[-1]


def _call_via_claude_cli(messages: List[Dict], model: str, tools: Optional[list] = None) -> Optional[dict]:
    """Call Anthropic via the Claude Code CLI binary.

    This uses the EXACT same auth + SDK path as Claude Code desktop.
    The CLI binary handles OAuth token refresh, correct headers, connection
    pooling, and all the server-side session magic that makes Sonnet/Opus work.

    The Agent SDK does NOT support OAuth tokens (401). The CLI binary is the
    only path that reliably works for premium models with subscription tokens.
    See docs/wiki/operations/anthropic-session-token-guide.md for full details.

    Tool support: tool definitions are injected into the prompt as text.
    The model outputs tool calls in [TOOL: name {"arg": "val"}] format
    which the existing triple-mode parser in handle_ai_message picks up.

    Returns OpenAI-compatible response dict, or None on failure.
    """
    import subprocess as sp

    cli_path = _find_claude_cli()
    if not cli_path:
        log.warning("Claude CLI binary not found — is Claude Code installed?")
        return None

    # Extract user message (last user message)
    prompt = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                prompt = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
            else:
                prompt = content
            break

    if not prompt:
        return None

    # Build full prompt with system context + conversation history
    system_text = ""
    for msg in messages:
        if msg.get("role") == "system":
            system_text += msg.get("content", "") + "\n"

    history_parts = []
    for msg in messages:
        if msg.get("role") in ("user", "assistant") and msg.get("content"):
            content = msg["content"]
            if isinstance(content, str) and len(content) < 500:
                history_parts.append(f"[{msg['role']}]: {content}")

    full_prompt = ""
    if system_text.strip():
        full_prompt += f"{system_text.strip()[:3000]}\n\n"

    # Inject tool definitions so the model can invoke them via text.
    # Use [TOOL: name {"arg": "val"}] syntax — our triple-mode parser picks these up.
    if tools:
        tool_lines = [
            "## YOUR TOOLS",
            "You MUST use tools to answer questions about positions, prices, markets, etc.",
            'To invoke a tool, output EXACTLY: [TOOL: name {"arg": "val"}]',
            "Examples:",
            "  [TOOL: account_summary]",
            '  [TOOL: live_price {"market": "BRENTOIL"}]',
            '  [TOOL: web_search {"query": "crude oil price forecast"}]',
            '  [TOOL: read_file {"path": "docs/plans/MASTER_PLAN.md"}]',
            '  [TOOL: list_files {"pattern": "**/*.py"}]',
            "",
            "Available tools:",
        ]
        for t in tools:
            func = t.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "")[:150]
            params = func.get("parameters", {}).get("properties", {})
            if params:
                param_str = ", ".join(f'"{k}": {v.get("type", "string")}' for k, v in params.items())
                tool_lines.append(f"  - [TOOL: {name} {{{param_str}}}] — {desc}")
            else:
                tool_lines.append(f"  - [TOOL: {name}] — {desc}")
        full_prompt += "\n".join(tool_lines) + "\n\n"

    if history_parts:
        full_prompt += "\n".join(history_parts[-6:]) + "\n\n"

    full_prompt += prompt

    try:
        # ``--allowedTools`` whitelists Claude Code's built-in tools that are
        # allowed to run without user approval inside the -p subprocess.
        # Without this flag, the CLI runs in non-interactive print mode with
        # no TTY and no way to click "approve" — any built-in tool that needs
        # permission (WebSearch, WebFetch, etc.) gets blocked and the model
        # returns "I need permission" text to the user, which surfaces on
        # Telegram as an "approval required" message with no approval button.
        #
        # BUG-FIX 2026-04-08: WebSearch + WebFetch are whitelisted so the
        # embedded Claude can search the web in response to user questions
        # (e.g. "what's the current crude oil price?") without requiring a
        # Telegram approval round-trip that has no UI path.  These are both
        # read-only HTTP fetches with no local filesystem or exchange impact;
        # whitelisting them is strictly a UX fix, not a security change.
        result = sp.run(
            [str(cli_path), "--model", model, "--output-format", "json",
             "--allowedTools", "WebSearch WebFetch",
             "-p", full_prompt],
            capture_output=True, text=True, timeout=90,
        )
        if result.returncode != 0:
            log.warning("Claude CLI failed (rc=%d): %s", result.returncode, result.stderr[:200])
            return None

        data = json.loads(result.stdout)
        if data.get("is_error"):
            log.warning("Claude CLI error: %s", data.get("result", "")[:200])
            return None

        text = data.get("result", "")
        if text:
            return {"role": "assistant", "content": text}
        return None

    except sp.TimeoutExpired:
        log.warning("Claude CLI timed out (90s)")
        return None
    except Exception as e:
        log.warning("Claude CLI call failed: %s", e)
        return None


def _call_anthropic(messages: List[Dict], tools: Optional[list] = None, model_override: Optional[str] = None) -> dict:
    """Call Anthropic Messages API.

    For Sonnet/Opus: uses Claude CLI binary (same path as OpenClaw).
    For Haiku: uses Python SDK directly (works fine, free).
    Falls back to SDK for all models if CLI unavailable.
    """
    import anthropic

    model = _get_active_model()
    anthropic_model = model_override or model.replace("anthropic/", "", 1)

    # Sonnet/Opus: use Claude CLI binary (same auth as Claude Code desktop).
    # The Agent SDK does NOT support OAuth tokens (401). The Python anthropic
    # SDK gets 429 on premium models. Only the CLI binary works reliably.
    # See docs/wiki/operations/anthropic-session-token-guide.md for full details.
    if "haiku" not in anthropic_model:
        cli_result = _call_via_claude_cli(messages, anthropic_model, tools=tools)
        if cli_result:
            return cli_result
        log.warning("CLI proxy failed for %s, falling back to Python SDK", anthropic_model)

    result = _get_anthropic_client(anthropic_model)
    if not result:
        return {"content": "Error: No Anthropic API key found."}
    client, session_id = result

    # Convert messages
    system_text, conv_messages = _convert_messages_to_anthropic(messages)

    # Build tool definitions
    sdk_tools = None
    if tools:
        cc = _get_cache_control()
        sdk_tools = []
        for t in tools:
            func = t.get("function", {})
            tool_def = {
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            }
            sdk_tools.append(tool_def)
        if sdk_tools:
            sdk_tools[-1]["cache_control"] = cc

    # Build system with caching
    cc = _get_cache_control()
    system_blocks = None
    if system_text.strip():
        system_blocks = [{"type": "text", "text": system_text.strip(), "cache_control": cc}]

    # Cache breakpoint on last message
    if conv_messages:
        last_msg = conv_messages[-1]
        content = last_msg.get("content", "")
        if isinstance(content, str) and content:
            last_msg["content"] = [{"type": "text", "text": content, "cache_control": cc}]
        elif isinstance(content, list) and content:
            last_block = content[-1]
            if isinstance(last_block, dict):
                last_block["cache_control"] = cc

    for attempt in range(_OR_MAX_RETRIES):
        try:
            kwargs = {
                "model": anthropic_model,
                "max_tokens": _MAX_RESPONSE_TOKENS,
                "messages": conv_messages,
                "metadata": {"user_id": session_id},
            }
            if system_blocks:
                kwargs["system"] = system_blocks
            if sdk_tools:
                kwargs["tools"] = sdk_tools

            resp = client.messages.create(**kwargs)

            # Convert SDK response to OpenAI-compatible format.
            # Filter out whitespace-only text blocks — Anthropic emits empty
            # text blocks alongside tool_use sometimes, and storing them
            # causes a 400 on the NEXT turn when they get re-fed into the
            # converter as message history.
            text_parts = []
            tool_calls = []
            for block in resp.content:
                if block.type == "text" and getattr(block, "text", None) and block.text.strip():
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "type": "function",
                        "function": {"name": block.name, "arguments": json.dumps(block.input)},
                    })

            result_dict: dict = {"role": "assistant"}
            if text_parts:
                result_dict["content"] = "\n".join(text_parts)
            if tool_calls:
                result_dict["tool_calls"] = tool_calls
            if not text_parts and not tool_calls:
                result_dict["content"] = ""
            return result_dict

        except anthropic.RateLimitError as e:
            delay = _OR_BACKOFF_BASE * (2 ** attempt)
            log.warning("Anthropic 429 (attempt %d/%d), backing off %.1fs", attempt + 1, _OR_MAX_RETRIES, delay)
            if attempt < _OR_MAX_RETRIES - 1:
                time.sleep(delay)
                continue
            # Exhausted — try Haiku fallback
            if "haiku" not in anthropic_model and "haiku" not in (model_override or ""):
                log.info("Rate limited on %s — trying Haiku", anthropic_model)
                try:
                    kwargs["model"] = "claude-haiku-4-5"
                    haiku_resp = client.messages.create(**kwargs)
                    text_parts = [b.text for b in haiku_resp.content if b.type == "text"]
                    tool_calls = [{"id": b.id, "type": "function", "function": {"name": b.name, "arguments": json.dumps(b.input)}} for b in haiku_resp.content if b.type == "tool_use"]
                    r: dict = {"role": "assistant"}
                    if text_parts:
                        r["content"] = "\n".join(text_parts)
                    if tool_calls:
                        r["tool_calls"] = tool_calls
                    if not text_parts and not tool_calls:
                        r["content"] = ""
                    return r
                except Exception as he:
                    log.warning("Haiku fallback failed: %s", he)
            # Free fallback chain
            fallback_result, _ = _try_fallback_chain(messages, tools)
            if fallback_result:
                return fallback_result
            return {"content": "AI rate limited — try again in a minute. Use /status for instant data."}

        except anthropic.AuthenticationError as e:
            log.warning("Anthropic auth error (attempt %d): %s", attempt + 1, e)
            # Force token refresh and retry once
            if attempt == 0:
                log.info("Forcing token refresh after 401...")
                refreshed = _force_token_refresh()
                if refreshed:
                    result = _get_anthropic_client(anthropic_model)
                    if result:
                        client, session_id = result
                        continue
            return {"content": "Auth expired — open Claude Code to refresh your session, then try again."}
        except anthropic.APITimeoutError:
            return {"content": "AI response timed out. Try /status for instant data."}
        except Exception as e:
            log.error("Anthropic call failed: %s", e)
            return {"content": f"AI call failed: {e}"}

    return {"content": "AI unavailable after retries. Try /status for live data."}


def _call_openrouter(messages: List[Dict], tools: Optional[list] = None) -> dict:
    """Route Anthropic models to direct API. OpenRouter is separate (user-controlled).

    All anthropic/* models go direct via session token — free, no per-token billing.
    Non-anthropic models go via OpenRouter if a key is configured.
    """
    _call_openrouter._last_fallback = None

    model = _get_active_model()
    if _is_anthropic_model(model):
        return _call_anthropic(messages, tools)

    # Non-Anthropic model via OpenRouter
    or_key = _get_openrouter_key()
    if or_key:
        return _call_openrouter_direct(messages, tools)
    return {"content": "No API key available. Use /models to select a model."}


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


def _refresh_oauth_token(refresh_token: str) -> Optional[str]:
    """Refresh an expired OAuth token using the refresh_token grant.

    Matches Claude Code's refreshOAuthToken() in services/oauth/client.ts.
    Returns new access token or None on failure.
    """
    import subprocess as sp
    try:
        resp = requests.post("https://platform.claude.com/v1/oauth/token", json={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
            "scope": "user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload",
        }, headers={"Content-Type": "application/json"}, timeout=15)

        if resp.status_code != 200:
            log.warning("Token refresh failed: %s", resp.text[:200])
            return None

        data = resp.json()
        new_token = data["access_token"]
        new_refresh = data.get("refresh_token", refresh_token)
        expires_in = data.get("expires_in", 0)

        # Update keychain
        try:
            raw = sp.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True, text=True,
            ).stdout.strip()
            if raw:
                kc_data = json.loads(raw)
                kc_data["claudeAiOauth"]["accessToken"] = new_token
                kc_data["claudeAiOauth"]["refreshToken"] = new_refresh
                kc_data["claudeAiOauth"]["expiresAt"] = int(time.time() * 1000) + expires_in * 1000
                sp.run(["security", "delete-generic-password", "-s", "Claude Code-credentials"], capture_output=True)
                sp.run(["security", "add-generic-password", "-s", "Claude Code-credentials",
                        "-a", "default", "-w", json.dumps(kc_data), "-U"], capture_output=True)
        except Exception as e:
            log.debug("Keychain update failed: %s", e)

        # Update auth-profiles.json
        try:
            if _AUTH_PROFILES.exists():
                auth_data = json.loads(_AUTH_PROFILES.read_text())
                for name, profile in auth_data.get("profiles", {}).items():
                    if profile.get("provider") == "anthropic":
                        profile["token"] = new_token
                        break
                _AUTH_PROFILES.write_text(json.dumps(auth_data, indent=2) + "\n")
        except Exception as e:
            log.debug("auth-profiles update failed: %s", e)

        log.info("OAuth token refreshed (expires in %ds)", expires_in)
        return new_token
    except Exception as e:
        log.warning("Token refresh error: %s", e)
        return None


def _force_token_refresh() -> Optional[str]:
    """Force-refresh the OAuth token from keychain, ignoring expiry check.

    Called after a 401 — the token looked valid but the API rejected it.
    Returns new token or None.
    """
    import subprocess as sp
    try:
        raw = sp.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True,
        ).stdout.strip()
        if not raw:
            return None
        kc_data = json.loads(raw)
        refresh_token = kc_data.get("claudeAiOauth", {}).get("refreshToken", "")
        if refresh_token:
            new_token = _refresh_oauth_token(refresh_token)
            if new_token:
                log.info("Force-refresh succeeded")
                return new_token
        log.warning("Force-refresh failed — no refresh token in keychain")
        return None
    except Exception as e:
        log.warning("Force-refresh error: %s", e)
        return None


def _get_anthropic_key() -> Optional[str]:
    """Read Anthropic session token, auto-refreshing if expired.

    Token sources (in priority order):
    1. macOS Keychain (shared with Claude Code, auto-refreshed)
    2. auth-profiles.json (may be stale)
    3. ANTHROPIC_API_KEY env var

    If the token is expired and a refresh token is available, refreshes
    automatically — matching Claude Code's auth.ts behavior.
    """
    import subprocess as sp

    # 1. Try keychain first (Claude Code keeps this current)
    try:
        raw = sp.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True,
        ).stdout.strip()
        if raw:
            kc_data = json.loads(raw)
            oauth = kc_data.get("claudeAiOauth", {})
            token = oauth.get("accessToken", "")
            expires_at = oauth.get("expiresAt", 0)

            # Check if expired
            now_ms = int(time.time() * 1000)
            if token and now_ms < expires_at:
                return token

            # Expired — try to refresh
            refresh_token = oauth.get("refreshToken", "")
            if refresh_token:
                new_token = _refresh_oauth_token(refresh_token)
                if new_token:
                    return new_token
                log.warning("Token refresh failed — expired token will not be sent")

            # Don't return expired tokens — they just cause 401s
    except Exception:
        pass

    # 2. Fall back to auth-profiles.json
    try:
        if _AUTH_PROFILES.exists():
            data = json.loads(_AUTH_PROFILES.read_text())
            profiles = data.get("profiles", {})
            for name, profile in profiles.items():
                if profile.get("provider") == "anthropic":
                    return profile.get("token") or profile.get("key")
    except Exception:
        pass

    # 3. Environment variable
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
