---
kind: agent_tool
last_regenerated: 2026-04-09 16:05
tool_name: edit_file
tags:
  - agent-tool
---
# Agent Tool: `edit_file`

**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`

## Description

Edit a project file by replacing a specific string. Claude Code pattern. REQUIRES APPROVAL.

## Parameters schema

```python
{'type': 'object', 'properties': {'path': {'type': 'string', 'description': 'File path relative to project root'}, 'old_str': {'type': 'string', 'description': 'Exact string to find and replace (must be unique in file)'}, 'new_str': {'type': 'string', 'description': 'Replacement string'}}, 'required': ['path', 'old_str', 'new_str']}
```

## Retrieval bounds

Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that reaches an agent prompt must have hard bounds on what it returns. Check `_tool_edit_file()` in `cli/agent_tools.py` for the clamp logic; bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.

## See also

- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)
- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`
- P10 bounds: [[Data-Discipline|Data Discipline (P10)]]

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here._
<!-- HUMAN:END -->
