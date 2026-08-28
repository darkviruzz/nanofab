"""M11's Qt-free live-preview and material-identity contracts."""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3 import Grid, Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.materials import CHROME, ION_BEAM, SILICON, didactic_library
from nanofab_v3.processes.rates import release_maps
from nanofab_v3.ui.preview import build_step_preview


@pytest.fixture
def sample(grid_2d: Grid) -> Structure:
    return ctor.add_material(
        Structure(grid_2d),
        SILICON,
        ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(60.0, 0.0)),
    )


def test_ion_beam_preview_uses_rate_duration_and_scale(sample: Structure) -> None:
    preview = build_step_preview(
        sample,
        "etch.ion_beam",
        {"duration": 120.0, "scale": 1.25, "angle": 0.0, "divergence": 3.0},
        didactic_library(),
    )

    assert preview.physical_length_nm == pytest.approx(0.2333 * 120.0 * 1.25)
    assert preview.arrows
    assert all(arrow.length_nm == preview.physical_length_nm for arrow in preview.arrows)


def test_sub_five_pixel_preview_reports_why_it_has_no_arrow(sample: Structure) -> None:
    preview = build_step_preview(
        sample,
        "etch.ion_beam",
        {"duration": 1.0, "scale": 1.0},
        didactic_library(),
        pixels_per_nm=20.0,
    )

    assert not preview.arrows
    assert preview.physical_length_nm == pytest.approx(0.2333)
    assert "4.67 px" in preview.note


def test_release_fields_keep_each_sputtered_material_separate(sample: Structure) -> None:
    structure = ctor.add_material(
        sample,
        CHROME,
        ctor.box(sample.grid, lower=(60.0, 120.0), upper=(80.0, 180.0)),
    )
    fields = release_maps(didactic_library(), structure, ION_BEAM)

    assert set(fields) == {SILICON, CHROME}
    owner = structure.nearest_material_index
    for index, material in enumerate(structure.materials):
        assert np.all(fields[material][owner != index] == 0.0)
        assert float(fields[material][owner == index].max()) > 0.0
