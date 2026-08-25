"""Set operations on signed-distance fields — pointwise min/max (plan §3.2).

Every operation is O(cells), local, N-D generic and free of any boolean cascade
or polygonization: this is what makes v1's fragmentation and sliver failure class
(ADR-0001 F3/F4) structurally impossible.

    union(A, B)        = min(phi_A, phi_B)
    intersection(A, B) = max(phi_A, phi_B)
    difference(A, B)   = max(phi_A, -phi_B)
    complement(A)      = -phi_A
    offset(A, d)       = phi_A - d          (d > 0 grows A)

`min`/`max` of exact signed-distance fields keep the *sign* — and therefore the
represented set — exact; the distance property degrades only near concave and
convex joins, which is what the narrow-band reinitialisation of the commit gate
(plan §4.2/§4.5, milestone M1) is there to repair.
"""

from __future__ import annotations

import numpy as np

from nanofab_v3.model.grid import PHI_DTYPE


def _as_phi(phi: np.ndarray) -> np.ndarray:
    """Coerce to the storage dtype without copying when it already matches."""
    return np.asarray(phi, dtype=PHI_DTYPE)


def _check_same_shape(phis: tuple[np.ndarray, ...]) -> None:
    shapes = {p.shape for p in phis}
    if len(shapes) > 1:
        raise ValueError(f"set operations need fields of one shape, got {sorted(shapes)}")


def union(*phis: np.ndarray) -> np.ndarray:
    """Signed-distance field of the union of the given regions (`min`)."""
    if not phis:
        raise ValueError("union needs at least one field")
    fields = tuple(_as_phi(p) for p in phis)
    _check_same_shape(fields)
    if len(fields) == 1:
        return fields[0].copy()
    return np.minimum.reduce(list(fields))


def intersection(*phis: np.ndarray) -> np.ndarray:
    """Signed-distance field of the intersection of the given regions (`max`)."""
    if not phis:
        raise ValueError("intersection needs at least one field")
    fields = tuple(_as_phi(p) for p in phis)
    _check_same_shape(fields)
    if len(fields) == 1:
        return fields[0].copy()
    return np.maximum.reduce(list(fields))


def difference(phi_a: np.ndarray, phi_b: np.ndarray) -> np.ndarray:
    """Signed-distance field of `A` minus `B` (`max(phi_A, -phi_B)`)."""
    a, b = _as_phi(phi_a), _as_phi(phi_b)
    _check_same_shape((a, b))
    return np.maximum(a, -b)


def complement(phi: np.ndarray) -> np.ndarray:
    """Signed-distance field of everything outside the region (`-phi`)."""
    return -_as_phi(phi)


def offset(phi: np.ndarray, distance: float) -> np.ndarray:
    """Grow (`distance > 0`) or shrink the region by `distance` nm.

    Exact for a true signed-distance field, and the isotropic fast path of
    plan §4.2 (ALD, simple wet etch) — one array operation, no front tracking.
    """
    return _as_phi(phi) - PHI_DTYPE(distance)
