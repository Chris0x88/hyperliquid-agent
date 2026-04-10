---
kind: agent_tool
last_regenerated: 2026-04-09 16:36
tool_name: introspect_self
tags:
  - agent-tool
---
# Agent Tool: `introspect_self`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Returns a live snapshot of YOUR OWN state — active model, available tools, approved markets (watchlist), open positions across all venues, thesis files with ages, last memory consolidation timestamp, and daemon health. Call this whenever you are unsure what you can do, what you are configured to know, or what state the system is in. Prefer this over guessing from prompt knowledge.

## Parameters schema

```python
{'type': 'object', 'properties': {}}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_introspect_self()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
