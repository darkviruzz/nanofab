"""Two pictures of one exposure, and the difference between them (M8, E9).

Roadmap E9 splits lithography into a *preview* and a *result* and says the
didactically interesting part is the difference:

- the **light preview** is geometry. Straight rays down through the open parts of
  the mask, computed from the parameters sitting in the form, available before
  the step runs. No dose, no blur, no absorption, no resist.
- the **`exposed` and `dose` overlays** are what the simulation produced, with
  the aerial image's blur and the Beer-Lambert depth falloff in them. They colour
  **always**, because roadmap §0 found these fields existed and were rendered
  nowhere — which made the whole ideal/physical split invisible in the
  application that exists to teach it.

A student who expects the second to look like the first has just learned what an
aerial image is, which is why they are two objects and not one "exposure view".
"""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3.materials import RESIST, SILICON, didactic_library
from nanofab_v3.processes import lithography, substrate
from nanofab_v3.ui import scene


@pytest.fixture
def library():
    return didactic_library()


@pytest.fixture
def coated():
    grid = substrate.cross_section_grid(width=300.0, thickness=40.0, headroom=200.0)
    wafer = substrate.select_substrate(grid, SILICON, surface=40.0)
    return lithography.spin_coat(wafer, RESIST, thickness=80.0)


@pytest.fixture
def window_pattern(coated):
    return lithography.windows(coated.grid, [(100.0, 200.0)])


# -- the result: fields that were stored and never drawn ----------------------


def test_the_exposed_field_now_has_a_picture(coated, window_pattern, library) -> None:
    """Roadmap §0's finding, closed: the field existed and `OVERLAY_KINDS` did not
    contain it, so the ideal tier's whole output was invisible."""
    exposed = lithography.expose_ideal(coated, RESIST, window_pattern)

    snapshot = scene.build(exposed, library=library, overlays=["exposed"])

    assert "exposed" in scene.OVERLAY_KINDS
    overlay = snapshot.overlays[0]
    assert overlay.kind == "exposed" and overlay.outlines
    assert "cells the pattern struck" in overlay.note


def test_the_latent_image_is_clipped_to_the_resist_that_holds_it(
    coated, window_pattern, library
) -> None:
    """`expose_ideal` writes over the whole grid on purpose — the gate's scoping
    rule is what keeps the field meaningful — but a picture of a latent image
    floating in empty space above the resist is a picture of nothing.

    The window is 100 nm wide and the resist 80 nm thick, so a correct overlay
    covers about 8000 cells and an unclipped one three times that.
    """
    exposed = lithography.expose_ideal(coated, RESIST, window_pattern)

    overlay = scene.build(exposed, library=library, overlays=["exposed"]).overlays[0]
    struck = int(overlay.note.split()[0])

    assert 7000 < struck < 9000


def test_the_dose_overlay_is_iso_contours_of_the_aerial_image(
    coated, window_pattern, library
) -> None:
    """Fractions of the peak, not absolute mJ/cm^2: what a reader is looking for
    is the shape, and where it crosses a clearing dose the renderer deliberately
    does not know about (plan §10 — this module holds no physics)."""
    dosed = lithography.expose_dose(
        coated, RESIST, window_pattern, dose=150.0, blur=8.0, library=library
    )

    overlay = scene.build(dosed, library=library, overlays=["dose"]).overlays[0]

    assert overlay.kind == "dose"
    assert len(overlay.outlines) >= len(scene.DOSE_LEVELS) - 1
    assert "150 mJ/cm^2" in overlay.note


def test_a_structure_with_no_latent_image_gets_no_empty_legend_entry(
    coated, library
) -> None:
    """An overlay that says nothing is worse than no overlay: it looks like a result."""
    snapshot = scene.build(coated, library=library, overlays=["exposed", "dose"])

    assert snapshot.overlays == ()


# -- the preview: geometry, from the parameters, before the step --------------


def test_the_preview_draws_a_ray_through_every_opening(coated, library) -> None:
    grating = lithography.grating(coated.grid, period=100.0, duty=0.5)

    preview = scene.light_preview(coated, grating, rays_per_opening=3)

    assert bool(preview)
    assert preview.segments.shape[1:] == (2, 2)
    assert "no dose, no blur, no absorption" in preview.note
    # Four openings intersect a 300 nm domain at a 100 nm period, and the last of
    # them is one column wide at the very edge — so it gets one ray, not three.
    # Three rays on one column would be a picture claiming three times the light.
    columns = preview.segments[:, 0, 1]
    assert len(columns) == len(set(columns))
    assert 3 * 3 <= len(columns) <= 4 * 3


