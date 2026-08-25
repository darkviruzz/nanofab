from __future__ import annotations

from ..domain import clone_state
from ..step_api import (
    ParamType,
    ProcessStepModule,
    StepExecutionContext,
    StepExecutionResult,
    StepParamSpec,
    ValidationIssue,
    ValidationSeverity,
)
from ._helpers import append_history, make_artifact


class CleaningStep(ProcessStepModule):
    step_id = "step_02_cleaning"
    display_name = "Cleaning"
    description = "Apply a cleaning protocol to prepare the substrate surface."
    prerequisites = ("step_01_substrate_selection",)

    def input_descriptions(self) -> list[str]:
        return ["Substrate metadata must be present."]

    def output_descriptions(self) -> list[str]:
        return [
            "Sample cleaned facet updated.",
            "Cleaning report artifact reference created.",
        ]

    def parameter_schema(self) -> list[StepParamSpec]:
        return [
            StepParamSpec(
                "method",
                "Method",
                ParamType.SELECT,
                options=["Piranha", "RCA", "Solvent", "O2 plasma"],
            ),
            StepParamSpec(
                "duration_min",
                "Duration",
                ParamType.NUMBER,
                unit="min",
                minimum=0.1,
                maximum=120.0,
                increment=0.1,
            ),
            StepParamSpec(
                "rinse",
                "Rinse",
                ParamType.SELECT,
                options=["DI", "IPA", "None"],
            ),
            StepParamSpec(
                "dry",
                "Drying",
                ParamType.SELECT,
                options=["N2", "spin-dry", "air"],
            ),
        ]

    def default_params(self) -> dict[str, object]:
        return {
            "method": "Piranha",
            "duration_min": 10.0,
            "rinse": "DI",
            "dry": "N2",
        }

    def summarize_params(self, params: dict[str, object]) -> str:
        return (
            f"{params['method']} {float(params['duration_min']):.1f} min "
            f"· {params['rinse']} rinse · {params['dry']} dry"
        )

    def validate(self, params: dict[str, object], state) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if state.substrate is None:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "No substrate defined yet."))
        if float(params.get("duration_min", 0.0)) <= 0:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "Duration must be > 0.", "duration_min"))
        return issues

    def run(self, context: StepExecutionContext) -> StepExecutionResult:
        state = clone_state(context.input_state)
        state.revision += 1

        state.facets["process.cleaning"] = {
            "method": context.params["method"],
            "duration_min": float(context.params["duration_min"]),
            "rinse": context.params["rinse"],
            "dry": context.params["dry"],
            "result": "cleaned",
        }
        state.facets["sample.cleaned"] = True

        artifact = make_artifact(
            run_id=context.run_id,
            step_id=self.step_id,
            kind="report",
            filename="cleaning_report.md",
            summary="Cleaning step summary report.",
            tags=["cleaning", "surface-prep"],
        )
        state.artifacts.append(artifact)

        append_history(
            state=state,
            step_id=self.step_id,
            step_name=self.display_name,
            params=context.params,
            artifacts=[artifact],
            notes="Substrate cleaned and marked ready for coating.",
        )

        return StepExecutionResult(
            output_state=state,
            artifacts=[artifact],
            logs=[
                f"Cleaning method: {context.params['method']}.",
                f"Duration: {float(context.params['duration_min']):.1f} min.",
                "Sample marked as cleaned.",
            ],
            outputs={"cleaned": True},
            notes="Cleaning completed.",
        )
