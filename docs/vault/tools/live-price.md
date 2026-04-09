---
kind: agent_tool
last_regenerated: 2026-04-09 14:08
tool_name: live_price
tags:
  - agent-tool
---
# Agent Tool: `live_price`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Get current prices for all watched markets or a specific one.

## Parameters schema

```python
{'type': 'object', 'properties': {'market': {'type': 'string', 'description': "Optional. Specific market like 'BTC' or 'xyz:BRENTOIL'. Omit for all prices.", 'default': 'all'}}}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_live_price()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
