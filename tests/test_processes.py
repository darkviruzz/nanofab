"""The process contract, the registry and the didactic set (plan §5, §6).

Three layers, in the order a chain meets them:

1. **the contract** — a parameter is validated at the API boundary, or it does
   not reach the solver (`ParamSpec`, plan §5.1/§3.1);
2. **the registry and the engine** — a step is gated on capabilities, seeded
   deterministically, and committed through the gate (plan §5.2-§5.4, §4.5);
3. **the processes themselves** — each one asserted against the mechanism it is
   supposed to show, at the smallest scale that shows it.

The four acceptance scenarios live next door in `test_scenarios.py`; what is here
is what has to be true *before* a scenario means anything.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from nanofab_v3 import Grid, Structure
from nanofab_v3.kernel import gate as commit_gate
from nanofab_v3.kernel import occurrences, predicates
from nanofab_v3.materials import (
    ALUMINA,
    HARD_RESIST,
    METAL,
    OXIDE,
    PARTICLE,
    RESIST,
    SILICON,
    MaterialLibrary,
    MaterialType,
    didactic_library,
)
from nanofab_v3.model import capability
from nanofab_v3.model.artifact import MemoryArtifactSink
from nanofab_v3.model.quantity import Quantity
from nanofab_v3.processes import (
    IDEAL,
    CapabilityError,
    FunctionStep,
    ParameterError,
    ParamSpec,
    ProcessRegistry,
    RegistrationError,
    StepContext,
    StepResult,
    builtin_registry,
    run_chain,
    run_step,
    step_seed,
)
from nanofab_v3.processes import (
    anneal,
    contamination,
    deposition,
    inspection,
    lithography,
    removal,
    substrate,
)
from nanofab_v3.processes.contract import validate_params

# -- fixtures -----------------------------------------------------------------


@pytest.fixture
def library() -> MaterialLibrary:
    return didactic_library()


@pytest.fixture
def wafer() -> Structure:
    """A blanket silicon wafer with its surface at 40 nm and room above it."""
    grid = substrate.cross_section_grid(width=240.0, thickness=40.0, headroom=200.0)
    return substrate.select_substrate(grid, SILICON, surface=40.0)


@pytest.fixture
def patterned(wafer: Structure) -> Structure:
    """Wafer, 80 nm of resist, an 80 nm window exposed and ideally developed."""
    grid = wafer.grid
    coated = lithography.spin_coat(wafer, RESIST, thickness=80.0)
    exposed = lithography.expose_ideal(coated, RESIST, lithography.windows(grid, [(80.0, 160.0)]))
    return commit_gate.commit(lithography.develop_ideal(exposed, RESIST)).structure


# -- 1. the contract ----------------------------------------------------------


def test_a_quantity_is_unwrapped_only_when_its_unit_matches() -> None:
    """The API boundary of plan §3.1: units are compared once, here, and never again."""
    spec = ParamSpec("thickness", float, unit="nm", default=10.0)

    assert spec.validate(Quantity(25.0, "nm")) == pytest.approx(25.0)
    with pytest.raises(ParameterError, match="expected a quantity in 'nm'"):
        spec.validate(Quantity(25.0, "um"))


def test_a_parameter_out_of_range_never_reaches_the_solver() -> None:
    """A range that is checked rather than documented."""
    spec = ParamSpec("angle", float, unit="deg", default=0.0, minimum=-85.0, maximum=85.0)

    assert spec.validate(30) == pytest.approx(30.0)
    with pytest.raises(ParameterError, match="above the maximum"):
        spec.validate(90.0)
    with pytest.raises(ParameterError, match="below the minimum"):
        spec.validate(-90.0)


def test_a_bool_is_not_a_number_and_a_number_is_not_a_bool() -> None:
    """`True` is `1` in Python, and a rate of `True` would be a silent 1 nm/s."""
    with pytest.raises(ParameterError, match="expected a number"):
        ParamSpec("rate", float, default=1.0).validate(True)
    with pytest.raises(ParameterError, match="expected a bool"):
        ParamSpec("planarise", bool, default=True).validate(1)


def test_an_unknown_parameter_is_an_error_rather_than_being_ignored() -> None:
    """A misspelt parameter that silently takes its default is the worst outcome.

    The recipe still runs, the picture still looks plausible, and the number the
    operator typed had no effect at all.
    """
    schema = (ParamSpec("thickness", float, unit="nm", default=10.0),)

    assert validate_params(schema, {"thickness": 20.0}) == {"thickness": 20.0}
    assert validate_params(schema, None) == {"thickness": 10.0}
    with pytest.raises(ParameterError, match="unknown parameter"):
        validate_params(schema, {"thicknes": 20.0})


def test_a_required_parameter_has_no_default_to_fall_back_on() -> None:
    """`default=None` marks a parameter a recipe has to state."""
    schema = (ParamSpec("duration", float, unit="s", default=None),)

    with pytest.raises(ParameterError, match="missing required parameter"):
        validate_params(schema, {})


# -- 2. capabilities, the registry, the engine --------------------------------


def test_the_structure_backs_its_own_structural_capabilities(patterned: Structure) -> None:
    """Plan §5.3's two structural forms, derived rather than declared."""
    derived = capability.derived(patterned)

    assert capability.of_material(RESIST) in derived
    assert capability.of_field(RESIST, "exposed") in derived
    assert capability.backed_by(patterned, capability.of_material(SILICON))
    assert not capability.backed_by(patterned, capability.of_material(METAL))
    # A free-form promise is not structural, so the structure cannot refute it.
    # It must not contain a dot: the dot is reserved for `<material>.<field>`.
    assert not capability.is_structural("chamber_pumped")
    assert capability.backed_by(patterned, "chamber_pumped")
    assert capability.is_structural("resist.dose")


