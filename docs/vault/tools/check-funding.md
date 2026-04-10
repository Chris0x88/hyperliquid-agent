---
kind: agent_tool
last_regenerated: 2026-04-09 16:36
tool_name: check_funding
tags:
  - agent-tool
---
# Agent Tool: `check_funding`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Get funding rate, premium, and open interest for a market.

## Parameters schema

```python
{'type': 'object', 'properties': {'coin': {'type': 'string', 'description': "Coin to check, e.g. 'BTC', 'BRENTOIL'"}}, 'required': ['coin']}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_check_funding()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
