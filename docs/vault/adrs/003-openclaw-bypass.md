---
kind: adr
last_regenerated: 2026-04-09 16:36
adr_file: docs/wiki/decisions/003-openclaw-bypass.md
tags:
  - adr
  - decision
---
# ADR-003: OpenClaw Gateway Bypass

**Source**: [`docs/wiki/decisions/003-openclaw-bypass.md`](../../docs/wiki/decisions/003-openclaw-bypass.md)

## Preview

```
# ADR-003: OpenClaw Gateway Bypass

**Date:** 2026-04-02
**Status:** Accepted

## Context
OpenClaw is the user's AI agent ecosystem (`~/.openclaw/`), hosting multiple agents. The hl-trader agent routed through the OpenClaw gateway for LLM access. This gateway repeatedly failed: auth-profiles.json had empty API keys, the gateway hit IPv6 ETIMEDOUT errors, sessions dropped, and the agent used web search instead of MCP tools. Each failure required manual gateway restarts and credential re-syncing.

## Decision
Bypass the OpenClaw gateway entirely. The Telegram AI agent calls OpenRouter directly via `telegram_agent.py`. MCP tools are called as Python functions (same code, no server). Chat history persists in `data/daemon/chat_history.jsonl`. The OpenClaw boundary rule remains: never modify `~/.openclaw/` global configs.

## Consequences
- Eliminated the gateway as a single point of failure. No more auth syncing or gateway restarts.
- Full control over model selection (18 models), chat history, and context pipeline.
- Lost the ability to share the agent across OpenClaw's multi-agent ecosystem, but this was not being used.
```

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
