---
kind: agent_tool
last_regenerated: 2026-04-09 16:36
tool_name: read_file
tags:
  - agent-tool
---
# Agent Tool: `read_file`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Read a file from the project. Path relative to project root.

## Parameters schema

```python
{'type': 'object', 'properties': {'path': {'type': 'string', 'description': "File path relative to project root, e.g. 'cli/telegram_agent.py'"}}, 'required': ['path']}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_read_file()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
