"""S1-S5: the acceptance scenarios (plan §1, §13.3) — the definition of done.

Plan §14 makes the first four the definition of done for milestone M3, and
plan §1 makes them the definition of "works" for the whole structure model. Each
one is a **recipe**, run through the registry and the commit gate exactly as the
application would run it, and asserted through the predicates of §7 rather than
by poking at arrays — because "the metal pattern is 100 nm wide" and "the resist
cannot be reached" are the sentences the model is supposed to be able to say.

What each scenario has to *emerge* rather than be told:

- **S1** — the metal on the resist and the metal in the window are separate
  pieces because a delta source cannot coat a vertical wall, and the first is
  carried away because nothing holds it up.
- **S2** — an isotropic front is a circle centred on the mask edge, so it
  undercuts by as much as it etches down; a directional one does not.
- **S3** — the same stack as S1 with a conformal film over it: the solvent never
  reaches the resist, so nothing lifts. **No step is told that the lift-off
  should fail.**
- **S4** — a broad lobe reaches down a sidewall a point source cannot see, and
  what it leaves there stays standing after the resist goes, because it is
  attached to the film on the substrate.
- **S5** (M5, plan §6 rows 16-17) — a particle that was buried by a film before
  the clean is **unreachable**, so the clean leaves it and the defect stays.
  Nothing is told to leave it: `reachable_occurrences` answers, exactly as it
  does for S3's sealed resist.

Every scenario also runs its **control**: the same recipe with the one change
that makes the mechanism go away. A test that only asserts the interesting
outcome cannot tell a working model from a broken one that happens to agree.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from nanofab_v3 import Structure
from nanofab_v3.kernel import occurrences, predicates
from nanofab_v3.materials import (
    ALUMINA,
    METAL,
    OXIDE,
    PARTICLE,
    RESIST,
    SILICON,
    UNDERLAYER,
    didactic_library,
)
from nanofab_v3 import acceptance
from nanofab_v3.processes import builtin_registry, contamination, run_chain
from nanofab_v3.processes.substrate import cross_section_grid

SURFACE = acceptance.SURFACE
CENTRE = acceptance.CENTRE
WINDOW = acceptance.WINDOW


@pytest.fixture(scope="module")
def registry():
    return builtin_registry()


@pytest.fixture(scope="module")
def library():
    return didactic_library()


# -- shared measurements ------------------------------------------------------


def _pattern(structure: Structure, material=METAL) -> tuple[int, np.ndarray]:
    """`(occurrence count, cell mask)` of one material — the derived stack view."""
    cells = structure.inside(material)
    _, count = occurrences.label_region(structure.grid, cells)
    return count, cells


def _width_at(structure: Structure, row: int, material=METAL) -> float:
    """Lateral extent of a material in one row, in nm."""
    return float(np.count_nonzero(structure.inside(material)[row])) * structure.grid.spacing


def _profile(structure: Structure, material=METAL) -> np.ndarray:
    """Topmost occupied row per column where the material is present."""
    cells = structure.inside(material)
    columns = np.flatnonzero(np.any(cells, axis=0))
    return np.array([int(np.flatnonzero(cells[:, c]).max()) for c in columns])


def _top_profile(structure: Structure) -> np.ndarray:
    """Height of the topmost solid cell per column, in nm — the sample's skyline."""
    rows = contamination.surface_rows(structure)
    return rows * structure.grid.spacing + structure.grid.origin[0]


# -- S1: naive lift-off -------------------------------------------------------


def _resolve(registry, steps):
    """`(step_id, params)` from `nanofab_v3.acceptance` -> what `run_chain` takes.

    The recipes live in the shipped module so the packaged exe can run them
    (plan §14's DoD) and this file measures the *same* ones — one definition of
    what S1 is, rather than two that drift.
    """
    return [(registry[step_id], dict(params)) for step_id, params in steps]


def _lift_off_recipe(registry, *, metal_thickness=20.0, resist_thickness=90.0):
    """substrate -> resist -> ideal exposure -> ideal development -> evaporation."""
    return _resolve(
        registry,
        acceptance.lift_off_steps(
            metal_thickness=metal_thickness, resist_thickness=resist_thickness
        ),
    )


@pytest.fixture(scope="module")
def s1(registry, library):
    """The whole of S1, run once: the naive lift-off, through to the pattern."""
    grid = cross_section_grid(width=300.0, thickness=SURFACE, headroom=200.0)
    recipe = _lift_off_recipe(registry) + [
        (registry["strip.lift_off"], {"material": RESIST})
    ]
    return run_chain(recipe, Structure(grid), library=library)