def test_the_gate_retracts_a_capability_whose_material_is_gone(patterned: Structure) -> None:
    """The sixth step of plan §4.5, doing the thing it exists for.

    Nothing told the gate the resist was dissolved. The resist is not in the
    structure, so `material:resist` is not in the revision — and neither is the
    `exposed` field that was scoped to it.
    """
    stripped = removal.dissolve(patterned, RESIST)

    outcome = commit_gate.commit(
        stripped,
        parent=patterned,
        capabilities={capability.of_material(RESIST), capability.of_field(RESIST, "exposed")},
    )

    assert capability.of_material(RESIST) not in outcome.capabilities
    assert capability.of_field(RESIST, "exposed") not in outcome.capabilities
    assert capability.of_material(SILICON) in outcome.capabilities
    assert any("no longer backed" in warning for warning in outcome.report.warnings)


def test_a_step_that_promises_a_field_and_does_not_deliver_it_fails_the_gate(
    wafer: Structure,
) -> None:
    """A broken promise is caught where it is made, not three steps later.

    Without this the chain keeps running and the failure surfaces as "development
    is not runnable", pointing at the wrong step.
    """
    outcome = commit_gate.commit(wafer, provides={capability.of_field(RESIST, "dose")})

    assert not outcome.report.ok
    assert any("does not carry it" in failure for failure in outcome.report.failures)


def test_a_free_form_capability_is_carried_through_and_can_be_retired(
    wafer: Structure,
) -> None:
    """What the geometry cannot see, it does not get to delete."""
    kept = commit_gate.commit(wafer, capabilities={"chamber_pumped"})
    dropped = commit_gate.commit(
        wafer, capabilities={"chamber_pumped"}, retires={"chamber_pumped"}
    )

    assert "chamber_pumped" in kept.capabilities
    assert "chamber_pumped" not in dropped.capabilities


def test_the_registry_gates_on_capabilities_with_a_reason(library: MaterialLibrary) -> None:
    """Plan §5.3: "exactly like today's gating UI, with better reasons"."""
    registry = builtin_registry()

    reason = registry.blocked_reason("develop.ideal", {capability.of_material(RESIST)})

    assert reason is not None and "resist.exposed" in reason
    assert registry.blocked_reason("develop.ideal", {capability.of_field(RESIST, "exposed")}) is None
    runnable = {step.step_id for step in registry.runnable({capability.of_material(RESIST)})}
    assert "develop.ideal" not in runnable
    assert "deposit.evaporate" in runnable


def test_the_two_development_tiers_gate_on_different_fields() -> None:
    """The capability contract's whole point (plan §5.3), as two step ids.

    Ideal exposure provides `resist.exposed`, dose exposure provides
    `resist.dose`, and each development variant requires the one it can consume.
    A chain that mixes tiers is either complete or not runnable — never silently
    wrong.
    """
    registry = builtin_registry()

    assert registry["develop.ideal"].requires() == {capability.of_field(RESIST, "exposed")}
    assert registry["develop.rate"].requires() == {capability.of_field(RESIST, "dose")}
    assert registry.blocked_reason("develop.rate", {capability.of_field(RESIST, "exposed")})


def test_the_registry_refuses_a_step_that_reaches_for_a_global_generator() -> None:
    """Plan §5.2's determinism lint, best-effort and honest about it."""

    def _rolls(ctx: StepContext) -> StepResult:
        _ = np.random.normal(size=3)  # exactly what §5.2 forbids
        return StepResult(structure=ctx.structure)

    stochastic = FunctionStep(
        step_id="bad.roll",
        display_name="Bad",
        fidelity=IDEAL,
        schema=(),
        required=frozenset(),
        provided=frozenset(),
        run_function=_rolls,
    )

    with pytest.raises(RegistrationError, match="process-global random generator"):
        ProcessRegistry().register(stochastic)


def test_a_step_id_can_only_be_claimed_once() -> None:
    """Two processes under one key is how a recipe silently changes meaning."""
    registry = builtin_registry()

    with pytest.raises(RegistrationError, match="already registered"):
        registry.register(registry["develop.ideal"])


def test_the_registry_groups_the_fidelity_tiers_of_one_technique() -> None:
    """Plan §5.4: several registered processes may model the same technique."""
    families = builtin_registry().by_technique()

    deposits = {step.step_id: step.fidelity for step in families["deposit"]}
    assert deposits["deposit.conformal_offset"] == "ideal"
    assert deposits["deposit.ald"] == "didactic"


def test_running_a_step_without_its_capability_raises_before_anything_moves(
    wafer: Structure, library: MaterialLibrary
) -> None:
    """The gate is in front of the step, not behind it."""
    with pytest.raises(CapabilityError, match="resist.exposed"):
        run_step(builtin_registry()["develop.ideal"], wafer, {}, library=library)


