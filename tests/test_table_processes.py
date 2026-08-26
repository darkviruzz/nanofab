"""The eleven processes of roadmap §3's table, as steps that run (milestone M6).

The table is the didactic payload of this milestone, and its DoD is that every
row is *callable*: an operator picks a chemistry from the step list, gives it a
time, and gets the profile that chemistry produces. What is asserted here is
therefore behaviour rather than numbers — the numbers are pinned in
`test_material_files.py`, where they can be read next to the table.

Three properties carry the whole table, and each one is a mistake it would be
easy to make instead:

- a **selective** step attacks what its column names and leaves the rest, which
  is what makes a hard mask a hard mask without anything modelling one;
- an **isotropic** step undercuts a mask by as much as it etches down (the
  table's "horizontal = vertical"), and a **directional** one does not (its
  "vertical") — from the angular distribution, never from a second rate;
- the timed deposition derives its thickness from the library, so a wrong rate
  shows up as a wrong film rather than as nothing at all.
"""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import gate as commit_gate
from nanofab_v3.materials import (
    CHROME,
    FUSED_SILICA,
    OXIDE,
    RESIST,
    SILICON,
    MaterialLibrary,
    didactic_library,
)
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes import builtin_registry, run_step
from nanofab_v3.processes import lithography, substrate

TABLE_STEPS = (
    "etch.sputter",        # row 1  — sputter etching
    "etch.icp_fluorine",   # row 2  — ICP, fluorine, vertical
    "etch.rie_chlorine",   # row 3  — RIE, chlorine, isotropic
    "etch.rie_oxygen",     # row 4  — RIE, oxygen, isotropic
    "etch.wet_cr",         # row 5  — chromium etchant
    "etch.wet_oxide",      # row 6  — buffered oxide etch
    "deposit.sputter_rate",  # rows 7-9 — one step, the material is the row
    "clean.particles",     # row 10 — since M5
    "resist.spin_coat",    # row 11 — the spin curve
)


@pytest.fixture
def library() -> MaterialLibrary:
    return didactic_library()


@pytest.fixture
def chrome_on_glass() -> Structure:
    """The photomask stack the table is written for, in three exposed columns.

    Quartz blank to y = 40; a 20 nm chromium absorber over the left half; 60 nm
    of resist over the left quarter. So column 30 is glass/chromium/resist,
    column 90 is glass/chromium with the chromium bare, and column 200 is bare
    glass — one column per thing a chemistry can be selective about.
    """
    grid = substrate.cross_section_grid(width=240.0, thickness=40.0, headroom=200.0)
    blank = substrate.select_substrate(grid, FUSED_SILICA, surface=40.0)
    with_cr = ctor.add_material(
        blank, CHROME, ctor.box(grid, [40.0, 0.0], [60.0, 120.0])
    )
    resisted = ctor.add_material(
        with_cr, RESIST, ctor.box(grid, [60.0, 0.0], [120.0, 60.0])
    )
    return commit_gate.commit(resisted).structure


def _height_of(structure: Structure, material: str, column: int) -> float:
    """Topmost cell of `material` in one column, in nm; `nan` when it is gone."""
    solid = structure.phi[material][:, column] < 0.0
    rows = np.flatnonzero(solid)
    if rows.size == 0:
        return float("nan")
    return structure.grid.origin[0] + structure.grid.spacing * float(rows.max())


# -- every row is a step ------------------------------------------------------


def test_all_eleven_table_processes_are_registered_steps() -> None:
    """M6's DoD, literally: the table is reachable from the step list."""
    registry = builtin_registry()

    for step_id in TABLE_STEPS:
        assert step_id in registry, step_id


def test_the_didactic_steps_they_sit_beside_are_untouched() -> None:
    """Nothing renamed (roadmap §3): the older ids still answer, at their own rates."""
    registry = builtin_registry()

    for step_id in ("etch.wet", "etch.rie", "etch.ibe", "deposit.sputter"):
        assert step_id in registry, step_id
    assert registry["etch.ibe"].step_id != registry["etch.sputter"].step_id


