# Handoff: milestone M3 (lithography, capabilities, predicates, S1–S4)

- Written 2026-08-25, at the end of M2
- Specification: `docs/plans/v2-structure-model.md` §5–§7, with the corrections
  in §17 (M0/M1) and §18 (M2); decisions in ADR-0002…0004; vocabulary in
  `CONTEXT.md`
- **DoD (plan §14)**: materials/fields/capabilities, the resist set, dissolution
  with reachability, lift-off, predicates. **The S1–S4 acceptance tests green** —
  which is the definition of done for the whole structure model, not just for M3.

Read `memory.md` from 2026-08-24 onward first; this file only covers what M3
needs that the plan does not already say.

## 1. What you are building on

`nanofab_v3` is M0 + M1 + M2 complete: **160 tests green**, `python -m compileall
nanofab_v3 tests` clean. Validation is both, per `AGENTS.md` §4.

```
nanofab_v3/
  model/     Grid, Structure, FieldKey/FieldSpec, Occurrence/Lineage, ValidationReport
  kernel/    csg, constructors, contours, measures, stencil, motion, reinit,
             occurrences, gate, invariants, flux
  materials/ MaterialType, MaterialId          (thin; this is your milestone)
  processes/ runtime/ io/                      (empty placeholders — processes/ is yours)
```

The kernel is N-D generic apart from two **named** 2D-only seams, `contours` and
`flux`, which both say so and raise on a 3D grid. Do not add a third by accident:
if a predicate needs a 2D assumption, say so the same way.

## 2. The seams M3 plugs into

```python
gate.commit(structure, *, parent, swept, field_specs, policy, tolerances)
    -> CommitOutcome(structure, report, lineage)
```

The gate already does five of plan §4.5's six steps. **Capability updates are the
sixth and they are yours** — everything else (reinit, field scoping, invariants,
balance, lineage) runs today. `field_specs` is the seam the scoping rule reads:
pass your `FieldSpec`s for `dose` / `exposed` and the gate resets them wherever
their material appeared or vanished, which is the mechanism that stops dose from
a first lithography leaking into resist spun later.

```python
occurrences.label_region(grid, mask) -> (labels, count)
```

This is plan §4.4's whole toolbox. **Reachability** is `label_region` on
`~structure.solid_mask` and then "which component touches the top row";
**support** is the same on `solid_mask` and "which touches the bottom". Both are
already exercised: `tests/test_mechanisms.py::_empty_components` is reachability
in miniature, and it is what the T-profile ALD test asserts against.

```python
flux.FluxModel2D(...).on_structure(structure, release=None) -> FluxOutcome
motion.advect_front(structure, rates, duration, *, deposit_material, flux=model)
```

`flux` accepts either a static array or the model itself, which it re-evaluates
every `motion._FLUX_REFRESH` sub-steps. The technique factories —
`evaporation`, `ion_beam_etch`, `reactive_ion_etch`, `sputter_deposition` — are
already the didactic set of plan §6; a process wrapper's job is to turn typed
parameters into one of these plus a `SurfaceRates`, not to add physics.

`FluxOutcome.redeposited` is a *deposition* flux in the same units as `arrival`,
so a process that redeposits runs a second `advect_front` with it. Its `release`
argument is where material knowledge enters a geometry-only module: pass each
material's etch rate relative to the fastest, or a hard mask will redeposit
material it is not losing.

## 3. The one design decision M3 has to make first

**Where does reachability gate a process — in the rate field, or in the region?**

Plan §4.4 says "a wet process only acts on material cells adjacent to reachable
empty space", and §6 marks development, wet etch, strip and lift-off as
reachability-gated. Two shapes:

- **(a) As a flux-like multiplier.** Build a per-cell mask (1 where the front is
  reachable, 0 elsewhere) and hand it to `advect_front(flux=...)`. It is the
  seam that already exists, it composes with the real flux, and the front simply
  stalls where the solvent cannot get. It must be *rebuilt* as the front moves —
  dissolving resist opens new paths — so it wants the same treatment
  `FluxModel2D` gets, i.e. a small object with `max_arrival` and `on_front`.
- **(b) As a region operation.** Compute the reachable material, remove it in one
  set operation, done. Right for the *ideal* processes (ideal development removes
  `resist ∧ exposed` where reachable), wrong for the rate-driven ones.

**Recommendation: both, and say which is which.** The ideal tier is (b) — one
`csg` operation, exact, no sub-stepping — and the physical tier is (a). That
split is already the plan's own (§3.3: "ideal development consumes `exposed`;
physical development consumes `dose`"), so the two implementations are two
processes at different fidelity, exactly as §5.4 wants, and not a fork in the
kernel.

Second decision, smaller: **S3 is the test of whether you got this right.** ALD
seals the resist, the solvent never reaches it, nothing lifts. Today
`tests/test_mechanisms.py::test_the_sealed_void_keeps_shrinking_and_finally_disappears`
asserts the *opposite* — geometric deposition keeps growing inside a sealed
cavity — and says in its docstring that this is the gap M3 fills. When you gate
ALD on reachability, that test has to be rewritten, not deleted: the sealed void
must stop shrinking. It is the smallest possible S3.