def test_s1_every_step_passes_the_commit_gate(s1) -> None:
    """The invariants hold through a six-step chain, not just at the end.

    Plan §4.5's report is stored per revision precisely so this is checkable; a
    scenario that only looked at the final geometry could be built on six steps
    of accumulated nonsense.
    """
    assert all(outcome.ok for outcome in s1)
    for outcome in s1:
        if outcome.report.balance is not None:
            assert outcome.report.balance.error < 0.05


def test_s1_the_evaporated_metal_is_three_pieces_before_anything_dissolves(s1) -> None:
    """A vertical wall at normal incidence receives nothing (`CONTEXT.md`, *Shadowing*).

    Two caps on the mask and one pattern in the window — and the wall between
    them bare, which is both why the pieces are separate and why the solvent can
    get to the resist at all.
    """
    deposited = s1[-2].structure

    count, _ = _pattern(deposited)
    assert count == 3
    assert predicates.is_reachable(deposited, RESIST)
    assert not predicates.unsupported(deposited).any()  # nothing floats yet


def test_s1_leaves_one_clean_metal_pattern_of_the_designed_width(s1) -> None:
    """Plan §13.3: "S1 pattern width == design ± tol".

    The tolerance is the grid's, not hope's: an ideal exposure is a cell-quantised
    field (plan §3.3), so the developed window's edges are good to half a cell
    each and the pattern is good to one.
    """
    final = s1[-1].structure

    count, _ = _pattern(final)
    assert count == 1
    assert final.materials == (SILICON, METAL)
    assert _width_at(final, int(SURFACE) + 1) == pytest.approx(WINDOW, abs=2.0)
    assert predicates.film_thickness(final, METAL) == pytest.approx(20.0, abs=2.0)


def test_s1_the_pattern_sits_where_the_mask_put_it(s1) -> None:
    """A pattern of the right width in the wrong place is not a pattern."""
    final = s1[-1].structure

    columns = np.flatnonzero(np.any(final.inside(METAL), axis=0)) * final.grid.spacing
    assert 0.5 * (columns.min() + columns.max()) == pytest.approx(CENTRE, abs=1.0)


def test_s1_the_resist_and_its_dose_field_are_gone_from_the_revision(s1) -> None:
    """The capability update of plan §4.5's sixth step, at scenario scale."""
    from nanofab_v3.model import capability

    before, after = s1[-2].capabilities, s1[-1].capabilities

    assert capability.of_material(RESIST) in before
    assert capability.of_field(RESIST, "exposed") in before
    assert capability.of_material(RESIST) not in after
    assert capability.of_field(RESIST, "exposed") not in after
    assert capability.of_material(METAL) in after


def test_s1_control_without_a_window_the_solvent_has_no_way_in(registry, library) -> None:
    """The control: skip the lithography, and the lift-off stops working.

    A blanket resist under a blanket metal has no exposed resist anywhere — the
    metal covers its top and the cross-section continues past both lateral faces,
    which the model does not treat as a bath (`predicates.open_faces`). So
    nothing dissolves and nothing lifts.

    That is the same mechanism as S3, reached by *removing* a step instead of
    adding one, and it is what makes S1's result a statement about the window
    rather than about `lift_off` removing resist whenever it is asked to.
    """
    grid = cross_section_grid(width=300.0, thickness=SURFACE, headroom=200.0)

    outcomes = run_chain(
        [
            (registry["substrate.select"], {"material": SILICON, "surface": SURFACE}),
            (registry["resist.spin_coat"], {"material": RESIST, "thickness": 90.0}),
            (registry["deposit.evaporate"], {"material": METAL, "thickness": 20.0}),
            (registry["strip.lift_off"], {"material": RESIST}),
        ],
        Structure(grid),
        library=library,
    )

    assert not predicates.is_reachable(outcomes[-2].structure, RESIST)
    assert outcomes[-1].structure.materials == (SILICON, RESIST, METAL)
    assert any("never reached" in line for line in outcomes[-1].logs)


# -- S2: undercut -------------------------------------------------------------


