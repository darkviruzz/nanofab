"""The exposure picture and the lithography defaults (roadmap E28, E33).

Two decisions with one subject: what an exposure *is* in this model, and how a
reader sees it. E33 is about the numbers a mask is described with; E28 is about
what the latent image looks like once it exists.
"""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3.processes import lithography
from nanofab_v3.ui import scene
from nanofab_v3.ui.session import Session


@pytest.fixture()
def coated():
    session = Session()
    session.run("substrate.select", {"preset": "wafer_fs_100"})
    session.run("resist.spin_coat", {"material": "resist", "thickness": 90.0})
    return session


# -- E33: the defaults come from the domain -----------------------------------


def test_a_window_with_no_centre_lands_in_the_middle_of_the_domain(coated):
    """`0` means "from the domain" — the third instance of the convention.

    The old default put a window at x = 0, i.e. against the left wall. Nobody
    would type that on purpose, which is what makes it a bad default rather than
    a neutral one.
    """
    grid = coated.structure.grid
    width = (grid.shape[-1] - 1) * grid.spacing
    resolved = lithography.domain_defaults(
        grid, {"center": 0.0, "grating_center": 0.0, "period": 0.0}
    )
    assert resolved["center"] == pytest.approx(grid.origin[-1] + 0.5 * width)
    assert resolved["period"] == pytest.approx(width / 3.0)


def test_a_stated_value_is_never_replaced_by_the_domain(coated):
    resolved = lithography.domain_defaults(
        coated.structure.grid, {"center": 25.0, "grating_center": 30.0, "period": 40.0}
    )
    assert resolved == {}


def test_grating_center_places_a_line_where_phase_placed_an_edge(coated):
    """The rename is the substance, not the spelling (E33).

    `phase` named where the waveform started, which coincides with the middle of
    a line only at duty 1.0 — so it could not answer "put a line here", which is
    the question anybody actually has.
    """
    grid = coated.structure.grid
    pattern = lithography.pattern_from_params(
        grid,
        {
            "pattern": "grating",
            "period": 120.0,
            "duty": 0.5,
            "grating_center": 150.0,
            "center": 0.0,
            "width": 0.0,
        },
    )
    open_columns = np.flatnonzero(pattern[0] > 0) * grid.spacing + grid.origin[-1]
    # The stripe containing 150 nm is centred on it, to within a cell.
    stripe = open_columns[np.abs(open_columns - 150.0) < 60.0]
    assert 0.5 * (stripe.min() + stripe.max()) == pytest.approx(150.0, abs=grid.spacing)


def test_no_step_takes_a_parameter_called_phase_any_more():
    from nanofab_v3.processes.registry import builtin_registry

    registry = builtin_registry()
    for step_id in registry.steps:
        names = {spec.name for spec in registry[step_id].parameter_schema()}
        assert "phase" not in names, step_id


# -- E33: two exposures are two exposures -------------------------------------


def test_two_dose_exposures_add_because_energy_adds(coated):
    """Neither clears the resist alone; together they do. That is a double exposure."""
    from nanofab_v3.processes.lithography import DOSE

    first = coated.run("litho.expose_dose", {"material": "resist", "dose": 40.0})
    second = coated.run("litho.expose_dose", {"material": "resist", "dose": 40.0})

    peak_first = float(np.asarray(first.structure.field(DOSE.key("resist"))).max())
    peak_second = float(np.asarray(second.structure.field(DOSE.key("resist"))).max())
    assert peak_second == pytest.approx(2.0 * peak_first)
    assert any("doses add" in line for line in second.logs)


def test_two_ideal_exposures_or_and_the_log_says_what_that_costs(coated):
    """Information, not a warning — the honesty `threshold_dose` already practises."""
    from nanofab_v3.processes.lithography import EXPOSED

    coated.run(
        "litho.expose_ideal",
        {"material": "resist", "pattern": "window", "center": 100.0, "width": 60.0},
    )
    second = coated.run(
        "litho.expose_ideal",
        {"material": "resist", "pattern": "window", "center": 220.0, "width": 60.0},
    )

    struck = np.asarray(second.structure.field(EXPOSED.key("resist"))) != 0
    columns = np.flatnonzero(struck.any(axis=0)) * second.structure.grid.spacing
    assert columns.min() < 100.0 and columns.max() > 200.0  # both windows survive
    assert any("OR-ed" in line for line in second.logs)


# -- E28: the picture ---------------------------------------------------------


def test_exposed_is_a_flat_area_and_not_a_contour(coated):
    """A binary field has nothing to grade, and an outline of it reads as a shape."""
    coated.run("litho.expose_ideal", {"material": "resist", "pattern": "window"})
    overlay = _overlay(coated, "exposed")

    assert overlay.filled is True
    assert len(overlay.bands) == 1
    assert overlay.bands[0].outlines


def test_dose_is_banded_against_the_resists_clearing_dose(coated):
    """E28's scale is D0, not the peak — a scale that moves is not a scale."""
    coated.run("litho.expose_dose", {"material": "resist", "dose": 250.0})
    overlay = _overlay(coated, "dose")

    assert "clearing dose of resist" in overlay.note
    assert len(overlay.bands) >= 3
    labels = [band.label for band in overlay.bands]
    assert labels[0].endswith("D0") and labels[-1].startswith("over")
    # Darker means more, always, so the picture is readable without the legend.
    shades = [band.shade for band in overlay.bands]
    assert shades == sorted(shades)


def test_the_only_line_in_the_dose_picture_is_the_clearing_dose(coated):
    """It is the one contour that predicts where the developer will cut."""
    coated.run("litho.expose_dose", {"material": "resist", "dose": 250.0})
    overlay = _overlay(coated, "dose")

    assert overlay.outlines
    assert "the line is D0" in overlay.note


def test_without_a_clearing_dose_the_picture_says_it_is_relative(coated):
    """A relative scale is worse than an absolute one and better than no picture."""
    library = coated.library
    stripped = scene.build(
        _dosed(coated).structure,
        library=type(library)(
            {
                key: entry
                for key, entry in library.entries.items()
                if entry.develop is None
            }
        ),
        overlays=["dose"],
    )
    note = next(o.note for o in stripped.overlays if o.kind == "dose")
    assert "no clearing dose in the library" in note


def _dosed(session):
    return session.run("litho.expose_dose", {"material": "resist", "dose": 250.0})


def _overlay(session, kind):
    snapshot = session.scene(overlays=[kind])
    return next(overlay for overlay in snapshot.overlays if overlay.kind == kind)
