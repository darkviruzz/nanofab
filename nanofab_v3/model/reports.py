"""`ValidationReport` — what the commit gate stores on a revision (plan §4.5).

Every chain step ends in one mandatory pass whose result is kept with the
revision and surfaced by the UI: "a suspicious step is visible, never silent".
The report is data only — the gate in `nanofab_v3.kernel.gate` produces it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BalanceCheck:
    """Swept measure from the front integral against the measured change (§4.5.4).

    Attributes:
        expected: `∫ rate · flux · dt` along the front, in nm^ndim — what the
            motion says it moved.
        measured: The change of the solid's enclosed measure over the step.
        tolerance: Relative tolerance the check was run against.
    """

    expected: float
    measured: float
    tolerance: float

    @property
    def error(self) -> float:
        """Relative deviation of measured from expected (0.0 when both are 0)."""
        scale = max(abs(self.expected), abs(self.measured))
        if scale == 0.0:
            return 0.0
        return abs(self.measured - self.expected) / scale

    @property
    def ok(self) -> bool:
        """Whether the step closed its balance within tolerance."""
        return self.error <= self.tolerance


@dataclass(frozen=True)
class ValidationReport:
    """The commit gate's verdict on one chain step.

    Attributes:
        failures: Invariant violations — a non-empty tuple means the step is bad.
        warnings: Findings worth surfacing that do not fail the step.
        reinit_displacement: Largest interface move the reinitialisation caused,
            in nm (plan §4.2 requires this to be reported, not hidden).
        reinit_measure_moved: How much enclosed measure the reinitialisation
            moved, in nm^ndim ("the area the normalisation moved").
        band_gradient_error: Worst `| |grad(phi)| - 1 |` in the narrow band after
            the gate ran.
        max_overlap_depth: Deepest interior overlap between two materials, in nm.
        boundary_faces: Domain faces the solid touches after the step.
        balance: The balance check, when the step reported a motion.
        field_resets: Per reset `Field`, how many cells were returned to the
            field's default by the scoping rule (plan §3.3).
    """

    failures: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    reinit_displacement: float = 0.0
    reinit_measure_moved: float = 0.0
    band_gradient_error: float = 0.0
    max_overlap_depth: float = 0.0
    boundary_faces: tuple[tuple[str, str], ...] = ()
    balance: BalanceCheck | None = None
    field_resets: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Whether every invariant held."""
        return not self.failures

    def describe(self) -> tuple[str, ...]:
        """The report as lines, for the run log and the UI."""
        lines = [f"FAIL {message}" for message in self.failures]
        lines += [f"warn {message}" for message in self.warnings]
        lines.append(
            f"reinit moved the interface by {self.reinit_displacement:.4g} nm "
            f"({self.reinit_measure_moved:.4g} nm^d of measure)"
        )
        if self.balance is not None:
            lines.append(
                f"balance: expected {self.balance.expected:.6g}, "
                f"measured {self.balance.measured:.6g} "
                f"({self.balance.error:.2%} off, tolerance {self.balance.tolerance:.0%})"
            )
        for name, cells in self.field_resets.items():
            lines.append(f"field {name}: {cells} cells reset to default")
        return tuple(lines)
