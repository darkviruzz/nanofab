"""Substrate and domain: two sizes that stopped pretending to be one (M7).

Milestone M7, roadmap E1-E7. The single idea underneath all of it is §1's
arithmetic: a `phi` costs `rows x columns x 4` bytes, so a 625 µm wafer at 1 nm
would be 15 GB per revision. A wafer therefore cannot be a domain. What follows:

- the **substrate** is metadata — form factor, real dimensions, thickness — and
  lives in `Structure.metadata` so a later step can read it (E1, E7);
- the **domain** is a nanometre-scale window that follows the sample, growing
  when an etch or a deposition runs out of it and giving room back when there is
  far too much (E5);
- the two meet in exactly one place: `substrate.select`, which is why nothing
  else may be the first step (E4).

What is asserted here is the behaviour an operator would notice. The arithmetic
of the resize itself is `test_domain.py`'s.
"""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import domain
from nanofab_v3.kernel import gate as commit_gate
from nanofab_v3.materials import CHROME, FUSED_SILICA, SILICON, didactic_library
from nanofab_v3.model import capability
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes import ParameterError, builtin_registry, run_step, substrate
from nanofab_v3.processes.substrate import (
    MM,
    SUBSTRATE_PRESETS,
    SubstrateSpec,
    cross_section_grid,
    etched_depth,
    through_etched,
)


@pytest.fixture
def library():
    return didactic_library()


@pytest.fixture
def registry():
    return builtin_registry()


# -- the presets (E2, E3) -----------------------------------------------------


def test_the_preset_list_is_two_sections_sorted_the_way_e3_asks() -> None:
    """By material, then ascending size, then ascending thickness — decided once.

    Sorted in the table rather than in the widget, so a dropdown, a recipe file
    and this test see one order, and "which is the default" is a fact about the
    list rather than about whichever one was built first.
    """
    sections = substrate.presets_by_section()

    # "other" arrived with E30's semi-infinite entry — a substrate that is
    # neither a wafer nor a mask blank because its thickness is not stated.
    assert set(sections) == {"wafer", "mask", "other"}
    for entries in sections.values():
        keys = [preset.sort_key for preset in entries]
        assert keys == sorted(keys)
    assert SUBSTRATE_PRESETS == tuple(sorted(SUBSTRATE_PRESETS, key=lambda p: p.sort_key))


def test_the_default_preset_is_a_100_mm_1_mm_fused_silica_round_substrate() -> None:
    """E3, literally: "Default: rund, 100 mm, 1 mm, Fused Silica"."""
    spec = SubstrateSpec.from_preset(substrate.DEFAULT_PRESET)

    assert spec.form_factor == substrate.WAFER
    assert spec.material == FUSED_SILICA
    assert spec.diameter == pytest.approx(100.0 * MM)
    assert spec.thickness == pytest.approx(1.0 * MM)


def test_the_mask_blanks_are_the_semi_short_codes_with_their_own_geometry() -> None:
    """Nine codes, three side lengths, six thicknesses — the table from the handoff."""
    masks = {preset.key: preset for preset in substrate.presets_by_section()["mask"]}

    assert set(masks) == {
        f"mask_{code}"
        for code in ("5006", "5009", "5018", "6009", "6012", "6025", "9012", "9020", "9025")
    }
    assert {preset.side_mm for preset in masks.values()} == {126.6, 152.0, 228.6}
    assert masks["mask_6025"].side_mm == 152.0
    assert masks["mask_6025"].thickness_mm == 6.35
    assert all(preset.material == FUSED_SILICA for preset in masks.values())
    # A blank is square, so both sides come out equal rather than one being unstated.
    spec = SubstrateSpec.from_preset("mask_6025")
    assert spec.size_x == spec.size_y == pytest.approx(152.0 * MM)
    assert spec.diameter is None


def test_an_unknown_preset_is_an_error_that_lists_the_ones_there_are() -> None:
    with pytest.raises(ValueError, match="no substrate preset"):
        SubstrateSpec.from_preset("mask_9999")


