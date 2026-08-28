from __future__ import annotations

from ..domain import Layer, Quantity, clone_state
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


class ThinFilmDepositionStep(ProcessStepModule):
    step_id = "step_07_thin_film_deposition"
    display_name = "Thin Film Deposition"
    description = "Deposit a blanket metal layer before lift-off."
    prerequisites = ("step_06_development",)

    def input_descriptions(self) -> list[str]:
        return ["Patterned resist opening from development."]

    def output_descriptions(self) -> list[str]:
        return [
            "Metal layer added to stack.",
            "Deposition artifact reference.",
        ]

    def parameter_schema(self) -> list[StepParamSpec]:
        return [
            StepParamSpec("material", "Material", ParamType.SELECT, options=["Cr", "Au", "Al", "Ti"]),
            StepParamSpec(
                "thickness_nm",
                "Thickness",
                ParamType.NUMBER,
                unit="nm",
                minimum=1.0,
                maximum=10000.0,
                increment=1.0,
            ),
            StepParamSpec("method", "Method", ParamType.SELECT, options=["e-beam", "sputter", "thermal"]),
            StepParamSpec(
                "rate_angstrom_s",
                "Rate",
                ParamType.NUMBER,
                unit="A/s",
                minimum=0.1,
                maximum=100.0,
                increment=0.1,
            ),
        ]

    def default_params(self) -> dict[str, object]:
        return {
            "material": "Cr",
            "thickness_nm": 80.0,
            "method": "e-beam",
            "rate_angstrom_s": 0.8,
        }

    def summarize_params(self, params: dict[str, object]) -> str:
        return (
            f"{params['material']} | {float(params['thickness_nm']):.0f} nm | {params['method']} "
            f"| {float(params['rate_angstrom_s']):.1f} A/s"
        )

    def validate(self, params: dict[str, object], state) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        resist_layers = [layer for layer in state.layers if layer.role == "resist" and layer.status == "present"]
        if not resist_layers:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.WARNING,
                    "No resist layer present; lift-off patterning may not be possible.",
                )
            )
        if float(params.get("thickness_nm", 0.0)) <= 0:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "Thickness must be > 0.", "thickness_nm"))
        return issues

    def run(self, context: StepExecutionContext) -> StepExecutionResult:
        state = clone_state(context.input_state)
        state.revision += 1

        thickness_nm = float(context.params["thickness_nm"])
        layer = Layer(
            layer_id=f"metal_r{state.revision}",
            name=f"{context.params['material']} film",
            role="metal",
            material=str(context.params["material"]),
            status="present",
            thickness=Quantity(value=thickness_nm, unit="nm", source="nominal"),
            coverage="blanket",
            properties={
                "method": str(context.params["method"]),
                "rate_angstrom_s": float(context.params["rate_angstrom_s"]),
            },
        )
        state.layers.append(layer)
        state.facets["process.thin_film_deposition"] = {
            "material": layer.material,
            "thickness_nm": thickness_nm,
            "method": str(context.params["method"]),
        }

        artifact = make_artifact(
            run_id=context.run_id,
            step_id=self.step_id,
            kind="report",
            filename="deposition_report.csv",
            summary="Deposition report (mock).",
            tags=["deposition", "metal"],
        )
        state.artifacts.append(artifact)

        append_history(
            state=state,
            step_id=self.step_id,
            step_name=self.display_name,
            params=context.params,
            artifacts=[artifact],
            notes="Blanket metal layer deposited.",
        )

        return StepExecutionResult(
            output_state=state,
            artifacts=[artifact],
            logs=[
                f"Material: {layer.material}",
                f"Thickness: {thickness_nm:.1f} nm",
                f"Method: {context.params['method']}",
            ],
            outputs={"metal_layer_id": layer.layer_id},
            notes="Thin film deposition completed.",
        )
