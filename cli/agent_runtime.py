"""Agent runtime — core agent loop ported from Claude Code architecture.

Provides:
- build_system_prompt(): Claude Code-quality prompt assembly
- ToolExecutor: parallel tool execution with concurrency safety
- stream_api_call(): SSE streaming for Anthropic + OpenRouter
- should_compact() + compact_conversation(): context management
- should_dream() + build_dream_prompt(): memory consolidation

Model-agnostic — works with any provider via telegram_agent.py adapters.
"""
from __future__ import annotations

import asyncio
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
# 1. SYSTEM PROMPT — ported from Claude Code constants/prompts.ts
# ═══════════════════════════════════════════════════════════════════════

# These sections are adapted from Claude Code's actual prompt text.
# Static sections are cached; dynamic sections (memory, live context) are fresh per message.

_PROMPT_CORE = """You are an autonomous agent. Think, plan, act. Lead with answers, not reasoning. Verify before claiming success. Report outcomes faithfully. Diagnose failures before switching tactics. Challenge constructively. Call independent tools in parallel. Check LIVE CONTEXT before calling tools for data already in your prompt."""


def build_system_prompt(
    agent_md: str = "",
    soul_md: str = "",
    memory_content: str = "",
    live_context: str = "",
) -> str:
    """Assemble the full system prompt from static + dynamic sections.

    Static sections (Claude Code patterns) provide the agent architecture.
    Dynamic sections (agent_md, memory, live_context) provide domain specifics.
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
    if live_context:
        parts.append(live_context)

    return "\n\n---\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════
# 2. PARALLEL TOOL EXECUTION — ported from StreamingToolExecutor.ts
# ═══════════════════════════════════════════════════════════════════════

# Tools that are safe to run concurrently (all READ tools)
CONCURRENT_SAFE_TOOLS = {
    "market_brief", "account_summary", "status", "live_price",
    "analyze_market", "check_funding", "get_orders", "trade_journal",
    "thesis_state", "daemon_health",
    "read_file", "search_code", "list_files", "web_search", "memory_read",
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


def should_compact(messages: List[Dict], model: str) -> bool:
    """Check if conversation should be compacted.

    Ported from Claude Code's autoCompact.ts — triggers when token count
    exceeds (context_window - reserve - buffer).
    """
    token_count = estimate_tokens(messages)
    context_window = get_context_window(model)
    threshold = context_window - _COMPACT_RESERVE - _COMPACT_BUFFER
    return token_count >= threshold


_COMPACT_PROMPT = """Your task is to create a detailed summary of the conversation so far. This summary will replace the full conversation, so it must be comprehensive.

Create a summary with these sections:
1. **Primary Request and Intent** — What the user wants to accomplish
2. **Key Facts** — Important data points, prices, positions, decisions
3. **Actions Taken** — What tools were called and what they found
4. **Current State** — Where things stand right now
5. **Pending Tasks** — What still needs to be done
6. **Important Context** — Any rules, constraints, or preferences mentioned

Be specific with numbers, file paths, and technical details. This summary will be the only context available for future turns.

CRITICAL: Respond with plain text only. Do NOT call any tools."""


def build_compact_messages(messages: List[Dict]) -> List[Dict]:
    """Build the compaction request — sends conversation to a fast model for summarization."""
    # Format conversation for the summarizer
    conversation = []
    for m in messages:
        role = m.get("role", "unknown")
        content = str(m.get("content", ""))[:2000]  # cap per message for summarizer
        conversation.append(f"[{role}]: {content}")

    return [
        {"role": "user", "content": _COMPACT_PROMPT + "\n\n---\n\nConversation to summarize:\n\n" + "\n\n".join(conversation)},
    ]


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
