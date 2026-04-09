---
kind: agent_tool
last_regenerated: 2026-04-09 14:08
tool_name: place_trade
tags:
  - agent-tool
---
# Agent Tool: `place_trade`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Place a trade order. REQUIRES USER APPROVAL before execution.

## Parameters schema

```python
{'type': 'object', 'properties': {'coin': {'type': 'string', 'description': "Market, e.g. 'BRENTOIL', 'BTC'"}, 'side': {'type': 'string', 'enum': ['buy', 'sell'], 'description': 'Buy (long) or sell (short)'}, 'size': {'type': 'number', 'description': 'Number of contracts/coins'}}, 'required': ['coin', 'side', 'size']}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_place_trade()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
