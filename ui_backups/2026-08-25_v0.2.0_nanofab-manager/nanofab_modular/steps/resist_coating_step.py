from __future__ import annotations

from ..domain import Layer, Quantity, clone_state
from ..step_api import (
    ParamType,
    ProcessStepModule,
    StepExecutionContext,
    StepExecutionResult,
    StepHelperTool,
    StepParamSpec,
    ValidationIssue,
    ValidationSeverity,
)
from ._helpers import append_history, make_artifact


class ResistCoatingStep(ProcessStepModule):
    step_id = "step_03_resist_coating"
    display_name = "Resist Coating"
    description = "Configure spin coat parameters and create resist layer in state."
    prerequisites = ("step_02_cleaning",)

    def input_descriptions(self) -> list[str]:
        return [
            "Cleaned substrate state.",
            "Spin program and target thickness parameters.",
        ]

    def output_descriptions(self) -> list[str]:
        return [
            "Resist layer added to stack.",
            "Predicted thickness and mismatch diagnostics.",
            "Validation artifact reference.",
        ]

    def parameter_schema(self) -> list[StepParamSpec]:
        return [
            StepParamSpec("resist", "Resist", ParamType.SELECT, options=["AZ10XT", "S1813", "SU-8", "Custom"]),
            StepParamSpec("spread_rpm", "Spread speed", ParamType.INTEGER, unit="rpm", minimum=100, maximum=10000),
            StepParamSpec("spread_s", "Spread time", ParamType.INTEGER, unit="s", minimum=1, maximum=600),
            StepParamSpec("spin_rpm", "Spin speed", ParamType.INTEGER, unit="rpm", minimum=100, maximum=10000),
            StepParamSpec("spin_s", "Spin time", ParamType.INTEGER, unit="s", minimum=1, maximum=600),
            StepParamSpec(
                "target_thickness_um",
                "Target thickness",
                ParamType.NUMBER,
                unit="um",
                minimum=0.1,
                maximum=100.0,
                increment=0.1,
            ),
            StepParamSpec("ebr_enabled", "Enable EBR", ParamType.BOOLEAN, required=False),
            StepParamSpec(
                "ebr_solvent",
                "EBR solvent",
                ParamType.SELECT,
                options=["PGMEA", "Acetone", "IPA"],
            ),
            StepParamSpec("softbake_c", "Softbake temperature", ParamType.INTEGER, unit="C", minimum=20, maximum=250),
            StepParamSpec("softbake_s", "Softbake time", ParamType.INTEGER, unit="s", minimum=1, maximum=3600),
        ]

    def default_params(self) -> dict[str, object]:
        return {
            "resist": "AZ10XT",
            "spread_rpm": 500,
            "spread_s": 5,
            "spin_rpm": 3000,
            "spin_s": 45,
            "target_thickness_um": 8.0,
            "ebr_enabled": True,
            "ebr_solvent": "PGMEA",
            "softbake_c": 110,
            "softbake_s": 90,
        }

    def summarize_params(self, params: dict[str, object]) -> str:
        return (
            f"{params['resist']} | {int(params['spin_rpm'])} rpm | {int(params['spin_s'])} s "
            f"| target {float(params['target_thickness_um']):.1f} um"
        )

    def helper_tools(self) -> list[StepHelperTool]:
        return [
            StepHelperTool(
                tool_id="auto_tune_spin",
                label="Auto-tune spin to target",
                description="Adjust spin RPM to reduce thickness mismatch.",
            )
        ]

    def apply_helper(self, tool_id: str, params: dict[str, object]) -> dict[str, object]:
        if tool_id != "auto_tune_spin":
            return params
        tuned = dict(params)
        tuned["spin_rpm"] = self._autotune_rpm(
            resist=str(params["resist"]),
            target_thickness_um=float(params["target_thickness_um"]),
        )
        return tuned

    def validate(self, params: dict[str, object], state) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if state.substrate is None:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "Substrate is not defined."))
        if float(params.get("target_thickness_um", 0.0)) <= 0:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    "Target thickness must be > 0.",
                    "target_thickness_um",
                )
            )
        spin_rpm = int(params.get("spin_rpm", 0))
        if spin_rpm < 100 or spin_rpm > 10000:
            issues.append(ValidationIssue(ValidationSeverity.ERROR, "Spin RPM is outside allowed range.", "spin_rpm"))
        if spin_rpm < 500 or spin_rpm > 6000:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.WARNING,
                    "Spin RPM is outside recommended range (500..6000).",
                    "spin_rpm",
                )
            )
        if not state.facets.get("sample.cleaned", False):
            issues.append(
                ValidationIssue(
                    ValidationSeverity.WARNING,
                    "Cleaning marker not found; adhesion risk may be higher.",
                )
            )
        return issues

    def run(self, context: StepExecutionContext) -> StepExecutionResult:
        state = clone_state(context.input_state)
        state.revision += 1

        resist = str(context.params["resist"])
        spin_rpm = int(context.params["spin_rpm"])
        target = float(context.params["target_thickness_um"])
        predicted = self._predict_thickness(resist, spin_rpm)
        delta = abs(predicted - target)

        state.layers = [layer for layer in state.layers if layer.role != "resist"]
        layer = Layer(
            layer_id=f"resist_r{state.revision}",
            name=f"{resist} Resist",
            role="resist",
            material=resist,
            status="present",
            thickness=Quantity(value=predicted, unit="um", source="estimated"),
            coverage="blanket",
            properties={
                "target_thickness_um": target,
                "spread_rpm": int(context.params["spread_rpm"]),
                "spread_s": int(context.params["spread_s"]),
                "spin_rpm": spin_rpm,
                "spin_s": int(context.params["spin_s"]),
                "ebr_enabled": bool(context.params["ebr_enabled"]),
                "ebr_solvent": str(context.params["ebr_solvent"]),
            },
            facets={"process.resist_coating": {"delta_um": delta}},
        )
        state.layers.append(layer)

        state.facets["process.resist_coating"] = {
            "resist": resist,
            "predicted_thickness_um": predicted,
            "target_thickness_um": target,
            "delta_um": delta,
        }

        artifact = make_artifact(
            run_id=context.run_id,
            step_id=self.step_id,
            kind="plot",
            filename="resist_thickness_prediction.png",
            summary="Predicted thickness vs target plot (mock).",
            tags=["resist", "coating", "thickness"],
        )
        state.artifacts.append(artifact)

        warning = ""
        if delta > 0.25:
            warning = (
                "Thickness mismatch risk: predicted "
                f"{predicted:.2f} um vs target {target:.2f} um (delta {delta:.2f} um)."
            )

        append_history(
            state=state,
            step_id=self.step_id,
            step_name=self.display_name,
            params=context.params,
            artifacts=[artifact],
            notes="Resist layer added to stack.",
            status="warning" if warning else "done",
        )

        return StepExecutionResult(
            output_state=state,
            artifacts=[artifact],
            logs=[
                f"Resist: {resist}",
                f"Spin: {spin_rpm} rpm",
                f"Predicted thickness: {predicted:.2f} um",
                f"Target thickness: {target:.2f} um",
            ],
            outputs={
                "layer_id": layer.layer_id,
                "predicted_thickness_um": predicted,
                "delta_um": delta,
            },
            notes="Resist coating completed.",
            warning=warning,
        )

    @staticmethod
    def _predict_thickness(resist: str, rpm: int) -> float:
        base = 8.0
        if resist == "S1813":
            base = 1.5
        elif resist == "SU-8":
            base = 20.0
        return base * (3000.0 / max(200.0, float(rpm))) ** 0.35

    def _autotune_rpm(self, resist: str, target_thickness_um: float) -> int:
        base = 8.0
        if resist == "S1813":
            base = 1.5
        elif resist == "SU-8":
            base = 20.0
        rpm = int(3000.0 * (base / max(0.1, target_thickness_um)) ** (1.0 / 0.35))
        return max(100, min(10000, rpm))
