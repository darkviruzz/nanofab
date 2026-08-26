"""Region operations: removing material in one exact set operation (plan §3.2).

The **ideal tier** of the process set. Where a rate-driven process advects a
front sub-step by sub-step, an ideal one names a region and removes it: ideal
development removes `resist & exposed` where reachable, an ideal dissolution
removes the reachable occurrences of a material, lift-off removes what support no
longer reaches. All three are one `csg.difference` per affected material and no
time integration at all — plan §3.3's ideal/physical split, expressed as two
different *kinds* of operation rather than as a flag inside one.

Two things make this exact rather than a cell-quantised approximation, and both
matter for the acceptance scenarios:

- **A material that loses nothing is not touched.** Its field keeps every
  sub-cell value it had, which is what keeps S1's pattern width a measurement of
  the process rather than of this module.
- **A removed region's boundary lies in empty space.** Every caller here removes
  *whole connected components* — a reachable occurrence, an unsupported
  component — and components are separated from what stays by at least one empty
  cell. So the cell-quantised boundary of the removed mask never becomes the
  binding constraint on a surviving material's field.

Removing an arbitrary mask would not have that property. It is still allowed, and
still correct as a *set* operation; what it costs is the sub-cell accuracy of the
kept material's surface along the cut, which the commit gate's reinitialisation
then re-derives from a cell-quantised interface. Callers that care say so by
removing components.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
from scipy import ndimage

from nanofab_v3.kernel import csg
from nanofab_v3.materials import MaterialId
from nanofab_v3.model.grid import PHI_DTYPE, Grid
from nanofab_v3.model.structure import Structure


def closed_region(grid: Grid, phi: np.ndarray) -> np.ndarray:
    """The cells one material really occupies: its interior, plus its own boundary.

    Not `phi <= 0`, and the difference is a third milestone's worth of the same
    lesson. §17.1 records that the *union* field is exactly zero along a buried
    interface between two touching materials. A **material's own** field has the
    same defect for the same reason: `constructors.add_material` carves the new
    region against the union of the others (`max(phi_new, -phi_union)`), and
    `-phi_union` is exactly zero along every interface between two of those
    others — interfaces the new material may be nowhere near.

    Measured on the S2 stack (silicon, 60 nm of oxide on it, resist spun on top):
    `phi_resist` reads exactly 0.0 along the buried silicon/oxide interface, 60 nm
    below the resist's own underside and in **every column of the domain**. A
    `phi <= 0` test therefore reported the resist as covering the whole width, and
    the undercut predicate — which measures against the mask's footprint —
    returned zero for every etch, wet and directional alike.

    The repair is topological rather than numerical: take the closure of the
    *interior*. A zero-valued cell counts only when it touches a cell that is
    strictly inside, which is exactly what distinguishes a material's own
    boundary from a zero level with nothing behind it (§18.7's phantom, in its
    third disguise).
    """
    values = np.asarray(phi)
    interior = values < 0.0
    if not interior.any():
        return interior
    neighbourhood = ndimage.generate_binary_structure(grid.ndim, 1)
    return (values <= 0.0) & ndimage.binary_dilation(interior, neighbourhood)


def signed_distance_of(grid: Grid, mask: np.ndarray) -> np.ndarray:
    """A signed-distance field for a boolean cell mask, negative inside.

    Two Euclidean distance transforms, shifted half a cell so the zero level sits
    *between* the last inside cell and the first outside one rather than on top of
    one of them. Without that shift the outermost cell of the mask reads exactly
    `-spacing` and the region comes out half a cell too large in every direction —
    which on a 2 nm film is a 50 % error.

    Cell-quantised by construction: a mask has no sub-cell information to recover,
    and pretending otherwise is how a "correct set operation" becomes a useless
    field (§17.2). An empty mask is `+inf` everywhere, a full one `-inf`, which
    are the right answers and keep `csg.difference` well behaved on both.
    """
    cells = np.asarray(mask, dtype=bool)
    if not cells.any():
        return grid.full(np.inf)
    if cells.all():
        return grid.full(-np.inf)
    half = 0.5 * grid.spacing
    inside = ndimage.distance_transform_edt(cells, sampling=grid.spacing)
    outside = ndimage.distance_transform_edt(~cells, sampling=grid.spacing)
    return np.where(cells, half - inside, outside - half).astype(PHI_DTYPE)


def remove_region(
    structure: Structure,
    removed: np.ndarray,
    *,
    materials: Sequence[MaterialId] | None = None,
) -> Structure:
    """Take `removed` out of `materials`, dropping the ones left with nothing.

    The single primitive behind development, dissolution, stripping and lift-off.
    Each material is clipped with `csg.difference(phi_m, phi_removed)` —
    `max(phi_m, -phi_removed)`, the plan's own formula — and a material left with
    no interior at all is dropped from the `Structure` outright, together with its
    scoped fields.

    Dropping rather than keeping an all-positive field is what makes the
    capability update mechanical: `material:resist` disappears from the revision
    because the resist did, and nothing had to remember to retract it.

    A material that loses no cell is returned untouched — not re-derived, not
    re-clipped. That is not an optimisation: `max(phi_m, -phi_removed)` understates
    `phi_m` wherever the removed region happens to be nearer than the material's
    own surface (§17.2), so touching a material that lost nothing would trade
    exact values for a repair the gate then has to make.

    **`materials` is not a convenience.** A *material-selective* removal — a
    solvent, a developer — must name what it attacks, because two touching
    materials share their interface cell: `phi` is exactly zero there for both
    (§17.1), so a mask covering the resist's closed region also covers the
    substrate's top row. Measured on the T-profile fixture: dissolving the resist
    without naming it took half a nanometre of silicon with it, along every cell
    the two shared. With `materials=("resist",)` the substrate is not a candidate
    and keeps its field untouched.

    `materials=None` means every material, which is right for a removal that is
    about *connectivity* rather than chemistry — lift-off's unsupported
    components, a whole occurrence carried away. There the shared-interface
    problem cannot arise: the removed region is a union of complete solid
    components, and a component is separated from what stays by empty space.
    """
    grid = structure.grid
    cells = grid.as_field(removed, dtype=bool)
    if not cells.any():
        return structure

    phi = dict(structure.phi)
    fields = dict(structure.fields)
    dropped: list[MaterialId] = []
    changed = False
    candidates = structure.materials if materials is None else tuple(materials)
    for material in candidates:
        if material not in phi:
            raise KeyError(f"no material {material!r} in this Structure")
        # The material's **closed** region — not its interior. A material's own
        # boundary cells read exactly zero (§17.1), and leaving them behind
        # leaves a one-cell rind that `inside` cannot see and `solid_mask`
        # counts as solid: a dissolved resist that still walls off the cavity it
        # was supposed to open. `closed_region` is also what keeps a phantom
        # zero on somebody else's buried seam out of the removal.
        region = closed_region(grid, phi[material])
        losing = region & cells
        if not losing.any():
            continue
        changed = True
        clipped = csg.difference(phi[material], signed_distance_of(grid, losing))
        if not np.any(clipped < 0.0):
            dropped.append(material)
            continue
        phi[material] = clipped

    if not changed:
        return structure
    for material in dropped:
        del phi[material]
        fields = {key: values for key, values in fields.items() if key.material != material}
    return Structure(grid, phi, fields, dict(structure.metadata))


def region_measure(structure: Structure, mask: np.ndarray) -> float:
    """Area (2D) / volume (3D) of a cell mask, in nm^ndim.

    Cell counting, deliberately: a mask *is* a set of cells, and dressing it in a
    sub-cell measure would claim an accuracy it does not have. For the sub-cell
    answer, measure the field (`measures.enclosed_measure`), not the mask.
    """
    return structure.measure(mask)
