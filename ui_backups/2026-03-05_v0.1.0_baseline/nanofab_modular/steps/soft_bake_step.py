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


class SoftBakeStep(ProcessStepModule):
    step_id = "step_04_soft_bake"
    display_name = "Soft Bake"
    description = "Bake the coated resist to remove solvent and stabilize film."
    prerequisites = ("step_03_resist_coating",)

    def input_descriptions(self) -> list[str]:
        return ["Resist layer present in sample stack."]

    def output_descriptions(self) -> list[str]:
        return [
            "Resist layer updated with soft-bake metadata.",
            "Soft-bake log artifact reference.",
        ]

    def parameter_schema(self) -> list[StepParamSpec]:
        return [
            StepParamSpec(
                "temperature_c",
                "Temperature",
                ParamType.INTEGER,
                unit="C",
                minimum=20,
                maximum=250,
            ),
            StepParamSpec(
                "time_s",
                "Time",
                ParamType.INTEGER,
                unit="s",
                minimum=1,
                maximum=3600,
            ),
        ]

    def default_params(self) -> dict[str, object]:
        return {"temperature_c": 110, "time_s": 90}

    def summarize_params(self, params: dict[str, object]) -> str:
        return f"{int(params['temperature_c'])} C · {int(params['time_s'])} s"

    def validate(self, params: dict[str, object], state) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        resist_layers = [layer for layer in state.layers if layer.role == "resist" and layer.status == "present"]
        if not resist_layers:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "No resist layer found for soft-bake."))
        if int(params.get("temperature_c", 0)) <= 0:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "Temperature must be > 0.", "temperature_c"))
        return issues

    def run(self, context: StepExecutionContext) -> StepExecutionResult:
        state = clone_state(context.input_state)
        state.revision += 1

        resist_layers = [layer for layer in state.layers if layer.role == "resist" and layer.status == "present"]
        if not resist_layers:
            raise ValueError("Cannot soft-bake without a resist layer.")
        resist_layer = resist_layers[-1]

        resist_layer.properties["soft_bake_temperature_c"] = int(context.params["temperature_c"])
        resist_layer.properties["soft_bake_time_s"] = int(context.params["time_s"])
        resist_layer.facets["process.soft_bake"] = {
            "temperature_c": int(context.params["temperature_c"]),
            "time_s": int(context.params["time_s"]),
            "result": "soft_baked",
        }

        state.facets["process.soft_bake"] = dict(resist_layer.facets["process.soft_bake"])

        artifact = make_artifact(
            run_id=context.run_id,
            step_id=self.step_id,
            kind="log",
            filename="soft_bake.log",
            summary="Soft-bake execution log (mock).",
            tags=["resist", "soft-bake"],
        )
        state.artifacts.append(artifact)

        append_history(
            state=state,
            step_id=self.step_id,
            step_name=self.display_name,
            params=context.params,
            artifacts=[artifact],
            notes="Resist soft-bake metadata updated.",
        )

        return StepExecutionResult(
            output_state=state,
            artifacts=[artifact],
            logs=[
                f"Soft-bake temperature: {int(context.params['temperature_c'])} C",
                f"Soft-bake time: {int(context.params['time_s'])} s",
            ],
            outputs={"soft_baked": True},
            notes="Soft-bake completed.",
        )
