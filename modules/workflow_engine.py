"""Workflow Engine — composable step graph for dynamic reasoning pipelines.

NOT a fixed if/else router. Each WorkflowStep declares what context keys it
needs (inputs) and produces (outputs). The engine resolves dependencies
dynamically and executes steps in topological order.

Think of it like the daemon's tick-based iterators, but for *reasoning*
rather than execution. A Telegram message, a strategy evaluation, or a
self-improvement cycle all compose different step sequences from the same
pool of reusable capabilities.

Usage:
    engine = WorkflowEngine()
    engine.register(FetchPositionsStep())
    engine.register(FetchThesisStep())
    engine.register(AssembleContextStep())

    result = engine.run(
        goal="assembled_context",
        initial={"user_message": "how's my oil position?", "intent": "position_query"},
    )
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

log = logging.getLogger("workflow")


@dataclass
class WorkflowContext:
    """Mutable bag of data flowing through the workflow."""

    data: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    steps_executed: List[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def has(self, key: str) -> bool:
        return key in self.data


class WorkflowStep(ABC):
    """One composable unit of work in a workflow.

    Declare what you need (inputs) and what you produce (outputs).
    The engine figures out the rest.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique step identifier."""
        ...

    @property
    def inputs(self) -> Set[str]:
        """Context keys this step requires."""
        return set()

    @property
    @abstractmethod
    def outputs(self) -> Set[str]:
        """Context keys this step produces."""
        ...

    @abstractmethod
    def execute(self, ctx: WorkflowContext) -> None:
        """Run the step. Read from ctx, write results back to ctx."""
        ...

    def should_skip(self, ctx: WorkflowContext) -> bool:
        """Override to conditionally skip this step."""
        return False


class WorkflowEngine:
    """Resolves and executes a DAG of WorkflowSteps.

    Given a goal (desired output keys), the engine walks backwards from
    the goal to find which steps need to run, then executes in dependency
    order. Steps that don't contribute to the goal are skipped.
    """

    def __init__(self):
        self._steps: Dict[str, WorkflowStep] = {}
        self._producers: Dict[str, str] = {}  # output_key -> step_name

    def register(self, step: WorkflowStep) -> None:
        self._steps[step.name] = step
        for key in step.outputs:
            self._producers[key] = step.name

    def run(
        self,
        goal: str | Set[str],
        initial: Optional[Dict[str, Any]] = None,
        max_steps: int = 50,
    ) -> WorkflowContext:
        """Execute the minimal set of steps needed to produce `goal` keys."""
        goals = {goal} if isinstance(goal, str) else set(goal)
        ctx = WorkflowContext(data=dict(initial or {}))
        t0 = time.monotonic()

        # Resolve execution plan
        plan = self._resolve(goals, set(ctx.data.keys()))
        if not plan:
            log.debug("Workflow: nothing to do for goals=%s (already satisfied)", goals)
            ctx.elapsed_ms = (time.monotonic() - t0) * 1000
            return ctx

        log.info("Workflow plan: %s -> goals=%s", [s.name for s in plan], goals)

        for step in plan[:max_steps]:
            # Check skip conditions
            if step.should_skip(ctx):
                log.debug("Workflow: skipping %s (should_skip=True)", step.name)
                continue

            # Check inputs are satisfied
            missing = step.inputs - set(ctx.data.keys())
            if missing:
                log.warning("Workflow: %s missing inputs %s — skipping", step.name, missing)
                ctx.errors.append(f"{step.name}: missing inputs {missing}")
                continue

            try:
                step.execute(ctx)
                ctx.steps_executed.append(step.name)
            except Exception as e:
                log.error("Workflow: %s failed: %s", step.name, e)
                ctx.errors.append(f"{step.name}: {e}")

        ctx.elapsed_ms = (time.monotonic() - t0) * 1000
        log.info("Workflow complete: %d steps in %.0fms, errors=%d",
                 len(ctx.steps_executed), ctx.elapsed_ms, len(ctx.errors))
        return ctx

    def run_sequence(
        self,
        step_names: List[str],
        initial: Optional[Dict[str, Any]] = None,
    ) -> WorkflowContext:
        """Execute an explicit sequence of steps (bypass dependency resolution)."""
        ctx = WorkflowContext(data=dict(initial or {}))
        t0 = time.monotonic()

        for name in step_names:
            step = self._steps.get(name)
            if not step:
                ctx.errors.append(f"Unknown step: {name}")
                continue
            if step.should_skip(ctx):
                continue
            try:
                step.execute(ctx)
                ctx.steps_executed.append(name)
            except Exception as e:
                log.error("Workflow: %s failed: %s", name, e)
                ctx.errors.append(f"{name}: {e}")

        ctx.elapsed_ms = (time.monotonic() - t0) * 1000
        return ctx

    def _resolve(self, goals: Set[str], available: Set[str]) -> List[WorkflowStep]:
        """Topological sort: walk backwards from goals to find needed steps."""
        needed: List[str] = []  # step names in reverse dependency order
        visited: Set[str] = set()

        def _visit(key: str):
            if key in available:
                return
            producer = self._producers.get(key)
            if not producer or producer in visited:
                return
            visited.add(producer)
            step = self._steps[producer]
            # Recurse into this step's inputs
            for inp in step.inputs:
                _visit(inp)
            needed.append(producer)

        for g in goals:
            _visit(g)

        return [self._steps[name] for name in needed]

    @property
    def registered_steps(self) -> List[str]:
        return list(self._steps.keys())
