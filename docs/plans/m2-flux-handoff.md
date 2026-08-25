# Handoff: milestone M2 (flux and visibility)

- Written 2026-08-25, at the end of M1
- Specification: `docs/plans/v2-structure-model.md` §4.3, with the corrections in
  §17; decisions in ADR-0002…0004; vocabulary in `CONTEXT.md`
- **DoD (plan §14)**: `FluxModel2D` reverse marching, evaporation / IBE / RIE /
  sputter, redeposition bounce. Shadow-wedge and mechanism tests green, budget
  verified.

Read `memory.md` from 2026-08-24 onward first; this file only covers what M2
needs that is not already in the plan.

## 1. What you are building on

`nanofab_v3` is M0 + M1 complete: 113 tests green, `python -m compileall
nanofab_v3 tests` clean. Validation is both, per `AGENTS.md` §4.

```
nanofab_v3/
  model/     Grid, Structure, FieldKey/FieldSpec, Occurrence/Lineage, ValidationReport
  kernel/    csg, constructors, contours, measures, stencil, motion, reinit,
             occurrences, gate, invariants
  materials/ MaterialType, MaterialId          (thin; grows in M3)
  processes/ runtime/ io/                      (empty placeholders, M3/M4)
```

The kernel is N-D generic. The only 2D-only module today is `contours`, which
says so and raises on a 3D grid. **`FluxModel2D` is the second**, by decision
(Q7) — name the seam the same way and check it the same way.

## 2. The seams M2 plugs into, and their exact shape

```python
motion.advect_front(structure, rates, duration, *, deposit_material=None,
                    flux=None, cfl=0.5, policy=ReinitPolicy()) -> MotionOutcome
```

`flux` is already wired: a **per-cell float32 array on the grid**, multiplied
onto the material rate to give the speed field `F = sign · rate(owner) · flux`.
It also enters the CFL bound (`rates.bound × max|flux|`) and the balance check's
front integral, so nothing else needs changing for a flux-driven process to be
sub-stepped and validated correctly. That is the whole integration point.

Also available:

- `measures.surface_normals(grid, phi) -> (ndim, *shape)` — outward unit normals
  from `∇phi`, zero where the gradient vanishes. This is the `θ_incidence` input.
- `measures.front_integral(grid, phi, values, epsilon)` — band-restricted, so it
  costs the front and not the domain.
- `contours.marching_squares(grid, phi, level)` — polylines in nm, in grid-axis
  order, oriented so the material lies to the left. If you want the plan's
  "front samples", this is where they come from.
- `motion.union_front(structure, policy)` — the union field with buried seams
  repaired. **Use this, never `structure.solid_phi`, as the occupancy or
  visibility input** (see §17.1: `min_m phi[m]` is zero along every shared
  interface, so a raw occupancy read would see walls that are not there).
- `occurrences.label_region(grid, mask)` — connected components, for enclosed
  voids and, in M3, reachability.

## 3. The one design decision M2 has to make first

Plan §4.3 defines `FluxModel2D` as returning **flux per front sample** (points +
normals). `advect_front` consumes a **per-cell array**. Those do not meet on
their own, and how you bridge them determines the module's shape:

- **(a) Per-cell throughout.** Evaluate visibility at the front cells directly
  (cells where `|phi_solid| < spacing`), write flux into an array, extend it off
  the front the way `motion._FrontMaterial` extends ownership. No sample
  abstraction at all. Simplest, and it reuses machinery that already exists.
- **(b) Samples, then scatter.** Build samples from `marching_squares` (which
  gives sub-cell positions and ordering, so refinement near shadow boundaries is
  natural — the plan explicitly wants that), compute flux per sample, then
  scatter back to the front cells and extend.

The plan's refinement argument ("refinement concentrates samples near
transitions") favours (b); the existing machinery favours (a). **Recommendation:
start with (a) to get a shadow wedge measurable end to end, then add sample-level
refinement inside the same interface if the wedge position is not accurate
enough.** Whichever you pick, keep it behind the `FluxModel2D` interface so the
choice stays reversible — the flux array is the contract with the solver, not
the internals.

Second decision, smaller: `F = sign · rate(material) · yield(θ) · flux(x)` has
three factors and the solver currently has two. Either fold `yield(θ)` into the
returned flux array (it is a per-cell quantity like the rest) or add it to
`SurfaceRates`. Folding it in keeps the solver unchanged and keeps
angle-dependence where the angles are known; that is the recommendation, with the
name saying so (`flux` becomes "arrival per unit front", not "raw flux").

