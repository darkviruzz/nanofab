# ADR-0002: Per-material signed-distance fields on one shared grid

- Status: accepted (design interview 2026-08-24/25) — implementation pending
- Detail: `docs/plans/v2-structure-model.md` §3–4

The v2 structure model represents sample geometry as one signed-distance field per
material (`phi_m < 0` inside, float32, dense) on a single shared `Grid`, and this is
the **only** stored geometry. Analytic primitives (planes, boxes, gratings) exist
solely as constructors that sample onto the grid once; they are never consulted
afterwards. Set operations are pointwise min/max; only the exposed union front is
ever advected, buried materials are maintained by clipping — so process-created
surfaces are first-class (v1's iteration stall, ADR-0001 F2, is impossible) and
boolean/polygonization artifact accumulation (ADR-0001 F3/F4) has no mechanism to
occur. Volumetric state (dose, damage) lives as fields on the same grid.

Considered and rejected:
- **B-Rep with a real boolean kernel** — v1's path; topology change (pinch-off, the
  cause of the ALD-broken lift-off) is manual bookkeeping, fields need a second
  data model, and the measured v1 failures were structural, not implementation bugs.
- **VOF (cell fill fractions)** — exact mass, but poor interface normals; both
  directional yield `f(θ)` and crystallographic anisotropy need accurate normals,
  which `∇phi` of an SDF provides.
- **Single φ + material-index map** — halves memory, but buried interfaces exist
  only at cell resolution; lift-off re-exposes buried interfaces, which would come
  back staircase-quantised. Per-material fields keep them sub-cell sharp.

Accepted costs: grid resolution becomes a visible model parameter (~½-cell corner
rounding); reinitialisation introduces a small, *measured* interface drift, bounded
by the commit gate's balance check.