def test_the_step_seed_is_a_pure_function_of_recipe_position_and_index() -> None:
    """ADR-0004's determinism invariant, at the one place randomness enters.

    Neighbouring positions must not produce correlated streams: two adjacent
    wafer positions with the same particle pattern would look like a finding and
    be an artifact of the seeding.
    """
    assert step_seed("r", (0.0, 0.0), 3) == step_seed("r", (0.0, 0.0), 3)
    assert step_seed("r", (0.0, 0.0), 3) != step_seed("r", (0.0, 0.0), 4)
    assert step_seed("r", (0.0, 0.0), 3) != step_seed("r", (1.0, 0.0), 3)
    assert step_seed("r", (0.0, 0.0), 3) != step_seed("s", (0.0, 0.0), 3)


def test_a_chain_run_twice_produces_the_same_sample(library: MaterialLibrary) -> None:
    """Plan §5.2: the outcome is a pure function of (structure, params, position).

    What makes replay materialization (plan §8) sound — adding a wafer position
    later replays to the sample that position would have had.
    """
    grid = substrate.cross_section_grid(width=200.0, thickness=40.0, headroom=140.0)
    registry = builtin_registry()
    recipe = [
        (registry["substrate.select"], {"material": SILICON, "surface": 40.0}),
        (registry["resist.spin_coat"], {"material": RESIST, "thickness": 60.0}),
        (registry["litho.expose_ideal"], {"material": RESIST, "center": 100.0, "width": 60.0}),
        (registry["develop.ideal"], {"material": RESIST}),
    ]

    first = run_chain(recipe, Structure(grid), library=library)
    second = run_chain(recipe, Structure(grid), library=library)

    for a, b in zip(first, second):
        assert a.structure.materials == b.structure.materials
        for material in a.structure.materials:
            assert np.array_equal(
                np.asarray(a.structure.phi_of(material)), np.asarray(b.structure.phi_of(material))
            )


def test_replaying_at_a_new_position_equals_a_fresh_run_at_that_position(
    library: MaterialLibrary,
) -> None:
    """The property plan §8's materialization is, stated at the engine seam.

    Adding a wafer position later replays the chain from substrate selection with
    that position's resolved parameters. That is only "exactly what the position
    would have been" if a chain at a position is reproducible **at that
    position**, which is what this asserts: the same recipe run twice at the
    wafer edge agrees with itself, and the seed that separates it from the centre
    is a different seed rather than a different sample by accident.

    `runtime.materialize` is the same property one layer up, with the cache in
    front of it and with a recipe whose parameters actually vary over the wafer
    (`tests/test_runtime.py`). Here the recipe is position-independent on
    purpose: what is being pinned down is the *seeding*, not the parameters.
    """
    grid = substrate.cross_section_grid(width=200.0, thickness=40.0, headroom=140.0)
    registry = builtin_registry()
    edge = (60.0, 0.0)
    recipe = [
        (registry["substrate.select"], {"material": SILICON, "surface": 40.0}),
        (registry["resist.spin_coat"], {"material": RESIST, "thickness": 60.0}),
        (registry["litho.expose_ideal"], {"material": RESIST, "center": 100.0, "width": 60.0}),
        (registry["develop.ideal"], {"material": RESIST}),
    ]

    replayed = run_chain(recipe, Structure(grid), library=library, position=edge)
    fresh = run_chain(recipe, Structure(grid), library=library, position=edge)

    assert [o.step_id for o in replayed] == [o.step_id for o in fresh]
    for a, b in zip(replayed, fresh):
        assert a.capabilities == b.capabilities
        assert a.structure.materials == b.structure.materials
        for material in a.structure.materials:
            assert np.array_equal(
                np.asarray(a.structure.phi_of(material)), np.asarray(b.structure.phi_of(material))
            )
    assert step_seed("recipe", edge, 3) != step_seed("recipe", (0.0, 0.0), 3)


def test_a_chain_threads_capabilities_from_step_to_step(library: MaterialLibrary) -> None:
    """What a revision promises is what the next step is gated against."""
    grid = substrate.cross_section_grid(width=200.0, thickness=40.0, headroom=140.0)
    registry = builtin_registry()

    outcomes = run_chain(
        [
            (registry["substrate.select"], {"material": SILICON, "surface": 40.0}),
            (registry["resist.spin_coat"], {"material": RESIST, "thickness": 60.0}),
            (registry["litho.expose_ideal"], {"material": RESIST, "center": 100.0, "width": 60.0}),
        ],
        Structure(grid),
        library=library,
    )

    assert outcomes[0].capabilities == {capability.of_material(SILICON)}
    assert capability.of_material(RESIST) in outcomes[1].capabilities
    assert capability.of_field(RESIST, "exposed") in outcomes[2].capabilities
    assert registry.blocked_reason("develop.ideal", outcomes[2].capabilities) is None


# -- 3. the didactic set ------------------------------------------------------


def test_spin_coating_planarises_rather_than_offsetting(wafer: Structure) -> None:
    """A spin coat has a flat top; that is what lithography depends on (plan §6).

    Over a step the film is thin on the high side and thick on the low one, and
    the quoted thickness is the one above the highest topography — which is how a
    resist thickness is quoted.
    """
    from nanofab_v3.kernel import constructors as ctor

    grid = wafer.grid
    stepped = ctor.add_material(
        wafer, "silicon", ctor.box(grid, lower=(40.0, 120.0), upper=(70.0, 240.0))
    )

    coated = commit_gate.commit(lithography.spin_coat(stepped, RESIST, thickness=50.0)).structure

    resist = predicates.cells_of(coated, RESIST)
    tops = [int(np.flatnonzero(resist[:, column]).max()) for column in (20, 200)]
    assert tops[0] == tops[1] == 120  # flat: 70 nm step + 50 nm
    assert int(np.flatnonzero(resist[:, 20]).min()) == 40  # thick on the low side
    assert int(np.flatnonzero(resist[:, 200]).min()) == 70  # thin over the step


