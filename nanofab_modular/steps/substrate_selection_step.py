from __future__ import annotations

from ..domain import Substrate, clone_state
from ..step_api import (
    ParamType,
    ProcessStepModule,
    StepExecutionContext,
    StepExecutionResult,
    StepParamSpec,
    ValidationIssue,
    ValidationSeverity,
)
from ._helpers import append_history


class SubstrateSelectionStep(ProcessStepModule):
    step_id = "step_01_substrate_selection"
    display_name = "Substrate Selection"
    description = "Initialize substrate material and geometry for the run."
    prerequisites: tuple[str, ...] = ()

    def input_descriptions(self) -> list[str]:
        return ["Initial empty sample state."]

    def output_descriptions(self) -> list[str]:
        return [
            "SampleState.substrate populated.",
            "Sample marked as loaded in facets.",
        ]

    def parameter_schema(self) -> list[StepParamSpec]:
        return [
            StepParamSpec("material", "Material", ParamType.TEXT, description="Substrate material."),
            StepParamSpec(
                "form_factor",
                "Form factor",
                ParamType.SELECT,
                options=["wafer", "chip", "coupon", "other"],
            ),
            StepParamSpec(
                "diameter_mm",
                "Diameter",
                ParamType.NUMBER,
                unit="mm",
                minimum=1.0,
                maximum=300.0,
                increment=1.0,
            ),
            StepParamSpec(
                "thickness_um",
                "Thickness",
                ParamType.NUMBER,
                unit="um",
                minimum=1.0,
                maximum=5000.0,
                increment=1.0,
            ),
            StepParamSpec(
                "surface_finish",
                "Surface finish",
                ParamType.SELECT,
                options=["DSP", "SSP", "unknown"],
            ),
            StepParamSpec("lot_id", "Lot ID", ParamType.TEXT, required=False),
        ]

    def default_params(self) -> dict[str, object]:
        return {
            "material": "Fused Silica",
            "form_factor": "wafer",
            "diameter_mm": 100.0,
            "thickness_um": 500.0,
            "surface_finish": "DSP",
            "lot_id": "LOT-12",
        }

    def summarize_params(self, params: dict[str, object]) -> str:
        return (
            f"{float(params['diameter_mm']):.0f} mm {params['form_factor']} "
            f"· {params['surface_finish']} · {params.get('lot_id', '')}"
        )

    def validate(self, params: dict[str, object], _state) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if float(params.get("diameter_mm", 0.0)) <= 0:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "Diameter must be > 0.", "diameter_mm"))
        if float(params.get("thickness_um", 0.0)) <= 0:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "Thickness must be > 0.", "thickness_um"))
        return issues

    def run(self, context: StepExecutionContext) -> StepExecutionResult:
        state = clone_state(context.input_state)
        state.revision += 1

        geometry = {
            "diameter_mm": float(context.params["diameter_mm"]),
            "thickness_um": float(context.params["thickness_um"]),
        }
        state.substrate = Substrate(
            material=str(context.params["material"]),
            form_factor=str(context.params["form_factor"]),
            geometry=geometry,
            surface_finish=str(context.params["surface_finish"]),
            lot_id=str(context.params.get("lot_id", "")),
            notes="Initialized by substrate selection step.",
        )
        state.facets["sample.loaded"] = True

        append_history(
            state=state,
            step_id=self.step_id,
            step_name=self.display_name,
            params=context.params,
            artifacts=[],
            notes="Substrate initialized.",
        )

        return StepExecutionResult(
            output_state=state,
            logs=[
                f"Substrate material set to {state.substrate.material}.",
                f"Geometry: {geometry['diameter_mm']:.0f} mm, {geometry['thickness_um']:.0f} um.",
            ],
            outputs={
                "substrate_material": state.substrate.material,
                "form_factor": state.substrate.form_factor,
            },
            notes="Sample substrate metadata initialized.",
        )