# -- the step (E1, E2) --------------------------------------------------------


def test_a_preset_drives_the_substrate_and_the_domain_together(library, registry) -> None:
    """E2's whole point: one choice, so the two cannot disagree.

    The DoD's first sentence — "a 100 mm fused-silica preset produces substrate
    and domain consistently" — is this test.
    """
    outcome = run_step(
        registry["substrate.select"],
        Structure(cross_section_grid(width=200.0, thickness=40.0, headroom=100.0)),
        {"preset": "wafer_fs_100", "surface": 40.0},
        library=library,
    )

    assert outcome.ok
    assert outcome.structure.materials == (FUSED_SILICA,)
    assert outcome.structure.meta(substrate.THICKNESS_KEY) == pytest.approx(1.0 * MM)
    assert outcome.structure.meta(substrate.DIAMETER_KEY) == pytest.approx(100.0 * MM)
    assert outcome.structure.meta(substrate.FORM_FACTOR_KEY) == substrate.WAFER
    # The domain came from the preset rather than from the grid it was handed.
    grid = outcome.structure.grid
    assert (grid.shape[-1] - 1) * grid.spacing == pytest.approx(1200.0)
    assert grid.spacing == pytest.approx(1.0)


def test_a_mask_blank_gets_a_wider_domain_at_a_coarser_resolution(library, registry) -> None:
    """E2 again: a blank is written with features a wafer's window is too small for."""
    outcome = run_step(
        registry["substrate.select"],
        Structure(cross_section_grid(width=200.0, thickness=40.0, headroom=100.0)),
        {"preset": "mask_6025", "surface": 40.0},
        library=library,
    )

    grid = outcome.structure.grid
    assert (grid.shape[-1] - 1) * grid.spacing == pytest.approx(2400.0)
    assert grid.spacing == pytest.approx(2.0)


def test_without_a_preset_the_domain_the_recipe_came_with_is_kept(library, registry) -> None:
    """A step whose output depended on something not in its parameters would be
    a step no recipe reproduces. So a preset *suggests*; nothing is silent."""
    grid = cross_section_grid(width=200.0, thickness=40.0, headroom=100.0)

    outcome = run_step(
        registry["substrate.select"],
        Structure(grid),
        {"material": str(SILICON), "surface": 40.0},
        library=library,
    )

    assert outcome.structure.grid == grid
    assert outcome.structure.meta(substrate.THICKNESS_KEY) is None


def test_the_explicit_fields_override_the_preset(library, registry) -> None:
    """The same override pattern as E13's tone and E17's thickness: typed wins."""
    outcome = run_step(
        registry["substrate.select"],
        Structure(cross_section_grid(width=200.0, thickness=40.0, headroom=100.0)),
        {
            "preset": "wafer_fs_100",
            "material": str(SILICON),
            "thickness": 0.525,
            "surface": 40.0,
            "domain_width": 300.0,
        },
        library=library,
    )

    assert outcome.structure.materials == (SILICON,)
    assert outcome.structure.meta(substrate.THICKNESS_KEY) == pytest.approx(0.525 * MM)
    grid = outcome.structure.grid
    assert (grid.shape[-1] - 1) * grid.spacing == pytest.approx(300.0)


def test_semi_infinite_is_a_form_factor_and_not_a_second_step(library, registry) -> None:
    """E1: one step, one recipe format. "Thickness irrelevant" is a *value*."""
    outcome = run_step(
        registry["substrate.select"],
        Structure(cross_section_grid(width=200.0, thickness=40.0, headroom=100.0)),
        {"form_factor": substrate.SEMI_INFINITE, "thickness": 0.5, "surface": 40.0},
        library=library,
    )

    assert outcome.structure.meta(substrate.FORM_FACTOR_KEY) == substrate.SEMI_INFINITE
    assert outcome.structure.meta(substrate.THICKNESS_KEY) is None
    assert through_etched(outcome.structure) is None

    with pytest.raises(ValueError, match="semi-infinite substrate has no thickness"):
        SubstrateSpec(form_factor=substrate.SEMI_INFINITE, thickness=1.0)