@pytest.fixture(scope="module")
def s2_masked(registry, library):
    """60 nm of oxide on silicon under a resist mask with an 80 nm window."""
    grid = cross_section_grid(width=300.0, thickness=SURFACE, headroom=220.0)
    outcomes = run_chain(
        _resolve(registry, acceptance.masked_oxide_steps()),
        Structure(grid),
        library=library,
    )
    return outcomes[-1].structure


def test_s2_an_isotropic_wet_etch_undercuts_the_mask_by_what_it_etches_down(
    registry, library, s2_masked
) -> None:
    """Plan §13.3: "S2 undercut ratio".

    An isotropic front is a circle centred on the mask edge, and a circle's
    radius is the same sideways as downwards — so the ratio is 1, and nothing in
    the model knows what an undercut is. 30 s at the oxide's 1 nm/s blanket rate.
    """
    outcomes = run_chain(
        [(registry["etch.wet"], {"duration": 30.0})],
        s2_masked,
        library=library,
    )
    measured = predicates.undercut(outcomes[-1].structure, RESIST)

    assert measured.vertical == pytest.approx(30.0, abs=3.0)
    assert measured.ratio == pytest.approx(1.0, abs=0.25)


def test_s2_an_ion_beam_of_the_same_depth_undercuts_nothing(
    registry, library, s2_masked
) -> None:
    """The contrast that makes the ratio mean something (plan §1, S2).

    The same nominal depth, from a narrow lobe with no chemistry: the walls stand
    where the mask edge is. `scale` brings the oxide's 0.8 nm/s ion-beam rate up
    to the wet etch's 1.0, so the two etches are compared at equal depth rather
    than at equal time.
    """
    outcomes = run_chain(
        [(registry["etch.ibe"], {"duration": 30.0, "scale": 1.25})],
        s2_masked,
        library=library,
    )
    measured = predicates.undercut(outcomes[-1].structure, RESIST)

    assert measured.vertical == pytest.approx(30.0, abs=3.0)
    assert measured.ratio < 0.1


def test_s2_a_chemical_fraction_is_what_puts_the_undercut_back(
    registry, library, s2_masked
) -> None:
    """RIE sits between the two, and the knob that moves it is the chemistry.

    §18's decision that the chemical fraction is an orientation-blind *floor* is
    what this measures: the floor etches sideways, so an RIE profile undercuts a
    little where an ion beam does not.
    """
    ratios = []
    for fraction in (0.0, 0.35):
        outcomes = run_chain(
            [
                (
                    registry["etch.rie"],
                    {"duration": 30.0, "scale": 0.67, "chemical_fraction": fraction},
                )
            ],
            s2_masked,
            library=library,
        )
        ratios.append(predicates.undercut(outcomes[-1].structure, RESIST).ratio)

    assert ratios[0] < 0.1
    assert ratios[1] > 2.0 * max(ratios[0], 0.02)


# -- S3: lift-off broken by ALD ----------------------------------------------


@pytest.fixture(scope="module")
def s3(registry, library):
    """S1's stack, plus a conformal film over it, then the same lift-off."""
    grid = cross_section_grid(width=300.0, thickness=SURFACE, headroom=200.0)
    recipe = _lift_off_recipe(registry) + [
        (registry["deposit.ald"], {"material": ALUMINA, "thickness": 15.0}),
        (registry["strip.lift_off"], {"material": RESIST}),
    ]
    return run_chain(recipe, Structure(grid), library=library)


def test_s3_the_conformal_film_seals_the_only_resist_surface_there_was(s3) -> None:
    """Plan §13.3: "S3 resist-unreachable".

    Before the ALD the solvent reaches the resist through the bare sidewall of
    the window; after it, there is no bare resist anywhere. The query is the same
    one S1 passes — the answer changed because the geometry did.
    """
    before, after = s3[-3].structure, s3[-2].structure

    assert predicates.is_reachable(before, RESIST)
    assert not predicates.is_reachable(after, RESIST)


def test_s3_nothing_lifts_and_the_failure_is_not_special_cased(s3) -> None:
    """Plan §1: "The failure must **emerge** from the model (reachability)".

    The lift-off step is the same object S1 runs and it is handed the same
    parameters. It dissolves what the solvent reaches, which is nothing, and then
    removes what is unsupported, which is also nothing.
    """
    final = s3[-1].structure

    assert RESIST in final.phi
    assert METAL in final.phi
    assert ALUMINA in final.phi
    assert any("never reached" in line for line in s3[-1].logs)


