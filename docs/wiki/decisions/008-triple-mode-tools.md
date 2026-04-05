# ADR-008: Triple-Mode Tool Calling

**Date:** 2026-04-02
**Status:** Accepted

## Context
The AI agent needs to call tools (check prices, place trades, read thesis). Paid models support native `tool_calls` in the API response, but free models on OpenRouter do not. Requiring paid models would limit accessibility and increase costs.

## Decision
Build a triple-mode fallback chain in `telegram_agent.py`. Mode 1: native `tool_calls` (paid models, structured JSON). Mode 2: regex parser for `[TOOL: name {args}]` patterns (free models). Mode 3: AST-based Python code block parser in `common/code_tool_parser.py` (free models writing Python). All three modes converge at the same `execute_tool()` entry point in `agent_tools.py`.

## Consequences
- Model choice is decoupled from tool capability. Free models (Llama, Mistral) can use all 12 tools.
- Three parser paths to maintain, but they share the same execution layer.
- The code-block parser uses Python AST, so it safely handles free-model hallucinated code without eval.
- Native tool_calls remain the preferred path for paid models --- no performance penalty.
- 18 models available across all three modes via OpenRouter.