def test_an_unknown_form_factor_or_finish_is_refused_at_the_boundary() -> None:
    with pytest.raises(ParameterError):
        substrate.SELECT_SUBSTRATE.parameter_schema()[2].validate("blob")
    with pytest.raises(ValueError, match="form factor must be"):
        SubstrateSpec(form_factor="blob")
    with pytest.raises(ValueError, match="surface finish must be"):
        SubstrateSpec(surface_finish="shiny")


# -- E4: nothing but the substrate may be first -------------------------------


def test_the_substrate_is_the_only_step_an_empty_sample_can_run(registry) -> None:
    """E4, at the registry, with a sentence rather than a runtime physics warning."""
    assert {step.step_id for step in registry.runnable(frozenset())} == {"substrate.select"}
    assert capability.DOMAIN in registry["substrate.select"].provides()

    reason = registry.blocked_reason("deposit.evaporate", frozenset())

    assert reason is not None and "substrate is always the first step" in reason


def test_the_domain_capability_is_derived_rather_than_declared(library, registry) -> None:
    """A structure with geometry *has* a domain, so it is checked, not trusted."""
    empty = Structure(cross_section_grid(width=200.0, thickness=40.0, headroom=100.0))

    assert capability.DOMAIN not in capability.derived(empty)

    outcome = run_step(
        registry["substrate.select"], empty, {"surface": 40.0}, library=library
    )

    assert capability.DOMAIN in outcome.capabilities
    assert capability.is_structural(capability.DOMAIN)


# -- E5: the domain follows the sample ----------------------------------------


def test_a_coat_taller_than_the_headroom_grows_the_domain_instead_of_failing(
        library, registry
) -> None:
    """The DoD's second sentence, from the top. Before M7 this was a FAIL."""
    grid = cross_section_grid(width=240.0, thickness=40.0, headroom=100.0)
    wafer = substrate.select_substrate(grid, SILICON, surface=40.0)

    outcome = run_step(
        registry["resist.spin_coat"], wafer, {"spin_speed": 1000.0}, library=library
    )

    assert outcome.ok
    assert outcome.attempts == 2  # ran, ran out of room, was given more, ran again
    assert outcome.structure.grid.shape[0] > grid.shape[0]
    assert outcome.domain.above > 0 and outcome.domain.below == 0
    assert any("domain grew" in line for line in outcome.logs)


def test_an_etch_that_would_leave_the_domain_below_grows_it(library, registry) -> None:
    """The DoD's second sentence, from the bottom — and the harder direction.

    The drawn substrate is 60 nm deep and the etch takes 100. The wafer is really
    525 µm thick, so there is nothing wrong with the etch: what was too small was
    the picture, and the picture is what moves.
    """
    grid = cross_section_grid(width=240.0, thickness=60.0, headroom=120.0)
    spec = SubstrateSpec(
        material=SILICON, form_factor=substrate.WAFER,
        thickness=0.525 * MM, diameter=100.0 * MM,
    )
    wafer = substrate.select_substrate(grid, SILICON, surface=60.0, spec=spec)
    masked = commit_gate.commit(
        ctor.add_material(wafer, CHROME, ctor.box(grid, [60.0, 0.0], [80.0, 120.0]))
    ).structure

    outcome = run_step(
        registry["etch.icp_fluorine"], masked, {"duration": 150.0}, library=library
    )

    assert outcome.ok
    assert outcome.domain.below > 0
    assert outcome.structure.grid.origin[0] < 0.0  # the offset rides on the origin
    assert etched_depth(outcome.structure) == pytest.approx(100.0, abs=2.0)


