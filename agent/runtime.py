"""Agent runtime — core agent loop ported from Claude Code architecture.

Provides:
- build_system_prompt(): Claude Code-quality prompt assembly
- ToolExecutor: parallel tool execution with concurrency safety
- stream_api_call(): SSE streaming for Anthropic + OpenRouter
- accordion_truncate(): Claude Code-style context management (strips old tool outputs)
- should_dream() + build_dream_prompt(): memory consolidation

Model-agnostic — works with any provider via telegram_agent.py adapters.
"""
from __future__ import annotations


import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

import requests

log = logging.getLogger("agent_runtime")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MEMORY_DIR = _PROJECT_ROOT / "data" / "agent_memory"


# ═══════════════════════════════════════════════════════════════════════
# 0. COST GATE — token-budget enforcer (see agent/control/cost_gate.py)
# ═══════════════════════════════════════════════════════════════════════

# Module-level singleton — one gate per process lifetime (= one session).
# Callers import and use check_cost_usage() rather than the gate directly.
try:
    from agent.control.cost_gate import CostGate as _CostGate, CostBudget as _CostBudget
    _cost_gate: Optional[Any] = _CostGate()
    log.debug("CostGate initialised — session_hard_cap=%s", _cost_gate.budget.session_hard_cap)
except Exception as _cg_err:  # pragma: no cover
    log.warning("CostGate unavailable — cost enforcement disabled: %s", _cg_err)
    _cost_gate = None


def check_cost_usage(usage: dict) -> Optional[str]:
    """Extract token counts from an LLM usage dict and enforce the budget.

    Call this immediately after every LLM API response::

        reason = check_cost_usage(result.usage)
        if reason:
            # Budget breached — abort the agent
            _handle_cost_abort(reason)

    Args:
        usage: Dict with keys ``prompt_tokens`` / ``input_tokens`` and
               ``completion_tokens`` / ``output_tokens``.  Anthropic and
               OpenRouter use slightly different key names — both are handled.

    Returns:
        ``None`` if budget is fine.
        A non-empty reason string if the budget was breached (caller must abort).

    Side-effect: updates state.json with current token totals.
    """
    if _cost_gate is None:
        return None

    # Normalise key names across providers
    prompt_tokens = int(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or 0
    )
    completion_tokens = int(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or 0
    )

    reason = _cost_gate.record_turn(prompt_tokens, completion_tokens)

    # Always sync token counts to state.json so the dashboard reflects reality
    gate_state = _cost_gate.get_state()
    try:
        from agent.control.state_writer import read_state_json, atomic_write_json, _DEFAULT_STATE_PATH
        state = read_state_json()
        state.update(gate_state)
        atomic_write_json(state, _DEFAULT_STATE_PATH)
    except Exception as _sw_err:
        log.debug("state.json sync failed (non-fatal): %s", _sw_err)

    # On breach, also call AgentControl.abort() if available
    if reason:
        try:
            from agent.control import AgentControl
            AgentControl().abort(reason=reason)
        except Exception as _ac_err:
            log.debug("AgentControl.abort() unavailable (non-fatal): %s", _ac_err)

    return reason


def get_cost_gate_state() -> dict:
    """Return current cost gate state (tokens_used_session, budget, etc.)."""
    if _cost_gate is None:
        return {}
    return _cost_gate.get_state()


# ═══════════════════════════════════════════════════════════════════════
# 1. SYSTEM PROMPT — ported from Claude Code constants/prompts.ts
# ═══════════════════════════════════════════════════════════════════════

# These sections are adapted from Claude Code's actual prompt text.
# Static sections are cached; dynamic sections (memory, live context) are fresh per message.

_PROMPT_CORE = """You are an autonomous agent. Think, plan, act. Lead with answers, not reasoning. Verify before claiming success. Report outcomes faithfully. Diagnose failures before switching tactics. Challenge constructively. Call independent tools in parallel. Check LIVE CONTEXT before calling tools for data already in your prompt."""


