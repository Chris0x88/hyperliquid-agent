---
kind: agent_tool
last_regenerated: 2026-04-09 16:36
tool_name: close_position
tags:
  - agent-tool
---
# Agent Tool: `close_position`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Close an existing position via IOC market order. The 'side' is the CLOSING side (opposite of position direction): use 'sell' to close a long, 'buy' to close a short. REQUIRES USER APPROVAL.

## Parameters schema

```python
{'type': 'object', 'properties': {'coin': {'type': 'string', 'description': "Market identifier, e.g. 'BTC', 'xyz:BRENTOIL', 'xyz:SP500'"}, 'side': {'type': 'string', 'enum': ['buy', 'sell'], 'description': 'Closing side (opposite of position direction)'}, 'size': {'type': 'number', 'description': 'Number of contracts/coins to close'}}, 'required': ['coin', 'side', 'size']}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_close_position()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