def test_a_ray_stops_where_it_would_strike_the_sample(coated, window_pattern) -> None:
    """Drawing it through the resist would say the light goes through it."""
    preview = scene.light_preview(coated, window_pattern, rays_per_opening=1)

    (start, end), = preview.segments
    ceiling = coated.grid.extent(0)[1]

    assert start[0] == pytest.approx(ceiling)
    assert end[0] == pytest.approx(120.0, abs=1.0)  # 40 nm wafer + 80 nm resist
    assert start[1] == end[1]  # straight down


def test_a_closed_mask_previews_nothing_and_says_so(coated) -> None:
    closed = np.full(coated.grid.shape, 1.0, dtype=float)

    preview = scene.light_preview(coated, closed)

    assert not preview
    assert "closed everywhere" in preview.note


def test_the_preview_is_the_step_s_own_pattern_and_not_a_second_reading(
    coated,
) -> None:
    """One definition of what the mask is. Two would drift the first time a
    parameter was added, and the drift would look like an optical effect."""
    params = {"pattern": "grating", "period": 120.0, "duty": 0.4, "phase": 0.0,
              "center": 0.0, "width": 0.0}

    from_step = lithography.pattern_from_params(coated.grid, params)
    directly = lithography.grating(coated.grid, period=120.0, duty=0.4, phase=0.0)

    assert np.array_equal(from_step, directly)


# -- the difference, which is the point ---------------------------------------


def test_the_preview_edge_is_sharp_where_the_simulated_dose_is_not(
    coated, window_pattern, library
) -> None:
    """E9's sentence, as a measurement.

    The preview says light falls in a 100 nm window and nowhere else. The
    simulated dose spreads past that edge by the aerial image's blur and falls
    off with depth. Neither is wrong; the gap between them is the lesson.
    """
    dosed = lithography.expose_dose(
        coated, RESIST, window_pattern, dose=150.0, blur=12.0, library=library
    )
    dose = np.asarray(dosed.field(("dose", RESIST)))
    grid = coated.grid

    lit_columns = np.flatnonzero(np.any(np.asarray(window_pattern) <= 0.0, axis=0))
    dosed_columns = np.flatnonzero(np.any(dose > 0.05 * dose.max(), axis=0))

    assert len(dosed_columns) > len(lit_columns) + 10  # the blur reaches outside
    # ... and inside the window the dose is not flat, because of the depth term.
    column = dose[:, int(np.mean(lit_columns))]
    inside = column[column > 0.0]
    assert inside.max() > inside.min() * 1.05
    assert grid.ndim == 2


# -- the shell ----------------------------------------------------------------


@pytest.fixture(scope="module")
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_result_colours_without_being_asked_and_the_preview_is_a_toggle(
    qt_app,
) -> None:
    """E9's asymmetry, at the shell: one is always on, the other is a choice."""
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    window.session.run("substrate.select", {"material": str(SILICON), "surface": 40.0})
    window.session.run("resist.spin_coat", {"spin_speed": 3000.0})
    window.steps.select_step("litho.expose_ideal")
    window._on_step_chosen("litho.expose_ideal")
    window._refresh_all()

    assert window._overlays["exposed"].isChecked()
    assert window._overlays["dose"].isChecked()
    assert not window._overlays["reachable"].isChecked()  # a predicate costs, so it waits
    assert not window.light_box.isChecked()

    window.light_box.setChecked(True)
    window._refresh_canvas()
    assert bool(window.canvas.scene.light)

    window.session.run(
        "litho.expose_ideal", {"material": str(RESIST), "center": 150.0, "width": 100.0}
    )
    window._refresh_all()
    assert [overlay.kind for overlay in window.canvas.scene.overlays] == ["exposed"]


def test_the_preview_is_only_offered_while_an_exposure_step_is_selected(qt_app) -> None:
    """Asking any other step for mask parameters would be inventing a mask."""
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    window.session.run("substrate.select", {"material": str(SILICON), "surface": 40.0})
    window.light_box.setChecked(True)
    window.steps.select_step("etch.wet")
    window._on_step_chosen("etch.wet")
    window._refresh_canvas()

    assert not bool(window.canvas.scene.light)
