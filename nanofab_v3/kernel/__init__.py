"""The kernel: pure functions on `Structure` (plan §4).

No Qt anywhere in here — v1's central defect was `QPainterPath` acting as the
physics engine (ADR-0001), and rendering is a consumer of the kernel (§10), never
the other way round. Kernel code is N-D generic; the only deliberately 2D-only
seam in M0 is `contours` (marching squares), which says so and checks it.

M0 ships:

- `csg` — set operations as pointwise min/max,
- `constructors` — analytic primitives sampled onto the `Grid`, once,
- `contours` — marching squares for rendering and debug,
- `invariants` — the cheap field checks the commit gate (M1) will reuse.

Motion (offset fast path, upwind advection, reinitialisation, the commit gate)
arrives in M1, flux and visibility in M2.
"""

from __future__ import annotations

__all__ = ["constructors", "contours", "csg", "invariants"]
