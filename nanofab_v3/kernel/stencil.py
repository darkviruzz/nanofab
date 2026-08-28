"""Finite-difference stencils shared by front motion and reinitialisation.

Both solve a Hamilton-Jacobi equation whose Hamiltonian is `|grad(phi)|`, and
both need the same one-sided differences and the same Godunov upwind norm — so
the discretisation lives here once, N-D generic, instead of twice per axis pair.

Boundary condition: the field is continued **linearly** across a domain face —
the difference at the edge repeats its inward neighbour. A zero-gradient edge
would report `|grad(phi)| < 1` for any front not parallel to that face and make
the reinitialisation invent a correction there; linear continuation keeps the
distance property intact and is the honest form of plan §3.1's "solid continues"
at the bottom face. Whether a front should have reached a face at all is the
commit gate's headroom guard, not the stencil's business.
"""

from __future__ import annotations

import numpy as np


def one_sided_differences(phi: np.ndarray, spacing: float) -> list[tuple[np.ndarray, np.ndarray]]:
    """Per axis, the backward and forward difference quotients of `phi`.

    `backward[i] = (phi[i] - phi[i-1]) / spacing`,
    `forward[i] = (phi[i+1] - phi[i]) / spacing`, both zero at the closed edge.
    """
    result: list[tuple[np.ndarray, np.ndarray]] = []
    scale = phi.dtype.type(1.0) / phi.dtype.type(spacing)
    for axis in range(phi.ndim):
        if phi.shape[axis] < 2:
            flat = np.zeros_like(phi)
            result.append((flat, flat))
            continue
        lower = _along(axis, phi.ndim, slice(None, -1))
        upper = _along(axis, phi.ndim, slice(1, None))
        difference = (phi[upper] - phi[lower]) * scale
        # Written into preallocated arrays rather than concatenated: this is the
        # innermost operation of the whole solver, and every temporary here is a
        # full copy of the domain.
        backward = np.empty_like(phi)
        forward = np.empty_like(phi)
        backward[upper] = difference
        forward[lower] = difference
        backward[_along(axis, phi.ndim, slice(0, 1))] = difference[
            _along(axis, phi.ndim, slice(0, 1))
        ]
        forward[_along(axis, phi.ndim, slice(-1, None))] = difference[
            _along(axis, phi.ndim, slice(-1, None))
        ]
        result.append((backward, forward))
    return result


def _along(axis: int, ndim: int, span: slice) -> tuple[slice, ...]:
    """Index one axis with `span` and every other axis in full."""
    return tuple(span if a == axis else slice(None) for a in range(ndim))


def godunov_norm(phi: np.ndarray, spacing: float, moving_out: np.ndarray | bool) -> np.ndarray:
    """Upwind `|grad(phi)|` for a front moving along `+grad(phi)` where `moving_out`.

    The Godunov flux for `H(grad phi) = |grad phi|`: per axis the upwind side is
    the one information comes from, so a front never reads the values it is about
    to overwrite. Exact for a planar field (both differences equal the slope).
    """
    outward = np.asarray(moving_out)
    # A front that moves the same way everywhere — an etch with no negative rate,
    # a deposition with no positive one — needs only its own upwind side. That is
    # the common case, and computing both sides for it would double the cost of
    # the single most-called function in the solver.
    everywhere_out = bool(np.all(outward))
    nowhere_out = not bool(np.any(outward))

    total = np.zeros_like(phi)
    for backward, forward in one_sided_differences(phi, spacing):
        if not nowhere_out:
            out_term = np.maximum(np.maximum(backward, 0.0) ** 2, np.minimum(forward, 0.0) ** 2)
            if everywhere_out:
                total += out_term
                continue
        in_term = np.maximum(np.minimum(backward, 0.0) ** 2, np.maximum(forward, 0.0) ** 2)
        total += in_term if nowhere_out else np.where(outward, out_term, in_term)
    return np.sqrt(total)


def one_sided_gradient_magnitude(phi: np.ndarray, spacing: float) -> np.ndarray:
    """`|grad(phi)|` from the steeper one-sided difference per axis.

    Combining the per-axis magnitudes as a Euclidean norm is what keeps this
    isotropic: a front at 45 degrees has one-sided differences of `1/sqrt(2)` per
    axis and must still measure 1, which a plain max over axes would report as
    `0.707`. It is the denominator of the Russo-Smereka sub-cell distance
    `phi / |grad(phi)|`, so getting it wrong tilts every diagonal interface.

    One-sided rather than central differences: at an interface cell the field has
    a kink, and the steeper side is the safe estimate.
    """
    total = np.zeros_like(phi)
    for backward, forward in one_sided_differences(phi, spacing):
        total = total + np.maximum(np.abs(backward), np.abs(forward)) ** 2
    return np.sqrt(total)


def has_opposite_sign_neighbour(phi: np.ndarray) -> np.ndarray:
    """Cells with a face neighbour on the other side of the zero level.

    A cell sitting exactly on the zero level counts as **inside**. That is not a
    detail: where two materials touch, the union field `min_m phi[m]` is exactly
    zero along their shared interface, and reading `phi < 0` would report that
    buried seam as a front. With `phi <= 0` the seam's neighbours are inside on
    both sides, so only the real solid/empty interface is flagged — which is what
    lets the reinitialisation relax such a seam away instead of preserving it.
    """
    negative = phi <= 0.0
    flagged = np.zeros(phi.shape, dtype=bool)
    for axis in range(phi.ndim):
        differs = np.diff(negative, axis=axis)
        edge = np.zeros_like(np.take(flagged, [0], axis=axis))
        flagged |= np.concatenate([edge, differs], axis=axis)
        flagged |= np.concatenate([differs, edge], axis=axis)
    return flagged