# Kill switch for the RECENT RELEVANT LESSONS prompt-injection section.
# Flip to False to disable lesson injection globally without removing code.
# Tests may also monkeypatch this module attribute to exercise both branches.
_LESSON_INJECTION_ENABLED = True


def build_system_prompt(
    agent_md: str = "",
    soul_md: str = "",
    memory_content: str = "",
    live_context: str = "",
    lessons_section: str = "",
) -> str:
    """Assemble the full system prompt from static + dynamic sections.

    Static sections (Claude Code patterns) provide the agent architecture.
    Dynamic sections (agent_md, memory, lessons, live_context) provide domain
    specifics. Pass an empty `lessons_section` to skip the section entirely —
    callers typically get the string from `build_lessons_section()`.
    """
    parts = [_PROMPT_CORE]

    # Domain-specific instructions (trading rules, coin names, etc.)
    if agent_md:
        parts.append(f"# Trading Agent Instructions\n\n{agent_md}")
    if soul_md:
        parts.append(f"# Response Protocol\n\n{soul_md}")

    # Dynamic per-message content
    if memory_content:
        parts.append(f"--- AGENT MEMORY ---\n\n{memory_content}")
    # Lessons sit between memory and live_context: structured historical
    # recall, as opposed to live_context which is immediate account/market state.
    if lessons_section:
        parts.append(lessons_section)
    if live_context:
        parts.append(live_context)

    return "\n\n---\n\n".join(parts)