def test_hitting_the_cap_says_what_raising_it_would_cost(library, registry) -> None:
    """The DoD's third sentence. E5 makes the cap raisable, so the price is shown."""
    grid = cross_section_grid(width=200.0, thickness=40.0, headroom=100.0)
    wafer = substrate.select_substrate(grid, SILICON, surface=40.0)

    outcome = run_step(
        registry["resist.spin_coat_ideal"],
        wafer,
        {"thickness": 900.0},
        library=library,
        domain=domain.DomainPolicy(cap=300.0),
    )

    assert not outcome.ok
    assert outcome.domain.capped
    message = "\n".join(outcome.logs)
    assert "Raising the cap" in message and "MB of RAM per revision" in message


# -- E7: etching through says so ----------------------------------------------


def test_etching_through_the_substrate_says_so_rather_than_computing_something(
        library, registry
) -> None:
    """The DoD's fourth sentence. B2 turns this into a via; the data is already right."""
    grid = cross_section_grid(width=200.0, thickness=60.0, headroom=200.0)
    spec = SubstrateSpec(
        material=SILICON, form_factor=substrate.CHIP,
        thickness=60.0, size_x=10.0 * MM, size_y=10.0 * MM,
    )
    chip = substrate.select_substrate(grid, SILICON, surface=60.0, spec=spec)

    assert etched_depth(chip) == pytest.approx(0.0)

    outcome = run_step(
        registry["etch.icp_fluorine"], chip, {"duration": 150.0}, library=library
    )

    assert not outcome.ok
    assert any("etched through" in failure for failure in outcome.report.failures)
    assert any("60.0 nm" in failure for failure in outcome.report.failures)


def test_a_substrate_nobody_described_is_not_measured_against_an_invented_thickness(
        library, registry
) -> None:
    """No metadata, no verdict — the same rule `semi_infinite` states out loud."""
    grid = cross_section_grid(width=200.0, thickness=60.0, headroom=200.0)
    plain = substrate.select_substrate(grid, SILICON, surface=60.0)

    assert etched_depth(plain) is None
    assert through_etched(plain) is None


def test_the_deepest_column_is_what_counts_not_the_average(library, registry) -> None:
    """A trench is what eats through a wafer, and it is deeper than the mean.

    A masked etch leaves the substrate untouched under the mask and takes it down
    in the open. Averaging the two would say a wafer half-etched to 100 nm has
    gone 50 — and a wafer is not breached on average.
    """
    grid = cross_section_grid(width=240.0, thickness=60.0, headroom=200.0)
    spec = SubstrateSpec(material=SILICON, thickness=0.5 * MM, diameter=100.0 * MM)
    wafer = substrate.select_substrate(grid, SILICON, surface=60.0, spec=spec)
    masked = commit_gate.commit(
        ctor.add_material(wafer, CHROME, ctor.box(grid, [60.0, 0.0], [80.0, 120.0]))
    ).structure

    outcome = run_step(
        registry["etch.icp_fluorine"], masked, {"duration": 60.0}, library=library
    )

    inside = outcome.structure.phi_of(SILICON) <= 0.0
    grid_after = outcome.structure.grid
    tops = grid_after.origin[0] + grid_after.spacing * np.max(
        np.where(inside, np.arange(grid_after.shape[0])[:, None], -1), axis=0
    )
    deepest = 60.0 - float(np.min(tops))
    mean = 60.0 - float(np.mean(tops))

    assert etched_depth(outcome.structure) == pytest.approx(deepest)
    assert deepest > mean + 5.0  # the mask half really is untouched


# -- the metadata carrier -----------------------------------------------------


def test_metadata_survives_every_step_that_does_not_set_it(library, registry) -> None:
    """A fact about the sample is not invalidated by geometry moving.

    The reason it is on the `Structure` and not on the `Revision`: the step that
    has to refuse to etch through the wafer is handed a structure and nothing
    else.
    """
    grid = cross_section_grid(width=240.0, thickness=40.0, headroom=200.0)
    wafer = substrate.select_substrate(
        grid, SILICON, surface=40.0,
        spec=SubstrateSpec(material=SILICON, thickness=0.525 * MM, diameter=100.0 * MM),
    )

    coated = run_step(registry["resist.spin_coat"], wafer, {}, library=library)
    etched = run_step(registry["etch.rie_oxygen"], coated.structure, {"duration": 5.0},
                      library=library)

    assert etched.structure.meta(substrate.THICKNESS_KEY) == pytest.approx(0.525 * MM)
    assert etched.structure.meta(substrate.MATERIAL_KEY) == str(SILICON)


