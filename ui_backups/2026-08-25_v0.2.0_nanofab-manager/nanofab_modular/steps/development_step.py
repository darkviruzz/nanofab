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


class DevelopmentStep(ProcessStepModule):
    step_id = "step_06_development"
    display_name = "Development"
    description = "Develop exposed resist and create patterned opening."
    prerequisites = ("step_05_projection_exposure",)

    def input_descriptions(self) -> list[str]:
        return ["Exposed resist with segmented geometry."]

    def output_descriptions(self) -> list[str]:
        return [
            "Exposed center resist segment removed (void).",
            "Patterned resist opening represented in facets.",
            "Development preview artifact reference.",
        ]

    def parameter_schema(self) -> list[StepParamSpec]:
        return [
            StepParamSpec(
                "developer",
                "Developer",
                ParamType.SELECT,
                options=["AZ 726 MIF", "MF-319", "TMAH 2.38%"],
            ),
            StepParamSpec("time_s", "Time", ParamType.INTEGER, unit="s", minimum=1, maximum=600),
        ]

    def default_params(self) -> dict[str, object]:
        return {"developer": "AZ 726 MIF", "time_s": 60}

    def summarize_params(self, params: dict[str, object]) -> str:
        return f"{params['developer']} · {int(params['time_s'])} s"

    def validate(self, params: dict[str, object], state) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        resist_layers = [layer for layer in state.layers if layer.role == "resist" and layer.status == "present"]
        if not resist_layers:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "No resist layer available for development."))
        else:
            segments = resist_layers[-1].facets.get("geometry.segments", [])
            exposed = any(segment.get("state") == "exposed" for segment in segments)
            if not exposed:
                issues.append(
                    ValidationIssue(
                        ValidationSeverity.WARNING,
                        "No exposed segment detected. Development may have no effect.",
                    )
                )
        if int(params.get("time_s", 0)) <= 0:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "Time must be > 0.", "time_s"))
        return issues

    def run(self, context: StepExecutionContext) -> StepExecutionResult:
        state = clone_state(context.input_state)
        state.revision += 1

        resist_layers = [layer for layer in state.layers if layer.role == "resist" and layer.status == "present"]
        if not resist_layers:
            raise ValueError("Cannot develop without resist layer.")
        resist_layer = resist_layers[-1]

        segments = resist_layer.facets.get("geometry.segments", [])
        if not segments:
            segments = [
                {"name": "left", "state": "unexposed", "fraction": 0.33},
                {"name": "center", "state": "exposed", "fraction": 0.34},
                {"name": "right", "state": "unexposed", "fraction": 0.33},
            ]
        for segment in segments:
            if segment.get("name") == "center" and segment.get("state") == "exposed":
                segment["state"] = "void"
        resist_layer.facets["geometry.segments"] = segments
        resist_layer.coverage = "patterned_opening"
        resist_layer.facets["process.development"] = {
            "developer": str(context.params["developer"]),
            "time_s": int(context.params["time_s"]),
            "result": "center_opening_created",
        }

        state.facets["process.development"] = dict(resist_layer.facets["process.development"])

        artifact = make_artifact(
            run_id=context.run_id,
            step_id=self.step_id,
            kind="image",
            filename="development_opening_preview.png",
            summary="Pattern opening preview after development (mock).",
            tags=["development", "patterning"],
        )
        state.artifacts.append(artifact)

        append_history(
            state=state,
            step_id=self.step_id,
            step_name=self.display_name,
            params=context.params,
            artifacts=[artifact],
            notes="Center exposed segment removed.",
        )

        return StepExecutionResult(
            output_state=state,
            artifacts=[artifact],
            logs=[
                f"Developer: {context.params['developer']}",
                f"Development time: {int(context.params['time_s'])} s",
                "Center segment converted to opening.",
            ],
            outputs={"opening_created": True, "segments": segments},
            notes="Development completed.",
        )