def build_lessons_section(
    query: str = "",
    market: Optional[str] = None,
    signal_source: Optional[str] = None,
    direction: Optional[str] = None,
    lesson_type: Optional[str] = None,
    limit: int = 5,
) -> str:
    """Build the `## RECENT RELEVANT LESSONS` prompt-injection section.

    Reads from the lessons corpus in `data/memory/memory.db` via
    `common.memory.search_lessons`. Non-empty `query` ranks by BM25 over
    summary + body_full + tags; empty query falls back to recency.

    Returns an empty string (section is naturally skipped by
    `build_system_prompt`) when:
      - `_LESSON_INJECTION_ENABLED` is False (global kill switch)
      - the corpus has no matching rows
      - the memory DB query raises — logged and swallowed. The 2026-04-08
        Bug A pattern applies here: refuse to degrade the prompt with a
        broken section; lesson injection must never break the agent.
    """
    if not _LESSON_INJECTION_ENABLED:
        return ""

    try:
        from common import memory as common_memory
        # common.memory helpers resolve _DB_PATH at call time as of 5382a0b,
        # so we don't need to pass db_path= explicitly anymore — the default
        # None flows through to _resolve_db_path(_DB_PATH).
        rows = common_memory.search_lessons(
            query=query or "",
            market=market,
            direction=direction,
            signal_source=signal_source,
            lesson_type=lesson_type,
            limit=int(limit),
        )
    except Exception as e:
        log.warning("lessons section: search failed, omitting section: %s", e)
        return ""

    if not rows:
        return ""

    lines = [
        "## RECENT RELEVANT LESSONS",
        "",
        "Your own prior trade post-mortems. Call `get_lesson(id)` for the",
        "verbatim body when a summary looks relevant.",
        "",
    ]
    for r in rows:
        lesson_id = r.get("id")
        market_col = r.get("market", "?")
        direction_col = r.get("direction", "?")
        outcome_col = r.get("outcome", "?")
        signal_col = r.get("signal_source", "?")
        type_col = r.get("lesson_type", "?")
        roe = r.get("roe_pct", 0.0)
        closed = (r.get("trade_closed_at") or "")[:10]
        summary = (r.get("summary") or "").strip()
        reviewed = r.get("reviewed_by_chris", 0)
        review_flag = " [approved]" if reviewed == 1 else ""
        lines.append(
            f"- #{lesson_id} {closed} {market_col} {direction_col} "
            f"({signal_col}, {type_col}) → {outcome_col} {roe:+.1f}%{review_flag}"
        )
        lines.append(f"  {summary}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 2. PARALLEL TOOL EXECUTION — ported from StreamingToolExecutor.ts
# ═══════════════════════════════════════════════════════════════════════

# Tools that are safe to run concurrently (all READ tools)
CONCURRENT_SAFE_TOOLS = {
    "market_brief", "account_summary", "live_price",
    "analyze_market", "check_funding", "get_orders", "trade_journal",
    "get_signals", "introspect_self", "get_calendar", "get_research",
    "get_technicals", "search_lessons", "get_lesson",
    "read_file", "search_code", "list_files", "web_search", "memory_read",
    "get_errors", "get_feedback", "read_reference",
}


@dataclass
class TrackedTool:
    """A tool in the execution queue."""
    id: str
    name: str
    args: dict
    is_concurrent_safe: bool
    status: str = "queued"  # queued → executing → completed
    result: Optional[str] = None


def execute_tools_parallel(tool_calls: List[dict], execute_fn) -> List[Tuple[str, str, str]]:
    """Execute multiple tool calls with concurrency where safe.

    Ported from Claude Code's StreamingToolExecutor.
    Returns list of (tool_id, tool_name, result_string).

    Rules:
    - READ tools (CONCURRENT_SAFE_TOOLS) run in parallel
    - WRITE tools block the queue — must complete before next tool starts
    - Results are returned in ORDER regardless of completion order
    """
    if not tool_calls:
        return []

    tracked = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        raw_args = fn.get("arguments", "{}")
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        tracked.append(TrackedTool(
            id=tc.get("id", f"call_{len(tracked)}"),
            name=name,
            args=args,
            is_concurrent_safe=name in CONCURRENT_SAFE_TOOLS,
        ))

    # Group into batches: consecutive concurrent-safe tools form one parallel batch,
    # non-safe tools form single-item batches
    batches: List[List[TrackedTool]] = []
    current_batch: List[TrackedTool] = []

    for tool in tracked:
        if tool.is_concurrent_safe:
            current_batch.append(tool)
        else:
            if current_batch:
                batches.append(current_batch)
                current_batch = []
            batches.append([tool])  # non-safe runs alone

    if current_batch:
        batches.append(current_batch)

    # Execute batches sequentially; tools within concurrent batch run in parallel
    results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        for batch in batches:
            if len(batch) == 1:
                # Single tool (or non-safe) — run directly
                tool = batch[0]
                tool.status = "executing"
                tool.result = execute_fn(tool.name, tool.args)
                tool.status = "completed"
                results.append((tool.id, tool.name, tool.result))
            else:
                # Concurrent batch — run in parallel
                futures = {}
                for tool in batch:
                    tool.status = "executing"
                    futures[tool.id] = executor.submit(execute_fn, tool.name, tool.args)

                for tool in batch:
                    tool.result = futures[tool.id].result()
                    tool.status = "completed"
                    results.append((tool.id, tool.name, tool.result))

    return results


# ═══════════════════════════════════════════════════════════════════════
# 3. STREAMING SSE PARSER — ported from Claude Code services/api/claude.ts
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class StreamEvent:
    """A parsed SSE event from the Anthropic/OpenRouter streaming API."""
    event_type: str  # message_start, content_block_start, content_block_delta, etc.
    data: dict = field(default_factory=dict)


@dataclass
class StreamResult:
    """Accumulated result from streaming."""
    text: str = ""
    tool_calls: List[dict] = field(default_factory=list)
    thinking: str = ""
    stop_reason: str = ""
    usage: dict = field(default_factory=dict)


def parse_sse_line(line: str) -> Optional[StreamEvent]:
    """Parse a single SSE line into a StreamEvent."""
    line = line.strip()
    if not line or line.startswith(":"):
        return None
    if line.startswith("data: "):
        data_str = line[6:]
        if data_str == "[DONE]":
            return StreamEvent(event_type="done")
        try:
            data = json.loads(data_str)
            return StreamEvent(event_type=data.get("type", "unknown"), data=data)
        except json.JSONDecodeError:
            return None
    return None


def stream_and_accumulate(
    url: str,
    payload: dict,
    headers: dict,
    timeout: int = 120,
) -> Generator[Tuple[str, StreamResult], None, None]:
    """Stream an API call and yield (delta_text, accumulated_result) tuples.

    Yields after every text delta so the caller can update Telegram.
    At the end, the final StreamResult contains complete tool_calls, text, etc.

    Ported from Claude Code's streaming loop in services/api/claude.ts.
    """
    payload["stream"] = True
    result = StreamResult()
    content_blocks: Dict[int, dict] = {}

    try:
        resp = requests.post(url, json=payload, headers=headers, stream=True, timeout=timeout)
        if resp.status_code != 200:
            error_text = ""
            for chunk in resp.iter_content(chunk_size=4096):
                error_text += chunk.decode("utf-8", errors="replace")
                if len(error_text) > 500:
                    break
            # Raise on rate limits and auth failures so caller can retry/fallback
            if resp.status_code == 429:
                raise RuntimeError(f"Rate limited (429): {error_text[:200]}")
            if resp.status_code == 401:
                raise RuntimeError(f"Auth failed (401): {error_text[:200]}")
            result.text = f"API error ({resp.status_code}): {error_text[:300]}"
            yield ("", result)
            return

        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            event = parse_sse_line(raw_line)
            if not event:
                continue

            if event.event_type == "message_start":
                msg = event.data.get("message", {})
                result.usage = msg.get("usage", {})

            elif event.event_type == "content_block_start":
                idx = event.data.get("index", 0)
                block = event.data.get("content_block", {})
                if block.get("type") == "tool_use":
                    content_blocks[idx] = {"type": "tool_use", "id": block.get("id", ""), "name": block.get("name", ""), "input": ""}
                elif block.get("type") == "text":
                    content_blocks[idx] = {"type": "text", "text": ""}
                elif block.get("type") == "thinking":
                    content_blocks[idx] = {"type": "thinking", "thinking": ""}

            elif event.event_type == "content_block_delta":
                idx = event.data.get("index", 0)
                delta = event.data.get("delta", {})
                block = content_blocks.get(idx, {})

                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    block["text"] = block.get("text", "") + text
                    result.text += text
                    yield (text, result)  # yield every text delta for streaming

                elif delta.get("type") == "input_json_delta":
                    block["input"] = block.get("input", "") + delta.get("partial_json", "")

                elif delta.get("type") == "thinking_delta":
                    block["thinking"] = block.get("thinking", "") + delta.get("thinking", "")
                    result.thinking += delta.get("thinking", "")

            elif event.event_type == "content_block_stop":
                idx = event.data.get("index", 0)
                block = content_blocks.get(idx, {})
                if block.get("type") == "tool_use":
                    try:
                        parsed_input = json.loads(block["input"]) if block["input"] else {}
                    except json.JSONDecodeError:
                        parsed_input = {}
                    result.tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(parsed_input),
                        },
                    })

            elif event.event_type == "message_delta":
                delta = event.data.get("delta", {})
                result.stop_reason = delta.get("stop_reason", result.stop_reason)
                if "usage" in event.data:
                    result.usage.update(event.data["usage"])

            elif event.event_type == "done":
                break

    except requests.exceptions.Timeout:
        result.text = "Request timed out. Try again or use /status for live data."
        yield ("", result)
    except Exception as e:
        log.error("Streaming error: %s", e)
        result.text = f"Streaming error: {e}"
        yield ("", result)


