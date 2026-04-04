"""AST-based parser for Python code blocks in AI output.

Free models can't reliably use JSON function calling. Instead, the system
prompt tells them to write Python code blocks to call tools. This module
parses those code blocks using ast — NO eval/exec ever.

Security:
- ast.parse only — code never executes as Python
- Only whitelisted function names from TOOL_REGISTRY
- Only literal arguments (str, int, float, bool, None, list, dict)
- WRITE tools return pending status (approval flow unchanged)
- If parsing fails, returns empty list (graceful degradation)
"""
from __future__ import annotations

import ast
import json
import logging
import re
import textwrap
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("code_tool_parser")

# Match fenced Python code blocks
_CODE_BLOCK_RE = re.compile(
    r'```(?:python|py)?\s*\n(.*?)```',
    re.DOTALL | re.IGNORECASE,
)


@dataclass
class ToolCall:
    name: str
    args: list = field(default_factory=list)
    kwargs: dict = field(default_factory=dict)


@dataclass
class ToolResult:
    name: str
    data: dict = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: int = 0


_FAIL = object()  # Module-level sentinel for extraction failures


def _extract_literal(node: ast.expr) -> Any:
    """Extract a Python literal from an AST node. Returns _FAIL on failure."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, int, float, bool, type(None))):
            return node.value
        return _FAIL

    if isinstance(node, ast.List):
        items = [_extract_literal(elt) for elt in node.elts]
        if any(v is _FAIL for v in items):
            return _FAIL
        return items

    if isinstance(node, ast.Dict):
        keys = []
        vals = []
        for k, v in zip(node.keys, node.values):
            if k is None:
                return _FAIL
            ek = _extract_literal(k)
            ev = _extract_literal(v)
            if ek is _FAIL or ev is _FAIL:
                return _FAIL
            keys.append(ek)
            vals.append(ev)
        return dict(zip(keys, vals))

    # Negative numbers: ast.UnaryOp(op=USub, operand=Constant)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _extract_literal(node.operand)
        if inner is not _FAIL and isinstance(inner, (int, float)):
            return -inner
        return _FAIL

    return _FAIL


def parse_tool_calls(ai_output: str, registry: dict) -> List[ToolCall]:
    """Extract function calls from Python code blocks in AI output.

    Only whitelisted function names (keys of registry) are extracted.
    Only literal arguments are supported.

    Returns list of ToolCall objects, or empty list.
    """
    valid_names = set(registry.keys())
    calls: List[ToolCall] = []

    # Find all Python code blocks
    blocks = _CODE_BLOCK_RE.findall(ai_output)
    if not blocks:
        return calls

    for block in blocks:
        try:
            # Dedent first (handles models that indent code inside markdown),
            # then strip outer whitespace
            dedented = textwrap.dedent(block).strip()
            tree = ast.parse(dedented, mode="exec")
        except SyntaxError:
            log.debug("Failed to parse code block: %s", block[:100])
            continue

        # Only walk top-level statements — NOT nested calls.
        # This prevents chained calls like analyze_market(check_funding("BTC").coin)
        # from being extracted as separate calls.
        for stmt in tree.body:
            # Extract the Call node from top-level statements:
            # - Expr(value=Call)          → bare function call
            # - Assign(value=Call)        → x = func()
            # - AnnAssign(value=Call)     → x: dict = func()
            call_node = None
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call_node = stmt.value
            elif isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
                call_node = stmt.value
            elif isinstance(stmt, ast.AnnAssign) and stmt.value and isinstance(stmt.value, ast.Call):
                call_node = stmt.value

            if call_node is None:
                continue

            # Get function name — support simple names only (no attributes)
            if isinstance(call_node.func, ast.Name):
                fn_name = call_node.func.id
            elif isinstance(call_node.func, ast.Attribute):
                # e.g. tools.live_price — take the attribute name
                fn_name = call_node.func.attr
            else:
                continue

            if fn_name not in valid_names:
                continue

            # Extract positional args — only literals allowed
            args = []
            skip = False
            for arg_node in call_node.args:
                val = _extract_literal(arg_node)
                if val is _FAIL:
                    skip = True
                    break
                args.append(val)

            if skip:
                log.debug("Skipping %s: non-literal positional arg", fn_name)
                continue

            # Extract keyword args
            kwargs = {}
            for kw in call_node.keywords:
                if kw.arg is None:
                    # **kwargs — skip
                    skip = True
                    break
                kval = _extract_literal(kw.value)
                if kval is _FAIL:
                    skip = True
                    break
                kwargs[kw.arg] = kval

            if skip:
                log.debug("Skipping %s: non-literal keyword arg", fn_name)
                continue

            calls.append(ToolCall(name=fn_name, args=args, kwargs=kwargs))

    return calls


def execute_parsed_calls(
    calls: List[ToolCall],
    registry: dict,
    write_tools: set,
) -> List[ToolResult]:
    """Execute parsed tool calls against the registry.

    READ tools execute immediately.
    WRITE tools return a pending marker (caller handles approval).
    """
    results: List[ToolResult] = []

    for call in calls:
        fn = registry.get(call.name)
        if fn is None:
            results.append(ToolResult(
                name=call.name,
                error=f"Unknown tool: {call.name}",
            ))
            continue

        if call.name in write_tools:
            # Don't execute — return pending for approval flow
            results.append(ToolResult(
                name=call.name,
                data={"_pending": True, "args": call.args, "kwargs": call.kwargs},
            ))
            continue

        t0 = time.time()
        try:
            # Build kwargs from positional + keyword args
            # Map positional args to function params using inspect
            import inspect
            sig = inspect.signature(fn)
            params = list(sig.parameters.keys())

            merged_kwargs = {}
            for i, val in enumerate(call.args):
                if i < len(params):
                    merged_kwargs[params[i]] = val
            merged_kwargs.update(call.kwargs)

            data = fn(**merged_kwargs)
            duration_ms = int((time.time() - t0) * 1000)
            results.append(ToolResult(
                name=call.name,
                data=data if isinstance(data, dict) else {"result": data},
                duration_ms=duration_ms,
            ))
            log.info("Tool %s executed (%dms)", call.name, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - t0) * 1000)
            results.append(ToolResult(
                name=call.name,
                error=str(e),
                duration_ms=duration_ms,
            ))
            log.error("Tool %s failed (%dms): %s", call.name, duration_ms, e)

    return results


def strip_code_blocks(content: str) -> str:
    """Remove Python code blocks from AI output so they don't show in response."""
    return _CODE_BLOCK_RE.sub("", content).strip()
