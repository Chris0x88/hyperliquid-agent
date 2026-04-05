# Unified Tool Core + Python Code Calling

**Date:** 2026-04-03
**Status:** Design approved
**Supersedes:** agent_tools.py (9 tools), partial MCP server overlap

## Problem

Three overlapping tool systems with duplicated logic and diverging implementations:
1. **MCP server** (`cli/mcp_server.py`) — 19 tools, subprocess-based, legacy
2. **Agent tools** (`cli/agent_tools.py`) — 9 tools, direct Python, used by AI agent
3. **Telegram commands** (`cli/telegram_bot.py`) — 28 handlers, user-facing, richest set

Free models can't reliably use JSON function calling or `[TOOL: name {args}]` text syntax. Paid models work but cost money.

## Solution

### Architecture: One Source, Three Renderers

```
                    ┌─────────────────┐
                    │  Tool Registry   │
                    │  common/tools.py │
                    │  ~25 core fns    │
                    └────────┬────────┘
                             │ returns dict
                 ┌───────────┼───────────┐
                 │           │           │
                 ▼           ▼           ▼
          Human Format   AI Format    Raw Data
          (Telegram)     (compact)    (Python)
          telegram_bot   AI agent     daemon/tests
```

### Layer 1: Tool Core — `common/tools.py` (NEW)

Each tool is a plain Python function that returns a dict. No formatting, no Telegram, no AI concerns. Single source of truth.

```python
# common/tools.py

def status() -> dict:
    """Account equity, open positions with entry/uPnL/leverage/liq, spot balances, alerts."""
    # Queries both clearinghouses + spot
    # Returns {"equity": 732.90, "positions": [...], "alerts": [...]}

def live_price(market: str = "all") -> dict:
    """Current mid prices for watched markets or a specific one."""
    # Returns {"BTC": 82450.0, "xyz:BRENTOIL": 108.1, ...}

def analyze_market(coin: str, interval: str = "1h", days: int = 30) -> dict:
    """Technicals: EMA, RSI, trend, S/R, BBands, volume."""
    # Returns {"price": 108.1, "rsi": 62.3, "trend": "up", "support": [...], ...}

def market_brief(market: str) -> dict:
    """Full market context: price, technicals, position, thesis, memory."""
    # Calls status() + analyze_market() + thesis + memory, assembles

def check_funding(coin: str) -> dict:
    """Funding rates, OI, volume for a market."""
    # Returns {"funding_rate": -0.0012, "oi": 45000000, "volume_24h": ...}

def get_orders() -> dict:
    """All open orders (trigger, limit, stop) across both clearinghouses."""
    # Returns {"orders": [...]}

def get_candles(coin: str, interval: str = "1h", days: int = 7) -> dict:
    """OHLCV candle data with digest stats."""
    # Returns {"candles": [...], "high": ..., "low": ..., "range_pct": ...}

def trade_journal(limit: int = 10) -> dict:
    """Recent trade records with PnL."""
    # Returns {"entries": [...]}

def agent_memory(query_type: str = "recent", limit: int = 10) -> dict:
    """Learnings, observations, playbook data."""
    # Returns {"events": [...]} or {"playbook": {...}}

def thesis_state(market: str = "all") -> dict:
    """Current thesis conviction, direction, age for markets."""
    # Returns {"xyz:BRENTOIL": {"conviction": 0.8, "direction": "long", ...}, ...}

def daemon_health() -> dict:
    """Daemon status: tier, tick count, strategies, risk gate."""
    # Returns {"tier": "watch", "tick": 997, "gate": "OPEN", ...}

def diagnostic_report() -> dict:
    """Tool call stats, recent errors, uptime."""
    # Returns {"uptime_s": ..., "tool_calls": ..., "errors": [...]}

def cache_stats() -> dict:
    """Candle cache summary."""
    # Returns {"coins": [...], "total_candles": ..., ...}

def log_bug(title: str, description: str, severity: str = "medium") -> dict:
    """Write bug report to data/bugs.md."""
    # Returns {"logged": True, "title": title}

def log_feedback(text: str, category: str = "general") -> dict:
    """Write feedback to data/feedback.jsonl."""
    # Returns {"logged": True, "category": category}

# --- WRITE tools (require approval in AI context) ---

def place_trade(coin: str, side: str, size: float) -> dict:
    """Place a market order."""
    # Returns {"filled": True, "coin": ..., "side": ..., "size": ..., "price": ...}

def update_thesis(market: str, direction: str, conviction: float, summary: str) -> dict:
    """Update thesis conviction file."""
    # Returns {"updated": True, "old_conviction": ..., "new_conviction": ...}

def set_leverage(coin: str, leverage: float) -> dict:
    """Set leverage for a market."""
    # Returns {"set": True, "coin": ..., "leverage": ...}
```