def test_ideal_development_opens_the_window_and_leaves_the_rest(patterned: Structure) -> None:
    """`remove resist & exposed`, reachability-gated (plan §6)."""
    resist = predicates.cells_of(patterned, RESIST)
    open_columns = np.flatnonzero(~np.any(resist, axis=0))

    assert open_columns.min() == pytest.approx(81, abs=2)
    assert open_columns.max() == pytest.approx(159, abs=2)
    assert not patterned.solid_mask[100, 120]  # the window is clear to the wafer
    assert patterned.solid_mask[100, 20]  # the mask is not


def test_ideal_development_cannot_reach_a_buried_exposed_pocket(wafer: Structure) -> None:
    """The ideal tier's reachability gate, at the smallest scale it shows at.

    A soluble region with no path to the surface stays. It is the same physics
    S3 shows at scenario scale, and it is asserted here because the ideal tier
    gates by *region* rather than by speed field — two implementations of one
    predicate, and this is the one that would silently do nothing.
    """
    grid = wafer.grid
    coated = lithography.spin_coat(wafer, RESIST, thickness=80.0)
    pocket = lithography.windows(grid, [(80.0, 160.0)])
    # Only expose a band in the middle of the film: no path from the surface.
    buried = np.asarray(pocket) <= 0.0
    rows = np.zeros(grid.shape, dtype=bool)
    rows[70:90] = True
    marked = coated.with_field(("exposed", RESIST), (buried & rows).astype(np.int8))

    developed = lithography.develop_ideal(marked, RESIST)

    assert developed is marked or np.array_equal(
        np.asarray(developed.phi_of(RESIST)), np.asarray(marked.phi_of(RESIST))
    )


def test_the_dose_tier_writes_a_profile_where_the_ideal_tier_writes_a_step(
    wafer: Structure, library: MaterialLibrary
) -> None:
    """Plan §3.3's two exposure fields, next to each other.

    The blur is what gives the developed sidewall a slope, and Beer-Lambert is
    what gives a thick resist a foot. Neither exists in the ideal tier, which is
    the honest statement of what "ideal" means here.
    """
    grid = wafer.grid
    coated = lithography.spin_coat(wafer, RESIST, thickness=80.0)
    pattern = lithography.windows(grid, [(80.0, 160.0)])

    ideal = lithography.expose_ideal(coated, RESIST, pattern)
    physical = lithography.expose_dose(coated, RESIST, pattern, dose=150.0, blur=8.0, library=library)

    exposed = np.asarray(ideal.field(("exposed", RESIST)))
    dose = np.asarray(physical.field(("dose", RESIST)))
    assert set(np.unique(exposed)) == {0, 1}
    edge = dose[110, 70:90]
    assert np.all(np.diff(edge) >= -1e-6)  # a gradient, not a step
    assert 3 < np.count_nonzero((edge > 1.0) & (edge < 149.0)) # a real penumbra
    top, bottom = dose[118, 120], dose[102, 120]
    assert bottom < top  # Beer-Lambert: the dose is attenuated with depth


def test_the_downgrade_adapter_says_what_it_throws_away(
    wafer: Structure, library: MaterialLibrary
) -> None:
    """Plan §5.3 allows downgrades and forbids upgrades; this is what one looks like."""
    grid = wafer.grid
    coated = lithography.spin_coat(wafer, RESIST, thickness=80.0)
    dosed = lithography.expose_dose(
        coated, RESIST, lithography.windows(grid, [(80.0, 160.0)]), dose=150.0, blur=8.0
    )

    outcome = run_step(
        builtin_registry()["litho.threshold_dose"],
        dosed,
        {"material": RESIST, "threshold": 75.0},
        library=library,
        capabilities={capability.of_field(RESIST, "dose")},
    )

    assert capability.of_field(RESIST, "exposed") in outcome.capabilities
    assert capability.of_field(RESIST, "dose") in outcome.capabilities
    assert any("discarded" in line for line in outcome.logs)


def test_development_at_a_rate_eats_downward_where_the_dose_is(
    wafer: Structure, library: MaterialLibrary
) -> None:
    """The physical tier: the front moves at `develop_rate(dose)` (plan §6).

    Same structure, same resist, a different *kind* of operation — and the
    unexposed mask survives because its dark rate is two orders of magnitude
    below the exposed one, not because anything masked it.
    """
    grid = wafer.grid
    coated = lithography.spin_coat(wafer, RESIST, thickness=80.0)
    dosed = lithography.expose_dose(
        coated, RESIST, lithography.windows(grid, [(80.0, 160.0)]), dose=200.0, blur=4.0
    )

    outcome = lithography.develop_at_rate(dosed, RESIST, duration=3.0, library=library)
    developed = commit_gate.commit(outcome.structure, parent=dosed, swept=outcome.swept).structure

    window = predicates.cells_of(developed, RESIST)[:, 120]
    mask = predicates.cells_of(developed, RESIST)[:, 20]
    assert int(np.count_nonzero(window)) < int(np.count_nonzero(mask))
    assert outcome.sub_steps > 1  # it really was sub-stepped, not a set operation