def test_s3_the_film_is_continuous_where_s1s_was_in_three_pieces(s3) -> None:
    """Plan §13.3: "S3 ... and film continuous".

    The conformal film bridges the sidewall the evaporation left bare. That is
    the *mechanism* of the failure and not merely a symptom: with the sidewall
    bridged there is no path to the resist, and with no path there is no lift-off.
    """
    sealed = s3[-2].structure

    _, pieces = occurrences.label_region(sealed.grid, sealed.solid_mask)
    assert pieces == 1
    coverage = predicates.step_coverage(sealed, ALUMINA)
    assert coverage.continuous


def test_s3_control_the_same_stack_without_the_ald_lifts_off_cleanly(s1) -> None:
    """S1 *is* the control for S3: one process added, opposite outcome."""
    assert s1[-1].structure.materials == (SILICON, METAL)


# -- S4: sputter fences -------------------------------------------------------


def _bilayer_recipe(registry, *, mouth=80.0, cavity=120.0, under=50.0, imaging=60.0):
    """A real lift-off stack, from the shipped module — see `_resolve`."""
    return _resolve(
        registry,
        acceptance.bilayer_steps(mouth=mouth, cavity=cavity, under=under, imaging=imaging),
    )


@pytest.fixture(scope="module")
def s4(registry, library):
    """The bilayer stack, a `cos^1` sputter with surface mobility, then lift-off."""
    grid = cross_section_grid(width=300.0, thickness=SURFACE, headroom=230.0)
    recipe = _bilayer_recipe(registry) + [
        (
            registry["deposit.sputter"],
            {"material": METAL, "thickness": 25.0, "exponent": 1.0, "mobility_length": 10.0},
        ),
        (registry["strip.lift_off"], {"material": UNDERLAYER}),
    ]
    return run_chain(recipe, Structure(grid), library=library)


def test_s4_the_bilayer_develops_into_a_re_entrant_profile(s4) -> None:
    """The undercut the fences need: the mouth is narrower than the cavity below."""
    developed = s4[-3].structure

    mouth = _width_at(developed, 120, RESIST)  # a row inside the imaging layer
    walls = np.flatnonzero(~np.any(developed.inside(UNDERLAYER), axis=0))
    assert mouth > 0.0
    assert (walls.max() - walls.min() + 1) > 80.0  # the cavity is wider than the 80 nm mouth


def test_s4_the_sputtered_film_covers_the_sidewall_only_partly(s4) -> None:
    """Plan §1: "partial sidewall coverage (broad lobe + surface mobility)".

    Partial is the whole point, twice over: enough coverage on the cavity wall
    for something to stand there after the resist goes, and a gap for the solvent
    to get through — a film that covered the wall completely would seal the
    underlayer and turn S4 into S3.
    """
    deposited = s4[-2].structure

    coverage = predicates.step_coverage(deposited, METAL)
    assert not coverage.continuous
    assert 0.0 < coverage.ratio < 0.6
    assert predicates.is_reachable(deposited, UNDERLAYER)


def test_s4_leaves_fences_standing_at_the_edges_of_the_pattern(s4) -> None:
    """Plan §13.3: "S4 fence components present".

    What survives is the pattern *plus* raised rims at its edges: the metal that
    landed on the cavity's vertical walls and is still attached to the film on the
    substrate. Support is what keeps it — no thickness threshold and no rule about
    fences anywhere in the model.
    """
    final = s4[-1].structure

    assert final.materials == (SILICON, METAL)
    profile = _profile(final)
    film_top = float(np.median(profile))
    assert profile.max() - film_top >= 10.0  # rims well above the flat film
    edges = np.flatnonzero(profile >= profile.max() - 2)
    assert edges.min() < 0.2 * profile.size  # ... at both edges of the pattern
    assert edges.max() > 0.8 * profile.size


def test_s4_control_an_evaporation_on_the_same_stack_leaves_a_flat_pattern(
    registry, library
) -> None:
    """One process changed, and the fences are gone (plan §1, S1 vs S4).

    A delta source cannot see the cavity walls at all — they are at normal
    incidence to it *and* behind the overhang — so it deposits only through the
    mouth and leaves a flat pattern of the mouth's width. That the same recipe
    gives fences with a broad lobe and none with a point source is the assertion;
    either result on its own would prove nothing.
    """
    grid = cross_section_grid(width=300.0, thickness=SURFACE, headroom=230.0)
    recipe = _bilayer_recipe(registry) + [
        (registry["deposit.evaporate"], {"material": METAL, "thickness": 25.0}),
        (registry["strip.lift_off"], {"material": UNDERLAYER}),
    ]

    outcomes = run_chain(recipe, Structure(grid), library=library)
    final = outcomes[-1].structure

    profile = _profile(final)
    assert final.materials == (SILICON, METAL)
    assert profile.max() - float(np.median(profile)) <= 2.0  # flat, no rims
    assert _width_at(final, int(SURFACE) + 1) == pytest.approx(80.0, abs=4.0)