# ═══════════════════════════════════════════════════════════════════════
# 4. CONTEXT COMPACTION — ported from Claude Code services/compact/
# ═══════════════════════════════════════════════════════════════════════

# Token estimation: ~4 chars per token (rough but good enough for threshold)
_CHARS_PER_TOKEN = 4

# Context windows by model family
_CONTEXT_WINDOWS = {
    "opus": 200_000,
    "sonnet": 200_000,
    "haiku": 200_000,
    "default": 128_000,  # most OpenRouter models
}

_COMPACT_RESERVE = 20_000   # reserved for summary output
_COMPACT_BUFFER = 13_000    # buffer before threshold triggers


def estimate_tokens(messages: List[Dict]) -> int:
    """Rough token estimate from message list."""
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    return total_chars // _CHARS_PER_TOKEN


def get_context_window(model: str) -> int:
    """Get context window for a model."""
    model_lower = model.lower()
    for family, window in _CONTEXT_WINDOWS.items():
        if family in model_lower:
            return window
    return _CONTEXT_WINDOWS["default"]


def compact_chat_history(
    history: List[Dict],
    token_budget: int = 8000,
    preserve_tail: int = 6,
    summarizer_fn=None,
) -> List[Dict]:
    """Token-aware chat history compaction.

    Replaces the hard message-count cap with intelligent summarization.
    When history exceeds token_budget, older messages are summarized into
    a single context entry while the most recent `preserve_tail` messages
    are kept verbatim.

    Pattern from nano-claude-code's compaction.py — adapted for our
    Telegram agent's JSONL history format.

    Args:
        history: List of {"role": ..., "text": ...} dicts from chat_history.jsonl
        token_budget: Max estimated tokens for the returned history
        preserve_tail: Number of recent messages to keep verbatim
        summarizer_fn: Optional callable(text) -> summary. If None, uses
                       extractive summary (keywords + recent user requests).

    Returns:
        Compacted history list. First entry may be a synthetic summary.
    """
    if not history:
        return history

    # Estimate current token usage
    total_chars = sum(len(e.get("text", "")) for e in history)
    total_tokens = total_chars // _CHARS_PER_TOKEN

    if total_tokens <= token_budget:
        return history  # Fits — no compaction needed

    # Split: older messages to summarize, recent to preserve
    if len(history) <= preserve_tail:
        return history  # Too few messages to compact

    old_messages = history[:-preserve_tail]
    recent_messages = history[-preserve_tail:]

    # Build extractive summary from old messages
    # (No LLM call — fast, deterministic, zero cost)
    user_requests = []
    assistant_actions = []
    tools_used = set()
    topics = set()

    for msg in old_messages:
        text = msg.get("text", "")[:300]  # Cap per-message scanning
        role = msg.get("role", "")

        if role == "user":
            # Keep the first line of each user message as a request summary
            first_line = text.split("\n")[0].strip()
            if first_line and len(first_line) > 5:
                user_requests.append(first_line[:100])
        elif role == "assistant":
            # Extract tool mentions and key actions
            if "[display tool:" in text:
                tools_used.update(t.strip() for t in text.split("[display tool:")[1].split("]")[0].split(","))
            if any(kw in text.lower() for kw in ("position", "trade", "order", "thesis")):
                topics.add("trading")
            if any(kw in text.lower() for kw in ("edit", "file", "code", "test", "bug")):
                topics.add("coding")
            # Keep short action summaries
            first_line = text.split("\n")[0].strip()
            if first_line and len(first_line) > 10:
                assistant_actions.append(first_line[:80])

    # Assemble compact summary
    parts = [f"[Chat summary — {len(old_messages)} older messages compacted]"]
    if topics:
        parts.append(f"Topics: {', '.join(sorted(topics))}")
    if user_requests:
        # Keep last 5 user requests
        parts.append("Recent user requests:")
        for req in user_requests[-5:]:
            parts.append(f"  - {req}")
    if tools_used:
        parts.append(f"Tools used: {', '.join(sorted(tools_used))}")
    if assistant_actions:
        parts.append("Key actions:")
        for act in assistant_actions[-3:]:
            parts.append(f"  - {act}")

    summary_text = "\n".join(parts)

    # Prepend summary as a synthetic history entry
    summary_entry = {
        "role": "system",
        "text": summary_text,
        "ts": old_messages[-1].get("ts", ""),
        "_compacted": True,
    }

    return [summary_entry] + recent_messages