def test_an_evaporated_film_leaves_a_vertical_sidewall_bare(patterned: Structure) -> None:
    """Why a naive lift-off works at all (plan §6, S1).

    A delta source at normal incidence puts nothing on a vertical wall — so the
    metal on the resist and the metal in the window are two disconnected pieces,
    and no step had to say so.
    """
    outcome = deposition.evaporate(patterned, METAL, thickness=20.0)
    grown = commit_gate.commit(outcome.structure, parent=patterned, swept=outcome.swept).structure

    _, pieces = occurrences.label_region(grown.grid, grown.inside(METAL))
    assert pieces == 3  # two caps on the mask, one pattern in the window
    assert predicates.is_reachable(grown, RESIST)  # the solvent still gets to the wall


def test_a_sputtered_film_coats_the_sidewall_an_evaporation_leaves_bare(
    patterned: Structure,
) -> None:
    """The difference S4 rests on: a broad lobe sees what a point source cannot."""
    evaporated = deposition.evaporate(patterned, METAL, thickness=20.0).structure
    sputtered = deposition.sputter_deposit(
        patterned, METAL, thickness=20.0, exponent=1.0
    ).structure

    wall = slice(60, 110)  # the window's left sidewall stands at x = 80
    assert not np.any(evaporated.inside(METAL)[wall, 81])
    assert np.count_nonzero(sputtered.inside(METAL)[wall, 81]) == wall.stop - wall.start


def test_conformal_offset_and_gated_ald_are_two_answers_to_one_technique() -> None:
    """Plan §5.4, measured: the same growth, with and without the reachability gate.

    On an *open* surface they agree to the resolution the fast path is exact at.
    Where they differ is a sealed cavity, and that difference is scenario S3.
    """
    grid = Grid(origin=(0.0, 0.0), spacing=1.0, shape=(120, 120), axes=("y", "x"))
    wafer = substrate.select_substrate(grid, SILICON, surface=40.0)

    offset = deposition.conformal_offset(wafer, ALUMINA, thickness=10.0).structure
    gated = deposition.atomic_layer_deposition(wafer, ALUMINA, thickness=10.0).structure

    tops = [int(np.flatnonzero(s.inside(ALUMINA)[:, 60]).max()) for s in (offset, gated)]
    assert tops[0] == tops[1]


def test_a_wet_etch_is_selective_because_of_the_rate_table(
    patterned: Structure, library: MaterialLibrary
) -> None:
    """Plan §4.2: mask behaviour emerges from rates, and so does selectivity.

    The resist has no wet-etch rate, so it does not move; nothing in the etch
    step knows it is a mask.
    """
    from nanofab_v3.processes.etching import wet_etch

    before = patterned.measure(patterned.inside(RESIST))
    etched = wet_etch(patterned, duration=10.0, library=library).structure

    assert etched.measure(etched.inside(RESIST)) == pytest.approx(before, rel=0.01)


def test_lift_off_dissolves_before_it_drops_and_the_order_is_the_physics(
    patterned: Structure,
) -> None:
    """Removing the unsupported metal first would make S3 succeed (plan §6).

    A lift-off that dropped floating components before the solvent acted would
    carry away a film still resting on resist — and would therefore "work" in
    exactly the scenario whose whole point is that it must not.
    """
    outcome = deposition.evaporate(patterned, METAL, thickness=20.0)
    grown = commit_gate.commit(outcome.structure, parent=patterned, swept=outcome.swept).structure

    assert not predicates.unsupported(grown).any()  # nothing floats yet
    dissolved = removal.dissolve(grown, RESIST)
    assert predicates.unsupported(dissolved).any()  # the caps float now
    assert RESIST not in removal.lift_off(grown, RESIST).phi


def test_an_unlisted_material_survives_a_bath_that_never_heard_of_it(
    patterned: Structure, library: MaterialLibrary
) -> None:
    """A bath is applied to the sample, not to a list of things to remove."""
    from nanofab_v3.processes.rates import dissolve_rates

    rates = dissolve_rates(library, patterned, "acetone")

    assert rates.for_material(RESIST) > 0.0
    assert rates.for_material(SILICON) == 0.0
    assert rates.default == 0.0


def test_the_release_map_stops_a_mask_redepositing_what_it_is_not_losing(
    patterned: Structure, library: MaterialLibrary
) -> None:
    """The seam where material knowledge enters a geometry-only module (M2 note 8)."""
    from nanofab_v3.materials import ION_BEAM
    from nanofab_v3.processes.rates import release_map

    release = release_map(library, patterned, ION_BEAM)

    assert release is not None
    resist_cells = patterned.inside(RESIST)
    silicon_cells = patterned.inside(SILICON)
    assert float(np.max(release[resist_cells])) == pytest.approx(1.0)  # the fastest
    assert float(np.max(release[silicon_cells])) < 1.0


