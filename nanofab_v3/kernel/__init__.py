"""The kernel: pure functions on `Structure` (plan §4).

No Qt anywhere in here — v1's central defect was `QPainterPath` acting as the
physics engine (ADR-0001), and rendering is a consumer of the kernel (§10), never
the other way round. Kernel code is N-D generic; the only deliberately 2D-only
seam in M0 is `contours` (marching squares), which says so and checks it.

Geometry and state (M0):

- `csg` — set operations as pointwise min/max,
- `constructors` — analytic primitives sampled onto the `Grid`, once,
- `contours` — marching squares for rendering and debug,
- `invariants` — the cheap field checks the commit gate reuses,
- `measures` — enclosed measure and front integrals, sub-cell accurate.

Motion and its bookkeeping (M1):

- `stencil` — the finite-difference stencils motion and reinit share,
- `motion` — the isotropic fast path and CFL-sub-stepped upwind advection,
- `reinit` — narrow-band, interface-preserving renormalisation,
- `occurrences` — connected components and lineage by overlap matching,
- `gate` — the commit gate every chain step ends in.

Flux and visibility (M2):

- `flux` — `FluxModel2D`: reverse-marching visibility, angular distributions,
  angle-dependent yield, surface mobility and the redeposition bounce. The
  **second** 2D-only seam next to `contours`, by decision (plan Q7).
"""

from __future__ import annotations

__all__ = [
    "constructors",
    "contours",
    "csg",
    "flux",
    "gate",
    "invariants",
    "measures",
    "motion",
    "occurrences",
    "reinit",
    "stencil",
]