def test_metadata_takes_scalars_only_so_the_exchange_format_needs_no_encoder() -> None:
    grid = cross_section_grid(width=100.0, thickness=20.0, headroom=40.0)

    with pytest.raises(ValueError, match="only JSON scalars"):
        Structure(grid).with_metadata(bad=np.zeros(3))
    with pytest.raises(ValueError, match="non-empty string"):
        Structure(grid, metadata={"  ": 1.0})


# -- the resize and the replay (handoff trap 3) -------------------------------


def _growing_recipe(grid):
    """A recipe whose coat does not fit, so the domain has to move to hold it."""
    from nanofab_v3.runtime.run import Recipe, RecipeStep

    return Recipe(
        grid=grid,
        recipe_id="grows",
        steps=(
            RecipeStep("substrate.select", {"material": str(SILICON), "surface": 40.0}),
            RecipeStep("resist.spin_coat", {"spin_speed": 1000.0}),
        ),
    )


def test_a_chain_that_resized_replays_to_the_same_sample(library, registry) -> None:
    """Trap 3 of the handoff: a resize has to stay deterministic or the cache rots.

    Replay is the cache's fallback *and* the mechanism for a new wafer position
    (ADR-0004), so "run it again and get the same thing" is not a nicety here —
    a chain that grew its domain differently on the second run would hand a
    position a different sample than its neighbour.
    """
    from nanofab_v3.runtime.replay import run_recipe

    recipe = _growing_recipe(cross_section_grid(width=240.0, thickness=40.0, headroom=100.0))

    first = run_recipe(recipe, registry=registry, library=library)
    second = run_recipe(recipe, registry=registry, library=library)

    assert first[-1].structure.grid.shape[0] > recipe.grid.shape[0]  # it really grew
    assert first[-1].structure.grid == second[-1].structure.grid
    for material in first[-1].structure.materials:
        assert np.array_equal(
            np.asarray(first[-1].structure.phi_of(material)),
            np.asarray(second[-1].structure.phi_of(material)),
        )


def test_a_resized_revision_survives_the_exchange_format(library, registry, tmp_path) -> None:
    """The grid is stored per revision, so revisions of different sizes round-trip.

    Worth pinning because the handoff expected this to be where M7 met
    resistance: `io/manifest.py` writes a grid into every revision's manifest and
    reads it back from there, and nothing in the package ever compared one
    revision's grid to another's. The trap was not there.
    """
    from nanofab_v3.io.exchange import load_chain, save_chain
    from nanofab_v3.runtime.replay import run_recipe

    chain = run_recipe(
        _growing_recipe(cross_section_grid(width=240.0, thickness=40.0, headroom=100.0)),
        registry=registry,
        library=library,
    )
    save_chain(tmp_path / "grown", chain)
    reloaded = load_chain(tmp_path / "grown")

    assert reloaded[0].structure.grid != reloaded[1].structure.grid  # two sizes, one chain
    assert reloaded[1].structure.grid == chain[1].structure.grid
    assert reloaded[1].structure.meta(substrate.SURFACE_KEY) == chain[1].structure.meta(
        substrate.SURFACE_KEY
    )


def test_two_wafer_positions_of_a_growing_recipe_agree(library, registry) -> None:
    """The domain policy is per `Run`, so one wafer cannot come out in two sizes."""
    from nanofab_v3.runtime.replay import Run

    run = Run(
        _growing_recipe(cross_section_grid(width=240.0, thickness=40.0, headroom=100.0)),
        registry=registry,
        library=library,
        positions=[(0.0, 0.0), (30.0, 0.0)],
    )

    centre = run.chain((0.0, 0.0))
    edge = run.chain((30.0, 0.0))

    assert centre[-1].structure.grid == edge[-1].structure.grid