def test_a_step_is_a_plain_function_before_it_is_a_registry_entry(
    patterned: Structure,
) -> None:
    """Interview decision I7, literally: the function is callable on its own."""
    direct = removal.dissolve(patterned, RESIST)
    wrapped = builtin_registry()["strip.dissolve"].run(
        StepContext(structure=patterned, params={"material": RESIST})
    )

    assert direct.materials == wrapped.structure.materials
    assert np.array_equal(
        np.asarray(direct.phi_of(SILICON)), np.asarray(wrapped.structure.phi_of(SILICON))
    )


def test_a_library_a_process_has_never_heard_of_still_runs(patterned: Structure) -> None:
    """`StepContext.library` is data, so a scene can carry materials nobody described.

    The rule `MaterialLibrary` enforces by raising on lookup has to stop short of
    the *processes*: a deposition of an undescribed material falls back to its
    parameters, because the alternative is a package that cannot draw anything
    the didactic library does not contain.
    """
    sparse = MaterialLibrary.of(MaterialType(material_id=SILICON, name="Silicon"))

    outcome = run_step(
        builtin_registry()["deposit.evaporate"],
        patterned,
        {"material": "gold", "thickness": 10.0},
        library=sparse,
    )

    assert "gold" in outcome.structure.phi
    assert capability.of_material("gold") in outcome.capabilities


# -- 4. particles and clean (plan §6 rows 16-17, milestone M5) ----------------


def test_a_particle_rests_on_whatever_is_topmost_in_its_column(patterned) -> None:
    """The placement decision: on the surface, not at a random point in the domain.

    On a developed window the topmost solid differs by 80 nm between the resist
    and the floor of the window, and a particle in either column sits on *that*
    column's surface. A uniform draw over the domain would put most of them
    inside the resist, where `add_material` would carve them away to nothing.
    """
    rng = np.random.default_rng(7)
    seeded, landed = contamination.scatter_particles(
        patterned, rng, count=40, radius=5.0
    )

    assert landed == 40
    cells = predicates.cells_of(seeded, PARTICLE)
    tops = contamination.surface_rows(patterned)
    for column in np.flatnonzero(np.any(cells, axis=0)):
        lowest = int(np.flatnonzero(cells[:, column]).min())
        assert lowest > tops[column] - 2  # never buried in what it landed on


def test_particles_that_overlap_are_one_occurrence() -> None:
    """ADR-0003 again: identity is derived, so two touching particles are one piece.

    Six 20 nm particles cannot fit side by side across a 100 nm domain, so some
    of them land on each other — and what comes out is fewer occurrences than
    particles, which is the derived view answering rather than a bookkeeping
    choice made when they were placed.
    """
    grid = substrate.cross_section_grid(width=100.0, thickness=20.0, headroom=120.0)
    wafer = substrate.select_substrate(grid, SILICON, surface=20.0)

    crowded, landed = contamination.scatter_particles(
        wafer, np.random.default_rng(0), count=6, radius=20.0
    )

    assert landed == 6
    assert 1 <= contamination.count_occurrences(crowded, PARTICLE) < landed


def test_a_particle_with_no_surface_to_land_on_is_skipped() -> None:
    """An empty domain has nothing to land on, and no floor is invented for it."""
    grid = substrate.cross_section_grid(width=100.0, thickness=20.0, headroom=60.0)
    empty = Structure(grid)

    seeded, landed = contamination.scatter_particles(empty, np.random.default_rng(1),
                                                     count=5, radius=4.0)

    assert landed == 0
    assert seeded is empty


def test_seeding_no_particles_returns_the_sample_untouched(wafer) -> None:
    seeded, landed = contamination.scatter_particles(
        wafer, np.random.default_rng(2), count=0, radius=4.0
    )
    assert (landed, seeded) == (0, wafer)


def test_the_particle_step_draws_only_from_the_context_rng(wafer, library) -> None:
    """§5.2's contract, from the registry's side: same seed, same sample.

    The lint that refuses `np.random` at registration is best-effort (it reads
    the wrapper's source); this is the behavioural half of the same rule, and it
    is what ADR-0004's replay actually rests on.
    """
    registry = builtin_registry()
    step = registry["particle.seed"]

    def once(recipe_id, position):
        outcome = run_step(step, wafer, {"count": 6, "radius": 6.0, "radius_spread": 0.4},
                           library=library, recipe_id=recipe_id, position=position, index=1)
        return predicates.cells_of(outcome.structure, PARTICLE)

    assert np.array_equal(once("r", (0.0, 0.0)), once("r", (0.0, 0.0)))
    assert not np.array_equal(once("r", (0.0, 0.0)), once("r", (30.0, 0.0)))
    assert not np.array_equal(once("r", (0.0, 0.0)), once("other", (0.0, 0.0)))


def test_a_clean_on_a_sample_with_no_particles_is_a_no_op(wafer) -> None:
    cleaned, removed, left = contamination.clean(wafer, PARTICLE)

    assert (cleaned, removed, left) == (wafer, 0, 0)


def test_clean_takes_a_whole_occurrence_and_not_the_cells_it_touched(wafer) -> None:
    """Per occurrence, for `removal.dissolve`'s reason: a bath takes the piece."""
    seeded, _ = contamination.scatter_particles(
        wafer, np.random.default_rng(3), count=4, radius=7.0
    )
    before = contamination.count_occurrences(seeded, PARTICLE)

    cleaned, removed, left = contamination.clean(seeded, PARTICLE)

    assert before >= 1
    assert (removed, left) == (before, 0)
    assert PARTICLE not in cleaned.phi


