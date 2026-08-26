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
5. occurrence lineage (plan §3.5),
6. **capability updates** (plan §5.3) — the revision's set of named promises,
   re-derived from the structure the step produced.

The `ValidationReport` goes on the revision and is surfaced by the UI: a
suspicious step is visible, never silent. That is also why the balance check is
a *warning* and not a failure — a step that changes topology (a trench pinching
off, a film splitting) genuinely breaks the front-integral estimate, and the
lineage report in the same pass says so. Broken invariants, which no legitimate
process produces, fail.

Why the sixth step belongs to the gate rather than to the runtime: a capability
is a statement about *state*, and this is the one place that sees the state a
step actually produced rather than the state it intended to produce. A step that
dissolves the resist does not have to remember to retract `material:resist` —
the resist is gone, so the capability is. A step that *promises* a structural
capability and does not deliver it fails here, which is a class of process bug
that would otherwise surface three steps later as an unrunnable chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

import numpy as np

from nanofab_v3.kernel import invariants, measures, occurrences, reinit
from nanofab_v3.model import capability
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
    """The committed revision and everything the gate learned about it.

    Attributes:
        structure: The renormalised, field-scoped `Structure` of the revision.
        report: What every check found (plan §4.5's `ValidationReport`).
        lineage: What happened to each occurrence (plan §3.5).
        capabilities: The revision's capabilities after step 6 — what the next
            step's `requires` is gated against (plan §5.3).
    """

    structure: Structure
    report: ValidationReport
    lineage: LineageReport
    capabilities: frozenset[str] = field(default_factory=frozenset)


def commit(
    structure: Structure,
    *,
    parent: Structure | None = None,
    swept: float | None = None,
    field_specs: Mapping[str, FieldSpec] | None = None,
    capabilities: Iterable[str] = (),
    provides: Iterable[str] = (),
    retires: Iterable[str] = (),
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
        capabilities: The **parent** revision's capabilities. Structural ones are
            re-derived from the committed structure either way; these are the
            free-form promises that only the chain remembers.
        provides: Capabilities the step declares it produced (plan §5.3). A
            structural one the structure does not back is a failure — the step
            promised a field or a material and did not deliver it.
        retires: Capabilities the step explicitly gives up. Needed only for the
            free-form ones: a structural capability retires itself the moment its
            material or field is gone.
        policy: Reinitialisation policy — the same object the motion used.
        tolerances: What counts as a failure.
    """
    grid = structure.grid
    failures: list[str] = []
    warnings: list[str] = []

    # 1. Narrow-band reinitialisation, per material field — except where the step
    #    left the material alone. A material the step did not touch carries the
    #    parent's array, and the parent's array came out of the parent's gate, so
    #    it is already normalised: renormalising it is a measured no-op (bit-exact
    #    fixed point, and still bit-exact after twenty passes) that costs a full
    #    reinitialisation and hands back a fresh array. Keeping the parent's array
    #    instead is what makes revisions share memory at all — see `_untouched`.
    measure_before = measures.solid_measure(structure)
    normalised: dict[str, np.ndarray] = {}
    shared: list[str] = []
    displacement = 0.0
    for material in structure.materials:
        if _untouched(structure, parent, material):
            normalised[material] = parent.phi_of(material)  # type: ignore[union-attr]
            shared.append(material)
            continue
        outcome = reinit.reinitialise(grid, structure.phi_of(material), policy)
        normalised[material] = outcome.phi
        displacement = max(displacement, outcome.displacement)
    # `metadata` rides along untouched: it is a statement about the sample that
    # no step's geometry can invalidate, and the gate re-derives geometry only.
    committed = Structure(grid, normalised, dict(structure.fields), dict(structure.metadata))
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

    # 6. Capability updates (plan §5.3).
    granted, lost, broken = _update_capabilities(committed, capabilities, provides, retires)
    for name in lost:
        warnings.append(f"capability {name!r} is no longer backed by the structure")
    for name in broken:
        failures.append(f"the step declared {name!r} and the structure does not carry it")

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
        capabilities=granted,
        shared_with_parent=tuple(shared),
    )
    return CommitOutcome(
        structure=committed, report=report, lineage=lineage, capabilities=granted
    )


def _untouched(structure: Structure, parent: Structure | None, material: str) -> bool:
    """Whether the step handed this material's field back exactly as it got it.

    Identity first, because a step that simply passes a material through *does*
    hand back the parent's array — `Structure` never copies what it is given.
    Value equality second, because a step that rebuilt the field with a set
    operation that changed nothing (an etch whose front never reached this
    material, a deposit that landed nowhere near it) produces a new array with
    the parent's values, and that is the same statement about the geometry. The
    comparison costs 0.011 ms at the reference grid against 3.8 ms for the
    reinitialisation it replaces.
    """
    if parent is None or material not in parent.phi:
        return False
    mine = structure.phi_of(material)
    theirs = parent.phi_of(material)
    return mine is theirs or bool(np.array_equal(mine, theirs))


def _update_capabilities(
    structure: Structure,
    inherited: Iterable[str],
    provides: Iterable[str],
    retires: Iterable[str],
) -> tuple[frozenset[str], tuple[str, ...], tuple[str, ...]]:
    """Plan §4.5's sixth step: what this revision promises, and what it stopped promising.

    Three sources, in order of authority:

    1. **The structure itself.** Every material and every material-scoped field
       present is a capability, re-derived here rather than declared — which is
       what makes the update mechanical rather than a bookkeeping obligation on
       every process author.
    2. **What the step declared.** Free-form promises the geometry cannot see
       (`"chamber.pumped"`), plus structural ones the step wants checked.
    3. **What the parent carried**, minus what the step retired.

    Then everything structural is filtered against the structure: a capability
    whose material or field is gone is dropped and reported. That is how
    dissolving the resist retracts `resist.exposed` without any step saying so.

    Returns `(capabilities, lost, broken)` — the surviving set, the inherited
    names the structure stopped backing, and the declared ones it never backed.
    """
    declared = set(provides)
    inherited_set = set(inherited) - set(retires) - declared
    broken = tuple(
        sorted(
            name
            for name in declared
            if capability.is_structural(name) and not capability.backed_by(structure, name)
        )
    )
    lost = tuple(
        sorted(name for name in inherited_set if not capability.backed_by(structure, name))
    )
    surviving = {name for name in inherited_set if name not in lost}
    surviving |= {name for name in declared if name not in broken}
    return frozenset(surviving | capability.derived(structure)), lost, broken


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
