from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .domain import ProcStatus, SampleState, clone_state, utc_now_iso
from .step_api import (
    ProcessStepModule,
    StepExecutionContext,
    StepExecutionResult,
    ValidationIssue,
    ValidationSeverity,
)


@dataclass
class StepRuntime:
    order: int
    module: ProcessStepModule
    status: ProcStatus
    params: dict[str, Any]
    key_params: str
    notes: str = ""
    last_artifact: str = ""
    blocked_reason: str = ""
    last_logs: list[str] = None
    last_warning: str = ""

    def __post_init__(self) -> None:
        if self.last_logs is None:
            self.last_logs = []


class ProcessEngine:
    def __init__(self, modules: list[ProcessStepModule], initial_state: SampleState | None = None) -> None:
        if not modules:
            raise ValueError("At least one module is required.")

        self._order: list[str] = []
        self._steps: dict[str, StepRuntime] = {}
        self.current_state = initial_state if initial_state is not None else SampleState()
        self.revisions: list[SampleState] = [clone_state(self.current_state)]

        for idx, module in enumerate(modules, start=1):
            if module.step_id in self._steps:
                raise ValueError(f"Duplicate step_id: {module.step_id}")
            params = module.default_params()
            status = ProcStatus.READY if not module.prerequisites else ProcStatus.BLOCKED
            runtime = StepRuntime(
                order=idx,
                module=module,
                status=status,
                params=params,
                key_params=module.summarize_params(params),
            )
            self._order.append(module.step_id)
            self._steps[module.step_id] = runtime

        self.evaluate_statuses()

    def steps_in_order(self) -> list[StepRuntime]:
        return [self._steps[step_id] for step_id in self._order]

    def _reindex_orders(self) -> None:
        for idx, step_id in enumerate(self._order, start=1):
            self._steps[step_id].order = idx

    @staticmethod
    def _is_done_like(status: ProcStatus) -> bool:
        return status in (ProcStatus.DONE, ProcStatus.WARNING)

    def _first_unfinished_step_id(self) -> str | None:
        for step_id in self._order:
            if not self._is_done_like(self._steps[step_id].status):
                return step_id
        return None

    def step_at(self, row: int) -> StepRuntime:
        return self.steps_in_order()[row]

    def step_by_id(self, step_id: str) -> StepRuntime:
        return self._steps[step_id]

    def _allocate_step_id(self, base_step_id: str) -> str:
        if base_step_id not in self._steps:
            return base_step_id
        suffix = 2
        while True:
            candidate = f"{base_step_id}_{suffix}"
            if candidate not in self._steps:
                return candidate
            suffix += 1

    def insert_step(self, module: ProcessStepModule, target_index: int) -> str:
        if target_index < 0 or target_index > len(self._order):
            raise ValueError(f"Target index out of bounds: {target_index}")

        module.step_id = self._allocate_step_id(module.step_id)
        runtime = StepRuntime(
            order=target_index + 1,
            module=module,
            status=ProcStatus.BLOCKED,
            params=module.default_params(),
            key_params=module.summarize_params(module.default_params()),
            notes="",
            last_artifact="",
            blocked_reason="",
            last_logs=[],
            last_warning="",
        )
        self._steps[module.step_id] = runtime
        self._order.insert(target_index, module.step_id)
        self._reindex_orders()
        self.evaluate_statuses()
        return module.step_id

    def remove_step(self, step_id: str) -> bool:
        if step_id not in self._steps:
            return False
        runtime = self._steps[step_id]
        if runtime.status in (ProcStatus.DONE, ProcStatus.WARNING, ProcStatus.RUNNING):
            return False
        self._order = [sid for sid in self._order if sid != step_id]
        del self._steps[step_id]
        self._reindex_orders()
        self.evaluate_statuses()
        return True

    def restart_chain(self) -> None:
        self.current_state = SampleState()
        self.revisions = [clone_state(self.current_state)]
        for step_id in self._order:
            runtime = self._steps[step_id]
            if runtime.status in (ProcStatus.DONE, ProcStatus.WARNING, ProcStatus.BLOCKED, ProcStatus.READY, ProcStatus.RUNNING, ProcStatus.FAILED):
                runtime.status = ProcStatus.BLOCKED
            runtime.notes = ""
            runtime.last_artifact = ""
            runtime.blocked_reason = ""
            runtime.last_logs = []
            runtime.last_warning = ""
        self.evaluate_statuses()

    def move_step(self, step_id: str, target_index: int) -> bool:
        """
        Reorder only unfinished and non-running steps.
        Completed steps remain fixed by policy.
        """
        if step_id not in self._steps:
            return False
        if target_index < 0 or target_index >= len(self._order):
            return False

        src_idx = self._order.index(step_id)
        runtime = self._steps[step_id]
        if runtime.status in (ProcStatus.DONE, ProcStatus.WARNING, ProcStatus.RUNNING):
            return False

        first_unfinished = next(
            (
                idx
                for idx, sid in enumerate(self._order)
                if self._steps[sid].status not in (ProcStatus.DONE, ProcStatus.WARNING)
            ),
            len(self._order),
        )
        if src_idx < first_unfinished:
            return False
        if target_index < first_unfinished:
            return False

        if src_idx == target_index:
            return True

        self._order.pop(src_idx)
        if src_idx < target_index:
            target_index -= 1
        self._order.insert(target_index, step_id)
        self._reindex_orders()
        self.evaluate_statuses()
        return True

    def update_params(self, step_id: str, new_params: dict[str, Any]) -> None:
        runtime = self._steps[step_id]
        runtime.params = dict(new_params)
        runtime.key_params = runtime.module.summarize_params(runtime.params)

    def validate_step(
        self, step_id: str, params_override: dict[str, Any] | None = None
    ) -> list[ValidationIssue]:
        runtime = self._steps[step_id]
        params = runtime.params if params_override is None else params_override
        issues = runtime.module.validate(params, self.current_state)

        return issues

    def evaluate_statuses(self) -> None:
        first_unfinished = self._first_unfinished_step_id()
        if first_unfinished is None:
            return

        first_runtime = self._steps[first_unfinished]
        waiting_for = first_runtime.module.display_name

        for step_id in self._order:
            runtime = self._steps[step_id]
            if runtime.status in (ProcStatus.DONE, ProcStatus.WARNING, ProcStatus.RUNNING):
                continue
            if step_id == first_unfinished:
                runtime.status = ProcStatus.READY
                runtime.blocked_reason = ""
            else:
                runtime.status = ProcStatus.BLOCKED
                runtime.blocked_reason = f"Waiting for current step: {waiting_for}"

    def ready_steps(self) -> list[StepRuntime]:
        return [s for s in self.steps_in_order() if s.status == ProcStatus.READY]

    def run_step(self, step_id: str, run_id: str | None = None) -> StepExecutionResult:
        runtime = self._steps[step_id]
        if runtime.status != ProcStatus.READY:
            raise ValueError(f"Step '{runtime.module.display_name}' is not ready.")

        validation = self.validate_step(step_id)
        blocking = [i for i in validation if i.severity == ValidationSeverity.ERROR]
        if blocking:
            msg = "\n".join(f"- {item.message}" for item in blocking)
            raise ValueError(f"Validation failed:\n{msg}")

        runtime.status = ProcStatus.RUNNING
        runtime.notes = f"Started at {utc_now_iso()}"
        context = StepExecutionContext(
            input_state=clone_state(self.current_state),
            params=dict(runtime.params),
            run_id=run_id or uuid4().hex[:10],
        )

        try:
            result = runtime.module.run(context)
        except Exception as exc:
            runtime.status = ProcStatus.FAILED
            runtime.notes = f"Execution failed: {exc}"
            runtime.last_warning = ""
            raise

        self.current_state = result.output_state
        self.revisions.append(clone_state(self.current_state))

        runtime.last_logs = list(result.logs)
        runtime.last_warning = result.warning
        runtime.last_artifact = result.artifacts[-1].uri if result.artifacts else ""
        runtime.notes = result.notes or f"Completed at {utc_now_iso()}"
        runtime.status = ProcStatus.WARNING if result.warning else ProcStatus.DONE

        self.evaluate_statuses()
        return result

    def run_next_ready(self) -> tuple[str, StepExecutionResult] | None:
        ready = self.ready_steps()
        if not ready:
            return None
        runtime = ready[0]
        return runtime.module.step_id, self.run_step(runtime.module.step_id)
