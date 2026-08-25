"""Process steps: `Structure -> Structure (+ outputs)` functions (plan §5, §6).

Empty in M0 by design. A `ProcessStep` declares a parameter schema, the
capabilities it `requires` and `provides` (plan §5.3), and runs as a pure
function of (input `Structure`, validated params, resolved local parameters,
seeded RNG) — the determinism invariant of ADR-0004.

Physics lives once in `nanofab_v3.kernel`; the modules here are thin wrappers
that compose kernel primitives, which is what lets several processes model the
same technique at different fidelity. The didactic set (plan §6) is milestone M3;
it needs the motion kernel (M1) and the flux solver (M2) first.
"""

from __future__ import annotations

__all__: list[str] = []
