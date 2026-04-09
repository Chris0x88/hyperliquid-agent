---
kind: agent_tool
last_regenerated: 2026-04-09 16:05
tool_name: set_sl
tags:
  - agent-tool
---
# Agent Tool: `set_sl`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Place an exchange-side stop-loss trigger order. Every position MUST have a stop-loss on the exchange (hard rule). REQUIRES USER APPROVAL.

## Parameters schema

```python
{'type': 'object', 'properties': {'coin': {'type': 'string', 'description': 'Market identifier'}, 'side': {'type': 'string', 'enum': ['buy', 'sell'], 'description': "Stop side (opposite of position direction — 'sell' stops a long, 'buy' stops a short)"}, 'size': {'type': 'number', 'description': 'Size to stop'}, 'trigger_price': {'type': 'number', 'description': 'Trigger price for the stop'}}, 'required': ['coin', 'side', 'size', 'trigger_price']}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_set_sl()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