## 4. Traps M2 hit that will bite M3 in the same places

All are written up in plan §18; the short version, plus the M1 traps that still
apply (§17, and the M2 handoff's list — every one of those was hit again).

1. **A correct set operation can be a useless field.** Third milestone running.
   M2's version: a directional deposition's shell formula is exactly zero along
   every shadowed stretch of the old surface — a zero level with no interior, and
   every sub-cell measure reads it as half full (§18.7). When a measurement is
   off by "about half a cell times the length of something", look for a zero
   level that should not exist.
2. **Ordinary geometry breaks invariants that were tuned on smooth scenes.** The
   band gradient check failed *every* film thinner than 8 nm and would have
   failed every masked scene, both for reasons that are arithmetic rather than
   numerical (§18.6). Before tightening a tolerance, work out what the shape
   itself forces the number to be.
3. **Never read geometry off `structure.solid_phi`** where two materials touch —
   use `motion.union_front`. M2 hit this in the visibility occupancy exactly as
   the M1 handoff predicted. M3's connectivity queries are the next place: use
   `solid_mask` (which is already `<= 0` for this reason) and never a strict
   `phi < 0` on the union.
4. **An extension is only valid near the front.** M2's flux collar is 12 cells
   and cells beyond it are frozen (§18.5). A reachability mask has the same
   property and the same failure mode if it is computed once and reused.
5. **Two boxes that share a face leave a zero-valued seam** which `solid_mask`
   reads as solid. Building a re-entrant profile out of abutting primitives walls
   the cavity off from its own mouth before anything is deposited — see the
   `t_profile` fixture, which builds the void as one union of *overlapping*
   boxes for exactly this reason. Every S1/S3 scene has this shape.

## 5. Budget: what you are adding to

Measured at the reference grid (540×1200 at 1 nm, 0.65 M cells) — plan §18.8 has
the full table:

| | |
|---|---|
| complete isotropic step, 4 nm | 0.53 s |
| complete directional step, 4 nm (evaporation / IBE) | 0.57 / 0.60 s |
| directional deposition, 4 nm (sputter cos¹) | 1.26 s |
| heavy 60 nm directional etch | 5.73 s |
| commit gate alone | 0.19 s |
| one flux rebuild | 25–152 ms |
| `label_region` | ~3 ms |

Connectivity is nearly free, so a reachability gate rebuilt every few sub-steps
costs less than the flux does. What still dominates a heavy step is the upwind
stencil over the whole domain — §17.7 said so, §18.8 confirmed it with the flux
in place, and a true narrow-band solver remains the structural fix that is
deliberately not built. If S1–S4 run in acceptable time, leave it alone.

## 6. Suggested order

1. **`MaterialType` for real** (plan §3.4). It is the thinnest module in the
   package and everything else needs it: per-process-class rates and yields,
   `develop_rate(dose)`, dissolve models, display colour. `SurfaceRates` and
   `flux.AngularYield` are the shapes it has to produce.
2. **Capabilities** (§5.3) and the `ProcessStep` protocol (§5.1), then the
   registry (§5.4). Gate on capabilities in the engine, and add the capability
   update to `gate.commit` — that closes plan §4.5 completely.
3. **Predicates** (§7) before the processes that need them, because reachability
   and support are predicates *and* kernel steps, and writing them once is the
   whole point. Start with reachability, support, enclosed voids, undercut ratio,
   step coverage.
4. **The resist set**: spin-coat, ideal exposure, ideal development. Then S1
   (naive lift-off) — which needs evaporation (done), dissolution
   (reachability-gated) and unsupported-component removal.
5. **S2** is nearly free: `tests/test_flux.py::test_a_directional_etch_holds_the_mask_edge`
   already measures the IBE/RIE undercut contrast, so S2 is that plus a predicate
   and a wet-etch process.
6. **S3** (ALD-broken lift-off) — see §3 above; it is the reachability gate
   proving itself.
7. **S4** (sputter fences) — `sputter_deposition(mobility_length=...)` already
   puts partial coverage on a sidewall; the fences are what survives support
   filtering after the resist goes.

## 7. Conventions that are not optional

- `memory.md` gets an entry per `AGENTS.md` §5 (date, what, why, how validated).
  M0/M1/M2's entries are the template; the *decisions taken where the plan left
  detail open* section is the part that earns its keep later.
- Focused commits, `feat:` / `test:` / `docs:` / `fix:`.
- v1 (`cross_section_general_prototype.py`) stays untouched **until S1–S4 pass**,
  which is this milestone — after that it becomes a `ui_backups/` snapshot per
  plan §14 and `AGENTS.md` §7. That is a step to take deliberately and to ask
  about, not a side effect of the tests going green.
- If the plan turns out to be wrong again, amend it the way §17 and §18 do: leave
  the agreed text, add the correction with the measurement that showed it, and
  point at it from the affected line.