def accordion_truncate(messages: List[Dict], max_tokens: int = 100_000, trigger_threshold: int = 150_000) -> List[Dict]:
    """Truncate old tool outputs to keep context manageable without losing the narrative.
    
    If total tokens exceed trigger_threshold, it combs backward through the
    message history. Any message older than the last 4 messages (2 user/assistant turns)
    that contains large tool-results text will have that text truncated.
    """
    token_count = estimate_tokens(messages)
    if token_count < trigger_threshold:
        return messages

    # Keep a trailing budget of recent turns perfectly intact
    # (system prompt is messages[0], we don't truncate that anyway)
    protected_count = 4 
    
    truncated = []
    for i, msg in enumerate(messages):
        if i == 0 or i >= len(messages) - protected_count:
            truncated.append(msg)
            continue
            
        role = msg.get("role")
        content = msg.get("content", "")
        
        # We only truncate text content
        if isinstance(content, str) and len(content) > 500:
            # Check if this is a tool result (either user or tool role passing tool results)
            if role in ("tool", "user", "assistant") and ("[Tool result" in content or "live_price" in content or "account_summary" in content):
                truncated.append({
                    **msg,
                    "content": content[:100] + "\n[...Tool output discarded for length to preserve context...]"
                })
            else:
                truncated.append({
                    **msg, 
                    "content": content[:500] + "\n[...Truncated for length...]"
                })
        elif isinstance(content, list):
            # For anthropic-style block content, we only truncate text blocks > 500 chars
            new_content = []
            for block in content:
                if block.get("type") == "text" and len(block.get("text", "")) > 500:
                    text_str = block["text"]
                    if "[Tool result" in text_str or "live_price" in text_str:
                        new_content.append({"type": "text", "text": text_str[:100] + "\n[...Tool output discarded for length to preserve context...]"})
                    else:
                        new_content.append({"type": "text", "text": text_str[:500] + "\n[...Truncated for length...]"})
                else:
                    new_content.append(block)
            truncated.append({**msg, "content": new_content})
        else:
            truncated.append(msg)
            
    return truncated