# -- 5. inspection (plan §6 row 18, §5.1, milestone M5) -----------------------


def test_an_inspection_returns_the_very_same_structure(patterned, library) -> None:
    """Plan §5.1: "return the input structure unchanged".

    The same object, not an equal one — which is what lets §20.2's sharing rule
    hand the whole revision its parent's arrays, so an inspection costs no memory
    and moves no interface. `swept=None` keeps it out of the balance check too,
    which is the honest answer for a step that swept no front.
    """
    for step in (inspection.SEM, inspection.PROFILOMETER, inspection.ELLIPSOMETER):
        result = step.run(StepContext(structure=patterned, params={
            spec.name: spec.default for spec in step.parameter_schema()
        }, library=library))
        assert result.structure is patterned
        assert result.swept is None
        assert result.provides == frozenset()

    outcome = run_step(inspection.SEM, patterned, {}, library=library)
    assert outcome.ok
    assert outcome.report.shared_with_parent == patterned.materials
    for material in patterned.materials:
        assert outcome.structure.phi_of(material) is patterned.phi_of(material)


def test_a_blunt_stylus_under_reports_a_narrow_trench(patterned, library) -> None:
    """The profilometer's characteristic error, and the reason it is a parameter.

    A tip cannot enter a feature narrower than itself. On an 80 nm window in
    80 nm of resist an ideal point stylus reads the full step; a 60 nm tip rolls
    across the mouth and reads a fraction of it. Both are the same surface.
    """
    def step_height(radius):
        outcome = run_step(
            inspection.PROFILOMETER, patterned, {"stylus_radius": radius}, library=library
        )
        return outcome.measurements["step_height"].value

    ideal = step_height(0.0)
    blunt = step_height(60.0)

    assert ideal == pytest.approx(80.0, abs=1.0)
    assert blunt < 0.6 * ideal
    assert blunt > 0.0  # it still sees a dimple


def test_the_ellipsometer_reports_the_topmost_film_when_none_is_named(
    patterned, library
) -> None:
    """The one step whose answer comes from the library rather than the geometry."""
    outcome = run_step(inspection.ELLIPSOMETER, patterned, {}, library=library)

    assert outcome.measurements["thickness"].value == pytest.approx(80.0, abs=1.0)
    assert outcome.measurements["thickness"].unit == "nm"
    assert outcome.measurements["n"].value == pytest.approx(1.51)
    assert 0.0 < outcome.measurements["coverage"].value < 1.0


def test_an_ellipsometer_on_a_material_that_is_not_there_measures_zero(
    wafer, library
) -> None:
    """A missing film is a reading of nothing, not an exception."""
    outcome = run_step(
        inspection.ELLIPSOMETER, wafer, {"material": str(METAL)}, library=library
    )

    assert outcome.measurements["thickness"].value == 0.0
    assert outcome.artifacts == ()


def test_the_sem_counts_the_pieces_of_what_it_is_pointed_at(patterned, library) -> None:
    """A developed window splits the resist in two, and the SEM says two."""
    resist = run_step(inspection.SEM, patterned, {"material": str(RESIST)}, library=library)
    stack = run_step(inspection.SEM, patterned, {}, library=library)

    assert resist.measurements["features"].value == 2.0
    assert stack.measurements["features"].value == 1.0  # the substrate joins them


def test_an_inspection_with_no_sink_still_measures_everything(patterned, library) -> None:
    """`model.artifact`'s honest default: no reference beats a reference to nothing."""
    outcome = run_step(inspection.PROFILOMETER, patterned, {}, library=library)

    assert outcome.artifacts == ()
    assert outcome.measurements["step_height"].value > 0.0


def test_an_inspection_with_a_sink_produces_a_reference_to_what_it_stored(
    patterned, library
) -> None:
    sink = MemoryArtifactSink()

    outcome = run_step(
        inspection.SEM, patterned, {"tag": "after-develop"}, library=library, artifacts=sink
    )

    (ref,) = outcome.artifacts
    assert ref.kind == "image"
    assert "sem-after-develop" in sink
    assert np.array_equal(sink.payloads["sem-after-develop"], patterned.material_index)


def test_etch_inspect_etch_inspect_is_four_plain_steps(wafer, library) -> None:
    """Interview Q6, which the chain has been able to express since M4.

    Two etches with an inspection after each, and the two inspections disagree —
    which is the whole reason inspection is a step rather than a panel: what was
    measured is pinned to the revision it was measured on.
    """
    registry = builtin_registry()
    sink = MemoryArtifactSink()
    coated = deposition.conformal_offset(wafer, OXIDE, thickness=40.0).structure

    outcomes = run_chain(
        [
            (registry["etch.wet"], {"duration": 10.0}),
            (registry["inspect.profilometer"], {"tag": "first"}),
            (registry["etch.wet"], {"duration": 10.0}),
            (registry["inspect.profilometer"], {"tag": "second"}),
        ],
        coated,
        library=library,
        artifacts=sink,
    )

    assert [outcome.step_id for outcome in outcomes] == [
        "etch.wet", "inspect.profilometer", "etch.wet", "inspect.profilometer"
    ]
    assert len(sink) == 2
    first, second = outcomes[1].measurements, outcomes[3].measurements
    assert second["mean_height"].value < first["mean_height"].value


# -- 6. anneal (plan §6 row 15, §16, milestone M5) ----------------------------


