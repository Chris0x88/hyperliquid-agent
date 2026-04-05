# ADR-009: Embedded Agent Runtime (Claude Code Port)

**Date:** 2026-04-05
**Status:** Accepted

## Context

The AI agent in the Telegram bot was a basic tool-calling wrapper — flat 3-iteration loop, 3000-char result caps, no planning, no streaming, no context management, no parallel execution. Considered adopting OpenClaw (TypeScript, too heavy, conflicts with root install), Hermes Agent (standalone app, requires rewrite), Claude Agent SDK (Anthropic-only), or Pydantic AI (framework tax). The full Claude Code source was available locally for reference.

## Decision

Port the 5 critical pieces from Claude Code's TypeScript to Python as a new file (`cli/agent_runtime.py`), keeping the existing `telegram_agent.py` as the Telegram adapter. No framework adoption — extend what exists.

Components ported: system prompt construction, parallel tool execution (StreamingToolExecutor pattern), SSE streaming parser, context compaction (autoCompact pattern), memory dream consolidation (autoDream pattern). All model-agnostic — works with any OpenRouter model or Anthropic direct.

## Consequences

- Agent quality dramatically improved via Claude Code's prompt patterns and parallel execution.
- No new framework dependency — still vanilla Python with requests.
- Streaming gives real-time Telegram output instead of 30s silence.
- Context compaction prevents crashes on long conversations.
- Memory dream auto-consolidates learnings without manual intervention.
- Trade-off: ~450 LOC of new code to maintain, but it's self-contained in one file.