# ═══════════════════════════════════════════════════════════════════════
# 5. MEMORY DREAM — ported from Claude Code services/autoDream/
# ═══════════════════════════════════════════════════════════════════════

_DREAM_LOCK = _MEMORY_DIR / ".last_dream"
_DREAM_MIN_HOURS = 24
_DREAM_MIN_SESSIONS = 3


def should_dream() -> bool:
    """Check if memory consolidation should run.

    Triggers after 24h AND 3+ conversation sessions since last dream.
    """
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if _DREAM_LOCK.exists():
        hours = (time.time() - _DREAM_LOCK.stat().st_mtime) / 3600
        if hours < _DREAM_MIN_HOURS:
            return False

    # Count sessions since last dream (approximate: count chat history entries)
    history_file = _PROJECT_ROOT / "data" / "daemon" / "chat_history.jsonl"
    if not history_file.exists():
        return False

    last_dream_time = _DREAM_LOCK.stat().st_mtime if _DREAM_LOCK.exists() else 0
    session_count = 0
    try:
        with open(history_file) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get("role") == "user" and entry.get("ts", 0) > last_dream_time:
                        session_count += 1
                except (json.JSONDecodeError, KeyError):
                    continue
    except Exception:
        return False

    return session_count >= _DREAM_MIN_SESSIONS