def _bake(temperature=200.0, duration=600.0, **overrides):
    params = {
        "temperature": temperature,
        "duration": duration,
        "material": str(RESIST),
        "becomes": str(HARD_RESIST),
        "activation": 150.0,
    }
    params.update(overrides)
    return params


def test_an_anneal_changes_the_material_and_not_the_geometry(patterned, library) -> None:
    """Plan §21.2's decision: a property change is a change of library entry.

    `StepContext.library` is passed in and never stored (plan §3.4), so an
    anneal cannot hand back a modified one. It does not need to: the same `phi`
    goes to a different `MaterialType`, and every rate downstream follows.
    """
    outcome = run_step(anneal.ANNEAL, patterned, _bake(), library=library)

    assert outcome.ok
    assert RESIST not in outcome.structure.phi
    assert HARD_RESIST in outcome.structure.phi
    assert outcome.structure.measure(
        outcome.structure.inside(HARD_RESIST)
    ) == pytest.approx(patterned.measure(patterned.inside(RESIST)), rel=1e-3)


def test_the_capabilities_swap_without_anything_being_told_to(patterned, library) -> None:
    """The gate re-derives both halves from the structure it was handed."""
    before = capability.derived(patterned)
    outcome = run_step(anneal.ANNEAL, patterned, _bake(), library=library)

    assert "material:resist" in before
    assert "material:resist" not in outcome.capabilities
    assert "material:resist_hardbaked" in outcome.capabilities
    assert anneal.ANNEALED in outcome.capabilities
    # a latent image in a resist that has been hard-baked is not a latent image
    assert "resist.exposed" not in outcome.capabilities


def test_a_bake_below_the_activation_leaves_the_material_alone(patterned, library) -> None:
    """A soft bake is still a thermal budget, and still not a transformation."""
    outcome = run_step(anneal.ANNEAL, patterned, _bake(temperature=90.0), library=library)

    assert RESIST in outcome.structure.phi
    assert HARD_RESIST not in outcome.structure.phi
    assert outcome.measurements["thermal_budget"].value > 0.0
    assert any("below" in line for line in outcome.logs)


def test_the_thermal_budget_accumulates_over_bakes(patterned, library) -> None:
    """A sample carries its whole thermal history, not its last bake.

    Global, because a furnace heats the whole sample: two 300 s bakes and one
    600 s bake leave the same number.
    """
    once = run_step(
        anneal.ANNEAL, patterned, _bake(duration=600.0, material="", becomes=""),
        library=library,
    )
    first = run_step(
        anneal.ANNEAL, patterned, _bake(duration=300.0, material="", becomes=""),
        library=library,
    )
    twice = run_step(
        anneal.ANNEAL, first.structure, _bake(duration=300.0, material="", becomes=""),
        library=library, index=1,
    )

    assert twice.measurements["thermal_budget"].value == pytest.approx(
        once.measurements["thermal_budget"].value
    )
    assert anneal.THERMAL_BUDGET.key() in twice.structure.fields


def test_hard_baking_a_resist_is_a_resist_the_solvent_no_longer_takes(
    wafer, library
) -> None:
    """The mechanism, and why it is worth a material rather than a footnote.

    The *rate* tier is where chemistry lives: `dissolve_rates` gives a rate of
    zero to a material the bath does not attack, and a hard-baked resist has no
    `DissolveModel` at all. Both runs are the same recipe with one step inserted.
    """
    registry = builtin_registry()
    coat = (registry["resist.spin_coat"], {"material": RESIST, "thickness": 60.0})
    strip = (registry["strip.rate"], {"solvent": "acetone", "duration": 3.0})

    coated = run_chain([coat], wafer, library=library)[-1].structure
    applied = coated.measure(coated.inside(RESIST))
    baked = run_chain(
        [coat, (registry["anneal.thermal"], _bake()), strip], wafer, library=library
    )
    control = run_chain([coat, strip], wafer, library=library)

    left = baked[-1].structure
    stripped = control[-1].structure

    assert applied > 0.0
    # acetone left the baked film standing, whole
    assert left.measure(left.inside(HARD_RESIST)) == pytest.approx(applied)
    # ... and took the unbaked one entirely. The *key* survives an advection —
    # only a region operation drops a material — so the measure is the assertion.
    assert stripped.measure(stripped.inside(RESIST)) == 0.0


def test_the_anneal_says_which_behaviour_changed(patterned, library) -> None:
    """Behaviour lives in the library, so the log says which of it moved."""
    outcome = run_step(anneal.ANNEAL, patterned, _bake(), library=library)

    line = next(line for line in outcome.logs if "->" in line)
    assert "no longer soluble" in line
    assert "no longer developable" in line
    assert "dry_etch 0.5 -> 0.25 nm/s" in line


def test_an_anneal_moves_no_geometry_and_reflow_stays_open(patterned, library) -> None:
    """Plan §16: curvature-driven reflow is deliberately not built.

    The assertion that keeps it that way — an anneal sweeps no front, so it is
    outside the balance check, and the transformed material's field is the very
    array the old one had.
    """
    result = anneal.ANNEAL.run(
        StepContext(structure=patterned, params={
            spec.name: spec.default for spec in anneal.ANNEAL.parameter_schema()
        } | _bake(), library=library)
    )

    assert result.swept is None
    assert result.structure.phi_of(HARD_RESIST) is patterned.phi_of(RESIST)