# -- selectivity: each column attacks what it names ---------------------------


def test_the_chromium_etchant_takes_the_chromium_and_leaves_the_glass(
    chrome_on_glass: Structure, library: MaterialLibrary
) -> None:
    """Row 5, and the reason `wet_etch_cr` is its own class: a bath is selective.

    Two things at once, and the second is free: the etchant takes the *bare*
    chromium at column 90 and leaves the chromium under the resist at column 30
    alone — not because it is a different material, but because the bath cannot
    reach it (plan §4.4).
    """
    before_glass = _height_of(chrome_on_glass, FUSED_SILICA, 200)

    outcome = run_step(
        builtin_registry()["etch.wet_cr"],
        chrome_on_glass,
        {"duration": 1.0},
        library=library,
    )

    assert outcome.ok
    bare = _height_of(outcome.structure, CHROME, 90)
    assert np.isnan(bare) or bare < 60.0 - 10.0
    # `abs=1.5` rather than exact: the reachability gate works on a collar around
    # the front (plan §18.5) and the commit gate reinitialises, so a covered
    # surface can move a cell. 20 nm of chromium against one is the statement.
    assert _height_of(outcome.structure, CHROME, 30) == pytest.approx(60.0, abs=1.5)
    assert _height_of(outcome.structure, FUSED_SILICA, 200) == pytest.approx(before_glass, abs=0.6)


def test_the_oxygen_plasma_strips_the_resist_and_nothing_else(
    chrome_on_glass: Structure, library: MaterialLibrary
) -> None:
    """Row 4. The table gives chromium and fused silica a rate of exactly zero."""
    before_resist = _height_of(chrome_on_glass, RESIST, 30)
    before_cr = _height_of(chrome_on_glass, CHROME, 90)

    outcome = run_step(
        builtin_registry()["etch.rie_oxygen"],
        chrome_on_glass,
        {"duration": 12.0},
        library=library,
    )

    assert outcome.ok
    assert _height_of(outcome.structure, RESIST, 30) < before_resist - 15.0
    assert _height_of(outcome.structure, CHROME, 90) == pytest.approx(before_cr, abs=0.6)


def test_the_fluorine_etch_goes_through_the_glass_and_barely_touches_the_chromium(
    chrome_on_glass: Structure, library: MaterialLibrary
) -> None:
    """Row 2 — a 25:1 selectivity, which is why the chromium is the hard mask."""
    library_entry = library[CHROME]
    glass = library[FUSED_SILICA].rate_for("icp_fluorine")

    assert glass / library_entry.rate_for("icp_fluorine") == pytest.approx(25.0, rel=2e-3)

    outcome = run_step(
        builtin_registry()["etch.icp_fluorine"],
        chrome_on_glass,
        {"duration": 20.0},
        library=library,
    )

    assert outcome.ok
    # Column 200 is bare glass and sinks; the chromium at column 30 barely moves,
    # which is the 25:1 above expressed as a picture.
    assert _height_of(outcome.structure, FUSED_SILICA, 200) < 40.0 - 10.0
    assert _height_of(outcome.structure, CHROME, 30) == pytest.approx(60.0, abs=1.0)


# -- direction: the angular distribution, not a second rate -------------------