**~18 core functions.** Each returns a dict. Each has a docstring the AI can read.

### Layer 2: Renderers

#### Human renderer — `common/tool_renderers.py` (NEW)

```python
def render_for_telegram(tool_name: str, data: dict) -> str:
    """Format tool output for Telegram — bold, arrows, emojis, markdown."""
    renderers = {
        "status": _render_status_telegram,
        "live_price": _render_price_telegram,
        "analyze_market": _render_analysis_telegram,
        # ... one per tool
    }
    return renderers.get(tool_name, _render_generic)(data)

def _render_status_telegram(data: dict) -> str:
    """
    💰 *$732.90* equity

    📊 *Positions:*
    🛢️ BRENTOIL  LONG 20 @ $104.98 | uPnL -$12.30 | 10x
    ...
    """
```

Telegram commands (`/status`, `/price`, etc.) call: `core function → render_for_telegram()`.

All existing Telegram formatting is preserved — just moved into renderer functions.

#### AI renderer — `common/tool_renderers.py`

```python
def render_for_ai(tool_name: str, data: dict) -> str:
    """Format tool output for AI agent — compact, token-efficient, no decoration."""
    renderers = {
        "status": _render_status_ai,
        "live_price": _render_price_ai,
        # ...
    }
    return renderers.get(tool_name, _render_generic_ai)(data)

def _render_status_ai(data: dict) -> str:
    """equity=$732.90 | BRENTOIL L20@104.98 uPnL=-12.30 10x liq=96.2"""
```

### Layer 3: AI Tool Calling via Python Code

#### How the AI calls tools

System prompt tells the AI: "You have these functions available. To use them, write a Python code block."

The AI writes:
```python
prices = live_price("BRENTOIL")
account = status()
funding = check_funding("BRENTOIL")
```

#### AST Parser — `common/code_tool_parser.py` (NEW)

Parses AI output for Python code blocks. Uses `ast` module — NO eval/exec.

```python
import ast

TOOL_REGISTRY = {
    "status": tools.status,
    "live_price": tools.live_price,
    "analyze_market": tools.analyze_market,
    # ... all core functions
}

WRITE_TOOLS = {"place_trade", "update_thesis", "set_leverage"}

def parse_tool_calls(ai_output: str) -> list[ToolCall]:
    """Extract function calls from Python code blocks in AI output.

    Returns list of ToolCall(name, args, kwargs) objects.
    Only whitelisted function names are extracted.
    """
    # 1. Find ```python ... ``` blocks in the AI output
    # 2. ast.parse() each block
    # 3. Walk AST for ast.Call nodes
    # 4. Match function names against TOOL_REGISTRY
    # 5. Extract literal arguments (strings, numbers, bools only)
    # 6. Return structured ToolCall list

def execute_parsed_calls(calls: list[ToolCall]) -> list[ToolResult]:
    """Execute parsed tool calls against the registry.

    READ tools execute immediately, return ai_format results.
    WRITE tools return pending confirmation (same approval flow).
    """
```

