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


class LiftOffStep(ProcessStepModule):
    step_id = "step_08_lift_off"
    display_name = "Lift-Off"
    description = "Remove sacrificial resist and leave patterned metal in the opening."
    prerequisites = ("step_07_thin_film_deposition",)

    def input_descriptions(self) -> list[str]:
        return ["Resist + blanket metal stack after deposition."]

    def output_descriptions(self) -> list[str]:
        return [
            "Resist layer removed from stack.",
            "Metal layer switched to patterned coverage.",
            "Final structure artifact reference.",
        ]

    def parameter_schema(self) -> list[StepParamSpec]:
        return [
            StepParamSpec("solvent", "Solvent", ParamType.SELECT, options=["NMP", "Acetone", "Remover 1165"]),
            StepParamSpec("temperature_c", "Temperature", ParamType.INTEGER, unit="C", minimum=20, maximum=120),
            StepParamSpec("duration_min", "Duration", ParamType.NUMBER, unit="min", minimum=0.1, maximum=240.0),
        ]

    def default_params(self) -> dict[str, object]:
        return {"solvent": "NMP", "temperature_c": 60, "duration_min": 20.0}

    def summarize_params(self, params: dict[str, object]) -> str:
        return (
            f"{params['solvent']} {int(params['temperature_c'])} C "
            f"· {float(params['duration_min']):.1f} min"
        )

    def validate(self, params: dict[str, object], state) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        resist_present = any(layer.role == "resist" and layer.status == "present" for layer in state.layers)
        metal_present = any(layer.role == "metal" and layer.status == "present" for layer in state.layers)
        if not resist_present:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "No resist layer present for lift-off."))
        if not metal_present:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "No metal layer present for lift-off."))
        if float(params.get("duration_min", 0.0)) <= 0:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "Duration must be > 0.", "duration_min"))
        return issues

    def run(self, context: StepExecutionContext) -> StepExecutionResult:
        state = clone_state(context.input_state)
        state.revision += 1

        resist_layers = [layer for layer in state.layers if layer.role == "resist" and layer.status == "present"]
        metal_layers = [layer for layer in state.layers if layer.role == "metal" and layer.status == "present"]
        if not resist_layers:
            raise ValueError("Cannot complete lift-off without resist layer.")
        if not metal_layers:
            raise ValueError("Cannot complete lift-off without metal layer.")

        resist_layer = resist_layers[-1]
        resist_segments = resist_layer.facets.get("geometry.segments", [])
        if not isinstance(resist_segments, list) or not resist_segments:
            resist_segments = [
                {"name": "left", "state": "material", "fraction": 0.33},
                {"name": "center", "state": "void", "fraction": 0.34},
                {"name": "right", "state": "material", "fraction": 0.33},
            ]

        metal_segments: list[dict[str, object]] = []
        for segment in resist_segments:
            seg_name = str(segment.get("name", "seg"))
            seg_state = str(segment.get("state", "material")).lower()
            seg_fraction = float(segment.get("fraction", 0.0))
            # Lift-off removes metal where resist remained; keep metal only in developed openings.
            metal_state = "material" if seg_state == "void" else "void"
            metal_segments.append({"name": seg_name, "state": metal_state, "fraction": seg_fraction})

        metal_layer = metal_layers[-1]
        metal_layer.coverage = "patterned"
        metal_layer.facets["geometry.segments"] = metal_segments
        metal_layer.facets["process.lift_off"] = {
            "solvent": str(context.params["solvent"]),
            "temperature_c": int(context.params["temperature_c"]),
            "duration_min": float(context.params["duration_min"]),
            "pattern_origin": "resist opening",
        }

        state.layers = [layer for layer in state.layers if layer.role != "resist"]
        state.facets["process.lift_off"] = dict(metal_layer.facets["process.lift_off"])

        artifact = make_artifact(
            run_id=context.run_id,
            step_id=self.step_id,
            kind="image",
            filename="final_patterned_structure.png",
            summary="Final patterned metal structure preview (mock).",
            tags=["lift-off", "final-structure"],
        )
        state.artifacts.append(artifact)

        append_history(
            state=state,
            step_id=self.step_id,
            step_name=self.display_name,
            params=context.params,
            artifacts=[artifact],
            notes="Resist removed and patterned metal retained.",
        )

        return StepExecutionResult(
            output_state=state,
            artifacts=[artifact],
            logs=[
                f"Lift-off solvent: {context.params['solvent']}",
                f"Duration: {float(context.params['duration_min']):.1f} min",
                "Resist removed; metal retained only in developed openings.",
            ],
            outputs={"final_metal_coverage": metal_layer.coverage},
            notes="Lift-off completed.",
        )