def test_horizontal_equals_vertical_undercuts_and_vertical_does_not(
    library: MaterialLibrary
) -> None:
    """Roadmap §3's central schema point, as the one measurement that separates them.

    The table distinguishes "horizontal = vertical" from "vertical" and both are
    a *single* scalar rate in this model. What differs is the flux model the step
    builds, so the same rate table produces an undercut for one and a vertical
    wall for the other — which is exactly the claim, and it would be untestable
    if direction had been stored as a second number.
    """
    grid = substrate.cross_section_grid(width=240.0, thickness=40.0, headroom=200.0)
    wafer = substrate.select_substrate(grid, SILICON, surface=40.0)
    coated = lithography.spin_coat(wafer, OXIDE, thickness=40.0)
    masked = ctor.add_material(coated, CHROME, ctor.box(grid, [80.0, 0.0], [100.0, 120.0]))
    stack = commit_gate.commit(masked).structure

    registry = builtin_registry()
    isotropic = run_step(
        registry["etch.wet_oxide"], stack, {"duration": 1.5}, library=library
    ).structure
    directional = run_step(
        registry["etch.icp_fluorine"], stack, {"duration": 24.0}, library=library
    ).structure

    # 10 nm inside the mask edge (which sits at x = 120 nm), under the mask. The
    # isotropic bath removes 25 nm in 1.5 s and so reaches 22.9 nm down here; the
    # directional one removes 20 nm and reaches none of it.
    under_mask = int(round((120.0 - 10.0) / grid.spacing))
    assert np.isnan(_height_of(isotropic, OXIDE, under_mask)) or _height_of(
        isotropic, OXIDE, under_mask
    ) < 80.0 - 5.0, "an isotropic bath must eat sideways under the mask"
    assert _height_of(directional, OXIDE, under_mask) == pytest.approx(80.0, abs=1.5), (
        "a vertical chemistry must leave what the mask covers"
    )


def test_raising_the_chemical_fraction_turns_the_vertical_etch_into_an_undercutting_one(
    library: MaterialLibrary
) -> None:
    """The parameter is the didactic payload, not a leftover (see the step's help)."""
    grid = substrate.cross_section_grid(width=240.0, thickness=40.0, headroom=200.0)
    wafer = substrate.select_substrate(grid, SILICON, surface=40.0)
    coated = lithography.spin_coat(wafer, OXIDE, thickness=40.0)
    masked = ctor.add_material(coated, CHROME, ctor.box(grid, [80.0, 0.0], [100.0, 120.0]))
    stack = commit_gate.commit(masked).structure
    step = builtin_registry()["etch.icp_fluorine"]
    under_mask = int(round((120.0 - 8.0) / grid.spacing))

    vertical = run_step(step, stack, {"duration": 24.0}, library=library).structure
    chemical = run_step(
        step, stack, {"duration": 24.0, "chemical_fraction": 0.8}, library=library
    ).structure

    assert _height_of(chemical, OXIDE, under_mask) < _height_of(vertical, OXIDE, under_mask)


# -- rows 7-9: the thickness comes from the library ---------------------------


def test_the_timed_sputter_deposition_derives_its_thickness_from_the_rate(
    library: MaterialLibrary
) -> None:
    """Rows 7-9 as the operator states them: a time in, a film out."""
    grid = substrate.cross_section_grid(width=240.0, thickness=40.0, headroom=200.0)
    wafer = substrate.select_substrate(grid, SILICON, surface=40.0)

    outcome = run_step(
        builtin_registry()["deposit.sputter_rate"],
        wafer,
        {"material": str(CHROME), "duration": 120.0},
        library=library,
    )

    # 0.0833 nm/s x 120 s = 10.0 nm, and the step says so rather than assuming it.
    assert outcome.measurements["thickness"].value == pytest.approx(9.996)
    assert outcome.measurements["rate"].value == pytest.approx(0.0833)
    assert CHROME in outcome.structure.materials
    assert _height_of(outcome.structure, CHROME, 120) == pytest.approx(50.0, abs=1.0)


def test_a_target_with_no_sputter_rate_says_so_instead_of_depositing_nothing(
    library: MaterialLibrary
) -> None:
    """E15's rule at the step: a zero rate is "nobody stated one", not "it does not grow"."""
    grid = substrate.cross_section_grid(width=240.0, thickness=40.0, headroom=200.0)
    wafer = substrate.select_substrate(grid, SILICON, surface=40.0)

    with pytest.raises(ValueError, match="nobody stated a rate"):
        run_step(
            builtin_registry()["deposit.sputter_rate"],
            wafer,
            {"material": "titania", "duration": 60.0},
            library=library,
        )