**Security:**
- AST parsing only — code never executes as Python
- Only whitelisted function names from TOOL_REGISTRY
- Only literal arguments (strings, numbers, bools) — no expressions, no variables
- WRITE tools still go through Telegram approval buttons
- If parsing fails, gracefully degrade to context-only response

#### Integration into telegram_agent.py

Replace the current dual-mode tool calling loop:

```python
# OLD: regex [TOOL: name {args}] or native tool_calls
# NEW: parse Python code blocks from AI output

from common.code_tool_parser import parse_tool_calls, execute_parsed_calls

# In handle_ai_message():
for _loop in range(_MAX_TOOL_LOOPS):
    content = response.get("content") or ""

    # Try native tool_calls first (paid models)
    tool_calls = response.get("tool_calls")

    # If no native calls, parse Python code blocks (free models)
    if not tool_calls:
        parsed = parse_tool_calls(content)
        if parsed:
            results = execute_parsed_calls(parsed)
            # Feed results back as next message
            # ...

    if not tool_calls and not parsed:
        break  # No tools requested, done
```

### Layer 4: Telegram Commands (MINIMAL CHANGE)

Existing Telegram command handlers change from inline logic to:

```python
# Before (in telegram_bot.py):
def _handle_status(token, chat_id, text):
    # 80 lines of API calls, formatting, emoji...

# After:
def _handle_status(token, chat_id, text):
    from common.tools import status
    from common.tool_renderers import render_for_telegram
    data = status()
    msg = render_for_telegram("status", data)
    _tg_send(token, chat_id, msg)
```

**Important:** This refactor happens incrementally, one command at a time. Not a big-bang rewrite. Each command migrates from inline logic to `core function → renderer`. The old inline code is the reference for what the renderer should output.

### MCP Server (OPTIONAL)

The MCP server (`cli/mcp_server.py`) can be rewired to call core functions:

```python
@mcp.tool()
def market_context(market: str = "xyz:BRENTOIL") -> str:
    from common.tools import market_brief
    from common.tool_renderers import render_for_ai
    return render_for_ai("market_brief", market_brief(market))
```

Or deprecated entirely if OpenClaw is gone. Low priority.

## File Changes Summary

| File | Action |
|------|--------|
| `common/tools.py` | NEW — ~18 core functions returning dicts |
| `common/tool_renderers.py` | NEW — telegram + AI format functions |
| `common/code_tool_parser.py` | NEW — AST-based Python code parser |
| `cli/telegram_agent.py` | MODIFY — replace regex/JSON parsing with code parser |
| `cli/telegram_bot.py` | MODIFY — incrementally migrate commands to core + renderer |
| `cli/agent_tools.py` | DEPRECATE — replaced by tools.py + code_tool_parser |
| `cli/mcp_server.py` | OPTIONAL — rewire to core functions or deprecate |

## What Stays the Same

- All 28 Telegram slash commands keep their exact formatting
- WRITE tool approval flow (inline keyboard buttons)
- Context pipeline (account + technicals + thesis + memory injection)
- Chat history + sanitization
- OpenRouter integration + model switching
- Daemon, heartbeat, vault rebalancer — untouched

## Migration Strategy

1. **Phase A:** Create `common/tools.py` with core functions (extract from existing code)
2. **Phase B:** Create `common/code_tool_parser.py` (AST parser)
3. **Phase C:** Create `common/tool_renderers.py` (AI format first, telegram format later)
4. **Phase D:** Wire AI agent to use code parser + core tools
5. **Phase E:** Incrementally migrate Telegram commands to core + telegram renderer
6. **Phase F:** Deprecate `agent_tools.py` and optionally MCP server

Each phase is independently testable. No big-bang rewrite.

## Success Criteria

1. Free models reliably call tools via Python code blocks
2. Telegram commands produce identical output to current
3. AI gets compact, token-efficient tool results
4. WRITE tools still require approval
5. New tools added in ONE place (common/tools.py) + renderers
6. All existing tests pass
