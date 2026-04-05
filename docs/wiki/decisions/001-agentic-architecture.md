# ADR-001: Agentic Tool-Calling Architecture (v3)

**Date:** 2026-04-02
**Status:** Accepted

## Context
The system evolved through three architectures in rapid succession. v1 (daemon-centric) built 19 iterators and a 4-phase plan but had no user-facing interface. v2 (interface-first) added rich AI context and a model selector but lacked the ability to take actions. The gap between "AI can see everything" and "AI can do nothing" was the bottleneck.

## Decision
Move to agentic tool-calling (v3). The Telegram AI agent gets 12 tools (7 read, 5 write) called via OpenRouter. Write tools require Telegram button approval before execution. Tool calling uses a triple-mode fallback chain (native, regex, code-block parsing) so free models can also use tools. Context pipeline injects live account state, technicals, and thesis into every message.

## Consequences
- AI can now research, analyze, AND act on positions through a single chat interface.
- Approval gates prevent unauthorized trades while keeping the workflow conversational.
- Triple-mode calling means model choice is decoupled from capability --- free models work.
- Added complexity: three parser paths to maintain, pending-action cleanup, approval expiry.
- Each version layered on the last: v1 daemon + v2 context + v3 tools = the full stack.