def test_s4_every_step_passes_the_commit_gate(s4) -> None:
    """Nine steps, two materials developed and one deposited through an overhang."""
    assert all(outcome.ok for outcome in s4)


# -- S5: micromasking — the particle a clean cannot reach ---------------------

def _particle_recipe(registry, *, bury: bool):
    """substrate -> particles -> (a conformal film) -> clean, from the shipped module."""
    return _resolve(registry, acceptance.particle_steps(bury=bury))


@pytest.fixture(scope="module")
def s5(registry, library):
    """The whole of S5, run once: particles, a film over them, and a clean."""
    grid = cross_section_grid(width=300.0, thickness=SURFACE, headroom=200.0)
    return run_chain(
        _particle_recipe(registry, bury=True),
        Structure(grid),
        library=library,
        recipe_id="s5",
    )


@pytest.fixture(scope="module")
def s5_control(registry, library):
    """The control: the same particles, cleaned before anything buries them."""
    grid = cross_section_grid(width=300.0, thickness=SURFACE, headroom=200.0)
    return run_chain(
        _particle_recipe(registry, bury=False),
        Structure(grid),
        library=library,
        recipe_id="s5",
    )


def test_s5_particles_land_on_the_surface_and_not_inside_it(s5) -> None:
    """Handoff §4's trap 2: a particle placed at a random point means nothing.

    Every particle cell is above the substrate surface, and the particles rest on
    it rather than hovering — the whole thing is one connected solid, which is
    what lets a conformal film seal around them.
    """
    seeded = s5[1].structure
    cells = predicates.cells_of(seeded, PARTICLE)

    rows = np.flatnonzero(np.any(cells, axis=1))
    assert rows.min() >= int(SURFACE)  # nothing buried in the substrate
    assert seeded.measure(cells) > 0.0
    # one connected solid: the particles are touching what they landed on
    _, pieces = occurrences.label_region(seeded.grid, seeded.solid_mask)
    assert pieces == 1


def test_s5_the_clean_leaves_every_buried_particle(s5) -> None:
    """The scenario: 0 removed, and `material:particle` survives the clean.

    No step is told that the particles are buried. `clean.particles` asks
    `reachable_occurrences`, gets an empty mask, and removes nothing.
    """
    before, after = s5[-2].structure, s5[-1].structure

    assert PARTICLE in after.phi
    assert "material:particle" in s5[-1].capabilities
    assert s5[-1].measurements["removed"].value == 0.0
    assert s5[-1].measurements["micromasked"].value >= 1.0
    assert after.measure(predicates.cells_of(after, PARTICLE)) == pytest.approx(
        before.measure(predicates.cells_of(before, PARTICLE))
    )
    assert not predicates.is_reachable(before, PARTICLE)


def test_s5_control_an_unburied_particle_is_cleaned_off(s5_control, registry) -> None:
    """One step removed and the mechanism goes away — the same particles, all gone.

    The control matters more here than anywhere else in this file: an assertion
    that a clean left the particles behind is satisfied just as well by a clean
    that does nothing at all.
    """
    seeded, cleaned = s5_control[-2], s5_control[-1]

    assert predicates.is_reachable(seeded.structure, PARTICLE)
    assert PARTICLE not in cleaned.structure.phi
    assert "material:particle" not in cleaned.capabilities
    assert cleaned.measurements["removed"].value >= 1.0
    assert cleaned.measurements["micromasked"].value == 0.0


