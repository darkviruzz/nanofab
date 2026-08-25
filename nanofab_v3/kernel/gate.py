"""The commit gate: the one mandatory pass every chain step ends in (plan §4.5).

The v2 successor of ADR-0001's D8. In order:

1. narrow-band reinitialisation, with the interface displacement it caused
   reported rather than assumed away,
2. field-scoping resets on the cells whose owning material changed (plan §3.3),
3. invariants: fields finite, band `|grad(phi)| ~ 1`, disjoint interiors,
   headroom guard,
4. the **balance check** — the measure that actually changed against
   `∫ rate * flux * dt` along the front, the guard against silent numerical
   drift,
5. occurrence lineage (plan §3.5).

The `ValidationReport` goes on the revision and is surfaced by the UI: a
suspicious step is visible, never silent. That is also why the balance check is
a *warning* and not a failure — a step that changes topology (a trench pinching
off, a film splitting) genuinely breaks the front-integral estimate, and the
lineage report in the same pass says so. Broken invariants, which no legitimate
process produces, fail.

Capability updates, the sixth item of plan §4.5, need the process contract of
§5.3 and arrive with it in milestone M3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

from nanofab_v3.kernel import invariants, measures, occurrences, reinit
from nanofab_v3.model.field import FieldSpec
from nanofab_v3.model.occurrence import LineageReport
from nanofab_v3.model.reports import BalanceCheck, ValidationReport
from nanofab_v3.model.structure import Structure

_GRADIENT_QUANTILE = 0.99
"""Quantile of the band gradient error the gate judges (see `invariants`)."""


@dataclass(frozen=True)
class GateTolerances:
    """What the gate is willing to accept.

    Attributes:
        balance: Relative deviation the balance check tolerates before warning.
        band_gradient_error: Worst tolerated `| |grad(phi)| - 1 |` in the band,
            read at a high quantile so a concave crease does not fail a step.
            The floor under this number is arithmetic, not empirical: at a
            **right-angled** concave crease a correct distance field is exactly
            `min(a, b)` in the two coordinates that meet there, so a central
            difference measures `1/2` per axis and `1/sqrt(2) = 0.707` in
            magnitude — an error of **0.293** that no amount of renormalisation
            can remove, because the field is right and the derivative does not
            exist. A mask corner is a right-angled crease, so a scene with a
            dozen mask windows has enough crease cells to carry the 99th
            percentile there, and any tolerance below 0.293 fails ordinary
            geometry. Measured on the reference grid, a 60 nm ion-beam etch
            through six mask windows: p90 0.053, p99 0.289, max 0.536.
        overlap_depth: Interior overlap between two materials tolerated, in nm.
            Zero: disjointness is a construction guarantee, not a target.
        allowed_boundary_faces: Domain faces the solid may touch. `None` means
            every face except the **max face of the first axis** — the headroom
            above the stack (plan §3.1), on the convention that the first axis is
            the stacking direction and grows upward. The bottom is "solid
            continues" by boundary condition, and a cross-section's lateral faces
            are the same thing sideways: a blanket layer reaches them by
            construction, so failing on them would fail every realistic scene.
            A face the step *newly* touches is warned about either way — that is
            the honest signal that the domain is running out.
    """

    balance: float = 0.05
    band_gradient_error: float = 0.35
    overlap_depth: float = 0.0
    allowed_boundary_faces: tuple[tuple[str, str], ...] | None = None


@dataclass(frozen=True)
class CommitOutcome:
    """The committed revision and everything the gate learned about it."""

    structure: Structure
    report: ValidationReport
    lineage: LineageReport


def commit(
    structure: Structure,
    *,
    parent: Structure | None = None,
    swept: float | None = None,
    field_specs: Mapping[str, FieldSpec] | None = None,
    policy: reinit.ReinitPolicy = reinit.ReinitPolicy(),
    tolerances: GateTolerances = GateTolerances(),
) -> CommitOutcome:
    """Close one chain step: renormalise, reset, check, balance, and report.

    Args:
        structure: The `Structure` the step produced.
        parent: The revision the step started from. Without it the gate cannot
            reset material-scoped fields, balance, or reconstruct lineage — which
            is right for the first revision and wrong for every later one.
        swept: `MotionOutcome.swept` of the step (summed if it moved the front
            more than once). `None` means the step moved nothing, e.g. an
            inspection step.
        field_specs: `FieldSpec` per field name, for the scoping rule's default
            values. Like `MaterialType`, a spec is library data and does not
            travel inside the `Structure`; a field with no spec is reset to 0.0
            and the report says so.
        policy: Reinitialisation policy — the same object the motion used.
        tolerances: What counts as a failure.
    """
    grid = structure.grid
    failures: list[str] = []
    warnings: list[str] = []

    # 1. Narrow-band reinitialisation, per material field.
    measure_before = measures.solid_measure(structure)
    normalised: dict[str, np.ndarray] = {}
    displacement = 0.0
    for material in structure.materials:
        outcome = reinit.reinitialise(grid, structure.phi_of(material), policy)
        normalised[material] = outcome.phi
        displacement = max(displacement, outcome.displacement)
    committed = Structure(grid, normalised, dict(structure.fields))
    measure_after = measures.solid_measure(committed)

    # 2. Field scoping: a material-scoped field means nothing where its material
    #    was just removed or just created (plan §3.3) — without this, dose from a
    #    first lithography leaks into resist deposited later.
    committed, resets = _reset_scoped_fields(committed, parent, field_specs)

    # 3. Invariants.
    gradient_error = 0.0
    for material in committed.materials:
        values = committed.phi_of(material)
        if not np.all(np.isfinite(values)):
            failures.append(f"material {material!r} has non-finite values")
        gradient_error = max(
            gradient_error,
            invariants.band_gradient_error(grid, values, quantile=_GRADIENT_QUANTILE),
        )
    if gradient_error > tolerances.band_gradient_error:
        failures.append(
            f"band |grad(phi)| - 1 is {gradient_error:.3f}, above {tolerances.band_gradient_error}"
        )
    overlap = invariants.max_overlap_depth(committed)
    if overlap > tolerances.overlap_depth:
        failures.append(f"material interiors overlap by up to {overlap:.3f} nm")
    faces = invariants.boundary_contact(committed)
    allowed = tolerances.allowed_boundary_faces
    if allowed is None:
        allowed = tuple(
            face
            for face in invariants.every_face(grid)
            if face != (grid.axes[0], "max")
        )
    already_touched = invariants.boundary_contact(parent) if parent is not None else faces
    for face in faces:
        if face not in allowed:
            failures.append(f"the front reached the {face[0]}-{face[1]} domain face (headroom)")
        elif face not in already_touched:
            warnings.append(f"the solid now reaches the {face[0]}-{face[1]} domain face")

    # 4. Balance check.
    balance: BalanceCheck | None = None
    if swept is not None and parent is not None:
        measured = measure_after - measures.solid_measure(parent)
        balance = BalanceCheck(expected=swept, measured=measured, tolerance=tolerances.balance)
        if not balance.ok:
            warnings.append(
                f"balance check off by {balance.error:.1%} "
                f"(expected {balance.expected:.4g}, measured {balance.measured:.4g})"
            )

    # 5. Occurrence lineage.
    lineage = LineageReport()
    if parent is not None:
        lineage = occurrences.match_lineage(
            occurrences.label_occurrences(parent), occurrences.label_occurrences(committed)
        )
        for entry in lineage.entries:
            if entry.kind in ("split", "merged", "vanished"):
                warnings.append(entry.describe())

    report = ValidationReport(
        failures=tuple(failures),
        warnings=tuple(warnings),
        reinit_displacement=displacement,
        reinit_measure_moved=abs(measure_after - measure_before),
        band_gradient_error=gradient_error,
        max_overlap_depth=overlap,
        boundary_faces=faces,
        balance=balance,
        field_resets=resets,
    )
    return CommitOutcome(structure=committed, report=report, lineage=lineage)


def _reset_scoped_fields(
    structure: Structure,
    parent: Structure | None,
    field_specs: Mapping[str, FieldSpec] | None,
) -> tuple[Structure, dict[str, int]]:
    """Reset material-scoped fields wherever their material appeared or vanished."""
    resets: dict[str, int] = {}
    if parent is None:
        return structure, resets

    specs = dict(field_specs or {})
    updated = structure
    for key in tuple(structure.fields):
        if key.material is None:
            continue
        if key.material not in parent.phi:
            changed = structure.inside(key.material)
        else:
            changed = structure.inside(key.material) != parent.inside(key.material)
        count = int(np.count_nonzero(changed))
        if count == 0:
            continue
        spec = specs.get(key.name)
        default = spec.default if spec is not None else 0.0
        values = np.array(structure.field(key), copy=True)
        values[changed] = default
        updated = updated.with_field(key, values)
        resets[f"{key.name}@{key.material}"] = count
    return updated, resets