def mark_dream_complete():
    """Mark the dream as complete by touching the lock file."""
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _DREAM_LOCK.touch()


_DREAM_PROMPT = """# Dream: Memory Consolidation

You are performing a memory consolidation — synthesizing what you've learned recently into durable, well-organized memories.

Memory directory: data/agent_memory/
Chat history: data/daemon/chat_history.jsonl

## Instructions

1. Read your current MEMORY.md index and any existing topic files
2. Read recent chat history for new facts, rules, corrections, or learnings
3. Update existing topic files with new information, or create new topics
4. Update MEMORY.md index with accurate one-line descriptions
5. Remove contradicted or superseded facts
6. Convert any relative dates to absolute
7. Keep MEMORY.md under 200 lines

Focus on:
- Trading rules and preferences Chris has stated
- Market insights and learnings from analysis
- System knowledge about the codebase
- Corrections or clarifications from Chris

Use memory_write(topic, content) to save each topic file."""


def build_dream_prompt() -> str:
    """Build the dream consolidation prompt."""
    return _DREAM_PROMPT


# ═══════════════════════════════════════════════════════════════════════
# 6. CONTROLLED AGENT LOOP — wires AgentControl into the runtime
# ═══════════════════════════════════════════════════════════════════════

import concurrent.futures as _cf
import threading as _threading


