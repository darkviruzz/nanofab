from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .domain import ArtifactRef, SampleState


class ParamType(str, Enum):
    INTEGER = "integer"
    NUMBER = "number"
    SELECT = "select"
    BOOLEAN = "boolean"
    TEXT = "text"


class ValidationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class StepParamSpec:
    key: str
    label: str
    param_type: ParamType
    unit: str = ""
    required: bool = True
    minimum: float | None = None
    maximum: float | None = None
    increment: float | None = None
    options: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class ValidationIssue:
    severity: ValidationSeverity
    message: str
    field: str = ""


@dataclass
class StepHelperTool:
    tool_id: str
    label: str
    description: str = ""


@dataclass
class StepExecutionContext:
    input_state: SampleState
    params: dict[str, Any]
    run_id: str


@dataclass
class StepExecutionResult:
    output_state: SampleState
    artifacts: list[ArtifactRef] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    warning: str = ""


class ProcessStepModule(ABC):
    step_id: str
    display_name: str
    description: str
    prerequisites: tuple[str, ...] = ()

    @abstractmethod
    def input_descriptions(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def output_descriptions(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def parameter_schema(self) -> list[StepParamSpec]:
        raise NotImplementedError

    @abstractmethod
    def default_params(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def summarize_params(self, params: dict[str, Any]) -> str:
        raise NotImplementedError

    def validate(self, params: dict[str, Any], state: SampleState) -> list[ValidationIssue]:
        return []

    def helper_tools(self) -> list[StepHelperTool]:
        return []

    def apply_helper(self, tool_id: str, params: dict[str, Any]) -> dict[str, Any]:
        return params

    @abstractmethod
    def run(self, context: StepExecutionContext) -> StepExecutionResult:
        raise NotImplementedError