def test_s5_the_defect_the_particle_caused_stays(s5, registry, library) -> None:
    """"...and the defect it caused stays" — the film is not flat where they are.

    The reference film over a bare substrate is flat to the cell. Over a buried
    particle it bulges, and it still bulges after the clean, because the clean
    could not reach what is holding it up.
    """
    grid = cross_section_grid(width=300.0, thickness=SURFACE, headroom=200.0)
    reference = run_chain(
        [
            (registry["substrate.select"], {"material": SILICON, "surface": SURFACE}),
            (registry["deposit.conformal_offset"], {"material": ALUMINA, "thickness": 10.0}),
        ],
        Structure(grid),
        library=library,
    )[-1].structure

    flat = _top_profile(reference)
    defective = _top_profile(s5[-1].structure)

    assert flat.max() == flat.min()  # a blanket film is flat to the cell
    assert defective.max() - flat.max() >= 5.0  # a bump, well above one cell
    raised = defective > flat.max()
    particles = np.any(predicates.cells_of(s5[-1].structure, PARTICLE), axis=0)
    assert np.all(raised[particles])  # every surviving particle shows through


def test_s5_the_particles_are_a_pure_function_of_the_seed(registry, library) -> None:
    """Plan §5.2, and the first *registered* step that exercises it.

    Two runs of the same recipe at the same position scatter identical particles;
    the same recipe at another wafer position scatters different ones. Without the
    first, ADR-0004's replay materialization is unsound; without the second, a
    wafer map would show one sample copied nine times.
    """
    grid = cross_section_grid(width=300.0, thickness=SURFACE, headroom=200.0)
    recipe = _particle_recipe(registry, bury=True)[:2]

    def scatter(position):
        outcomes = run_chain(
            recipe, Structure(grid), library=library, recipe_id="s5", position=position
        )
        return predicates.cells_of(outcomes[-1].structure, PARTICLE)

    centre = scatter((0.0, 0.0))
    again = scatter((0.0, 0.0))
    edge = scatter((60.0, 0.0))

    assert np.array_equal(centre, again)
    assert not np.array_equal(centre, edge)


def test_s5_every_step_passes_the_commit_gate(s5, s5_control) -> None:
    """Handoff §4's trap 5: a disk of a few cells against tolerances tuned on planes.

    It does not fire. The reinitialisation moves a particle's interface by
    0.0002 nm (0.045 nm^2 of measure) and the conformal film over four of them
    balances 2.5% off against a 5% tolerance — so nothing was loosened for this
    scenario, which is the only way the numbers stay worth anything.
    """
    assert all(outcome.ok for outcome in s5)
    assert all(outcome.ok for outcome in s5_control)


# -- the shipped scenarios (plan §14's DoD path) ------------------------------


def test_the_shipped_scenarios_all_pass(registry, library) -> None:
    """`nanofab_v3.acceptance` is what the packaged exe runs — plan §14's DoD.

    The exe cannot run pytest, so the recipes and one headline check per scenario
    live in the package and `--selftest` runs them. This asserts they pass, which
    is what keeps the shipped scenarios and the detailed ones above from
    drifting: the recipes are literally the same objects (`_resolve`), and if a
    headline check stopped holding, the suite goes red before the exe does.
    """
    results = acceptance.run_all(registry=registry, library=library)

    assert [result.name for result in results] == [
        scenario.name for scenario in acceptance.scenarios()
    ]
    failed = {result.name: result.failures for result in results if not result.ok}
    assert not failed, failed
    assert all(result.steps > 0 for result in results)


def test_a_scenario_that_breaks_reports_rather_than_raises(registry, library) -> None:
    """In an exe, a traceback on stderr is not a result anybody can act on.

    So `run_scenario` catches, and the failure is the scenario's own — a
    self-test that died on S2 would have said nothing about S3, S4 or S5.
    """
    broken = replace(
        acceptance.scenarios()[0],
        steps=(("substrate.select", {"material": SILICON}),),  # no `surface`
    )

    result = acceptance.run_scenario(broken, registry=registry, library=library)

    assert not result.ok
    assert "ParameterError" in result.failures[0]
    assert result.seconds >= 0.0


def test_a_headline_check_actually_checks(registry, library) -> None:
    """A check that passes whatever happened is worse than no check.

    S1's lift-off pointed at a material that is not in the stack dissolves
    nothing, so the three evaporated pieces all stay — and the scenario has to
    say so. Without this, "S1 passed" would be a sentence about the recipe
    running rather than about the sample it produced.
    """
    wrong_bath = replace(
        acceptance.scenarios()[0],
        steps=acceptance.lift_off_steps()
        + (("strip.lift_off", {"material": UNDERLAYER}),),
        strict=False,
    )

    result = acceptance.run_scenario(wrong_bath, registry=registry, library=library)

    assert not result.ok
    assert any("lift-off should leave" in failure for failure in result.failures)