class ControlledAgentLoop:
    """Stateless helper that runs one "prompt → (tool → tool → …) → response"
    cycle with full AgentControl integration.

    This class does NOT own the conversation history or the HTTP client.
    The caller (telegram_agent.py) owns those and passes them in each call.
    This keeps the existing caller interface unchanged.

    Control hooks — checked at every boundary:
    ─────────────────────────────────────────
    1. LLM-call boundary  — is_aborted() checked before EVERY LLM call
    2. Tool-call boundary — is_aborted() checked before EVERY tool execution
    3. Steering drain     — drain_steering_queue() injected as user messages
                            BEFORE each LLM call
    4. Follow-up drain    — pop_follow_up() checked when the loop would end
    5. Turn timeout       — each LLM call wrapped in a per-turn timeout thread
    6. State writes       — set_state() called at every transition

    The loop is intentionally NOT recursive to avoid stack depth surprises
    with long follow-up chains.
    """

    def __init__(self, control: "AgentControl") -> None:
        from agent.control import AgentControl  # local import to avoid circular
        self.control = control

    def run(
        self,
        *,
        prompt: str,
        call_llm_fn,         # callable(messages) -> StreamResult
        execute_tool_fn,     # callable(name, args) -> str
        messages: List[Dict],
        max_turns: int = 50,
        turn_timeout_s: Optional[int] = None,
    ) -> dict:
        """Run the agent loop for one user prompt.

        Args:
            prompt: The user's message.
            call_llm_fn: Callable that takes the messages list and returns a
                         StreamResult.  Wraps streaming internally.
            execute_tool_fn: Callable(tool_name, args) → result string.
            messages: Mutable list — messages are appended in-place.
            max_turns: Hard ceiling on LLM calls per run (guards runaway loops).
            turn_timeout_s: Per-turn timeout override.  None → reads from control.

        Returns:
            dict with keys:
              text      — final assistant text (empty string if aborted)
              aborted   — bool
              turns     — number of LLM calls made
        """
        ctrl = self.control
        timeout = turn_timeout_s if turn_timeout_s is not None else ctrl._turn_timeout_s

        # Mark session as running
        ctrl.set_state(is_running=True, current_turn=0)

        # Append the initial user message
        messages.append({"role": "user", "content": prompt})

        final_text = ""
        turns = 0

        # Outer loop: re-enters for each follow-up message
        while True:
            # ── inner loop: tool execution rounds ──────────────────────────
            while turns < max_turns:
                # 1. Check abort BEFORE LLM call
                if ctrl.is_aborted():
                    ctrl.set_state(
                        is_running=False,
                        last_event={"type": "aborted_before_llm", "ts": _iso_now(), "data": {}},
                    )
                    return {"text": final_text, "aborted": True, "turns": turns}

                # 2. Drain steering queue — inject as user messages
                steers = ctrl.drain_steering_queue()
                for s in steers:
                    messages.append({"role": "user", "content": s["text"]})

                turns += 1
                ctrl.set_state(
                    current_turn=turns,
                    last_event={"type": "turn_start", "ts": _iso_now(), "data": {"turn": turns}},
                )

                # 3. LLM call wrapped in per-turn timeout
                result = _run_with_timeout(call_llm_fn, args=(messages,), timeout_s=timeout)

                if result is None:
                    # Timeout
                    ctrl.abort(reason="turn_timeout")
                    ctrl.set_state(is_running=False)
                    return {"text": final_text, "aborted": True, "turns": turns}

                # Accumulate text
                final_text = result.text

                # Add assistant message to history
                messages.append({"role": "assistant", "content": result.text})

                ctrl.set_state(
                    last_event={"type": "turn_end", "ts": _iso_now(), "data": {"turn": turns}},
                )

                # 4. If no tool calls, the model is done for this round
                if not result.tool_calls:
                    break

                # 5. Execute tools — check abort before each one
                tool_results = []
                for tc in result.tool_calls:
                    # Abort check at tool boundary
                    if ctrl.is_aborted():
                        ctrl.set_state(
                            is_running=False,
                            last_event={
                                "type": "aborted_at_tool_boundary",
                                "ts": _iso_now(),
                                "data": {},
                            },
                        )
                        return {"text": final_text, "aborted": True, "turns": turns}

                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    raw_args = fn.get("arguments", "{}")
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    tool_id = tc.get("id", f"call_{turns}")

                    ctrl.set_state(
                        current_tool={
                            "name": name,
                            "args_summary": str(args)[:120],
                            "started_at": _iso_now(),
                        },
                        last_event={
                            "type": "tool_execution_start",
                            "ts": _iso_now(),
                            "data": {"tool": name},
                        },
                    )

                    tool_result = execute_tool_fn(name, args)

                    ctrl.set_state(
                        current_tool=None,
                        last_event={
                            "type": "tool_execution_end",
                            "ts": _iso_now(),
                            "data": {"tool": name},
                        },
                    )
                    tool_results.append((tool_id, name, tool_result))

                # Append tool results as user/tool messages
                for tool_id, name, res in tool_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "content": res,
                    })

            # ── end of inner tool loop ──────────────────────────────────────

            # 6. Check for follow-up BEFORE exiting
            if ctrl.is_aborted():
                break

            follow = ctrl.pop_follow_up()
            if follow is None:
                break

            # Re-enter outer loop with the follow-up as the new user prompt
            messages.append({"role": "user", "content": follow["text"]})
            ctrl.set_state(
                last_event={
                    "type": "follow_up_start",
                    "ts": _iso_now(),
                    "data": {"text": follow["text"][:100]},
                }
            )
            # Continue outer while-loop; turns counter carries over

        # Done
        ctrl.set_state(
            is_running=False,
            current_tool=None,
            last_event={"type": "run_complete", "ts": _iso_now(), "data": {"turns": turns}},
        )
        return {"text": final_text, "aborted": ctrl.is_aborted(), "turns": turns}


def _run_with_timeout(fn, args=(), kwargs=None, timeout_s: int = 60):
    """Run fn(*args, **kwargs) in a thread.  Return result or None on timeout.

    Used to wrap individual LLM calls so a hung HTTP request doesn't block
    the abort check indefinitely.
    """
    if kwargs is None:
        kwargs = {}
    with _cf.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=timeout_s)
        except _cf.TimeoutError:
            log.error("LLM call timed out after %ds", timeout_s)
            return None


def _iso_now() -> str:
    """ISO-8601 UTC timestamp string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
