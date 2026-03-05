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


class ProjectionExposureStep(ProcessStepModule):
    step_id = "step_05_projection_exposure"
    display_name = "Projection Exposure"
    description = "Expose resist through a mask and mark center region as exposed."
    prerequisites = ("step_04_soft_bake",)

    def input_descriptions(self) -> list[str]:
        return ["Soft-baked resist layer with blanket coverage."]

    def output_descriptions(self) -> list[str]:
        return [
            "Resist geometry segmented into left/center/right bands.",
            "Center segment marked as exposed.",
            "Exposure artifact reference.",
        ]

    def parameter_schema(self) -> list[StepParamSpec]:
        return [
            StepParamSpec(
                "dose_mj_cm2",
                "Dose",
                ParamType.NUMBER,
                unit="mJ/cm^2",
                minimum=1.0,
                maximum=1000.0,
                increment=1.0,
            ),
            StepParamSpec(
                "focus_um",
                "Focus offset",
                ParamType.NUMBER,
                unit="um",
                minimum=-5.0,
                maximum=5.0,
                increment=0.1,
            ),
            StepParamSpec("mask_name", "Mask", ParamType.TEXT),
        ]

    def default_params(self) -> dict[str, object]:
        return {
            "dose_mj_cm2": 120.0,
            "focus_um": 0.2,
            "mask_name": "Mask-A",
        }

    def summarize_params(self, params: dict[str, object]) -> str:
        return (
            f"Dose {float(params['dose_mj_cm2']):.1f} mJ/cm^2 "
            f"· focus {float(params['focus_um']):+.1f} um"
        )

    def validate(self, params: dict[str, object], state) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        resist_layers = [layer for layer in state.layers if layer.role == "resist" and layer.status == "present"]
        if not resist_layers:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "No resist layer found for exposure."))
        if float(params.get("dose_mj_cm2", 0.0)) <= 0:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "Dose must be > 0.", "dose_mj_cm2"))
        return issues

    def run(self, context: StepExecutionContext) -> StepExecutionResult:
        state = clone_state(context.input_state)
        state.revision += 1

        resist_layers = [layer for layer in state.layers if layer.role == "resist" and layer.status == "present"]
        if not resist_layers:
            raise ValueError("Cannot expose without resist layer.")
        resist_layer = resist_layers[-1]

        segments = [
            {"name": "left", "state": "unexposed", "fraction": 0.33},
            {"name": "center", "state": "exposed", "fraction": 0.34},
            {"name": "right", "state": "unexposed", "fraction": 0.33},
        ]
        resist_layer.coverage = "patterned"
        resist_layer.facets["geometry.segments"] = segments
        resist_layer.facets["process.projection_exposure"] = {
            "dose_mj_cm2": float(context.params["dose_mj_cm2"]),
            "focus_um": float(context.params["focus_um"]),
            "mask_name": str(context.params["mask_name"]),
        }

        state.facets["process.projection_exposure"] = dict(resist_layer.facets["process.projection_exposure"])

        artifact = make_artifact(
            run_id=context.run_id,
            step_id=self.step_id,
            kind="image",
            filename="exposure_preview.png",
            summary="Exposure segmentation preview image (mock).",
            tags=["exposure", "mask"],
        )
        state.artifacts.append(artifact)

        append_history(
            state=state,
            step_id=self.step_id,
            step_name=self.display_name,
            params=context.params,
            artifacts=[artifact],
            notes="Resist segmented and center region exposed.",
        )

        return StepExecutionResult(
            output_state=state,
            artifacts=[artifact],
            logs=[
                f"Dose set to {float(context.params['dose_mj_cm2']):.1f} mJ/cm^2.",
                f"Focus offset set to {float(context.params['focus_um']):+.1f} um.",
                "Center segment marked as exposed.",
            ],
            outputs={"segments": segments},
            notes="Projection exposure completed.",
        )
