---
kind: agent_tool
last_regenerated: 2026-04-09 16:36
tool_name: memory_write
tags:
  - agent-tool
---
# Agent Tool: `memory_write`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Write to agent persistent memory. Creates or updates a topic file. REQUIRES APPROVAL.

## Parameters schema

```python
{'type': 'object', 'properties': {'topic': {'type': 'string', 'description': "Topic name (becomes filename, e.g. 'trading_rules')"}, 'content': {'type': 'string', 'description': 'Full content to write to the topic file (markdown)'}}, 'required': ['topic', 'content']}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_memory_write()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