## 4. Traps M1 hit that will bite M2 in the same places

These cost most of M1's time. All are written up in plan §17; the short version:

1. **A correct set operation can be a useless field.** Signs decide regions;
   values decide every distance and integral read off them afterwards. When
   something is off by a factor, ask which of the two you actually broke.
2. **Never read geometry off `structure.solid_phi` directly** where two materials
   touch — use `union_front`. This will hit the visibility occupancy grid.
3. **Nothing about the front can be read from the material fields in a shadowed
   void.** M1's undercut ran 35 % too far this way. Flux has the same shape of
   problem: what a void cell "sees" is not what its field values say.
4. **Anything quantised per cell is a resolution artifact, and it multiplies.**
   The A→B rate switch is a cell wide, which with a rate ratio of 5 is a few nm.
   A shadow boundary is the same: expect the wedge position to be accurate to
   about a cell, and set the test tolerance from the geometry, not from hope.
5. **Uniform speed sign is a fast path.** `stencil.godunov_norm` computes one
   upwind side when the front moves the same way everywhere. Keep flux
   non-negative so directional etching stays uniformly signed, or the solver
   silently doubles its cost.

## 5. Budget: what you are adding to

Measured at the plan's reference grid (540×1200 at 1 nm, 0.65 M cells) — the
numbers in plan §4.2 are the stencil alone, these are complete steps:

| | |
|---|---|
| complete advection sub-step | ~50 ms |
| typical step (4 nm = 8 sub-steps) | 0.74 s |
| heavy step (60 nm = 120 sub-steps) | 6.0 s |
| commit gate, 2 materials | 0.31 s |
| distance transform (the ownership extension) | 75 ms |

So §4.3's estimate of 10–100 ms per flux rebuild, every 5–10 sub-steps, adds
2–20 % to a step rather than dominating it. `motion._OWNER_REFRESH = 5` is the
existing precedent for such a cadence constant; consider sharing one refresh
point for both maps, since both answer "where are the walls".

If the budget does not hold, plan §15 says the fallback is K and the visibility
grid coarseness, **not the model**. The other lever, untouched so far, is that
the whole solver still evaluates the upwind stencil over the entire domain; a
true narrow-band solver is the structural fix and is deliberately not built.

## 6. Suggested order

1. **The mechanism test that needs no flux at all**, as a warm-up that also
   verifies the handoff: plan §13.2's T-profile ALD. It runs today —
   `offset_solid(s, t, deposit_material=...)` plus `occurrences.label_region` on
   `~solid_mask`. Measured while writing this: over a 20 nm opening under an
   overhang, `t = 5` leaves the cavity open (1 empty component), `t = 15` seals
   an enclosed void (2 components). At `t = 25` the void has closed *completely*
   — because geometric deposition keeps growing inside a sealed cavity. That is
   correct for M1 and is exactly the gap M3's reachability gate fills; it is also
   the S3 mechanism in miniature. Worth landing as a test now, with that
   behaviour written down rather than discovered later.
2. `FluxModel2D` interface + a δ(θ) evaporation source with reverse marching,
   and the **shadow wedge** test against the analytic position for a rectangular
   mask at angle θ. This is the smallest thing that proves visibility works.
3. Angular distributions: narrow lobe (RIE/IBE), cosⁿ (sputter), plus RIE's
   isotropic chemical fraction as a flux floor.
4. Angle-dependent yield, then the redeposition bounce.
5. Budget verification at the reference grid; record it in `memory.md` the way
   M1's numbers are recorded.

## 7. Conventions that are not optional

- `memory.md` gets an entry per `AGENTS.md` §5 (date, what, why, how validated).
  M0 and M1's entries are the template; the *decisions taken where the plan left
  detail open* section is the part that earns its keep later.
- Focused commits, `feat:` / `test:` / `docs:`.
- v1 (`cross_section_general_prototype.py`) stays untouched until the S1–S4
  acceptance tests pass in M3; then it becomes a `ui_backups/` snapshot.
- If the plan turns out to be wrong again, amend it the way §17 does: leave the
  agreed text, add the correction with the measurement that showed it, and point
  at it from the affected line.
