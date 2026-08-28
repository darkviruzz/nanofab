"""M11's Qt-free live-preview and material-identity contracts."""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3 import Grid, Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.materials import CHROME, ION_BEAM, SILICON, didactic_library
from nanofab_v3.processes.rates import release_maps
from nanofab_v3.ui.preview import build_step_preview
from nanofab_v3.ui.scene import PreviewArrow


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


def test_arrow_tip_is_a_physical_nm_length_with_a_dimensionless_scale() -> None:
    arrow = PreviewArrow((20.0, 30.0), (0.0, 2.0), 10.0, "#ffffff")

    assert arrow.tip(1.0) == pytest.approx((20.0, 40.0))
    assert arrow.tip(0.5) == pytest.approx((20.0, 35.0))


def test_zero_preview_scale_disables_growth_and_redeposit_arrows(sample: Structure) -> None:
    preview = build_step_preview(
        sample,
        "etch.ion_beam",
        {"duration": 120.0, "scale": 1.25, "redeposition_yield": 0.5},
        didactic_library(),
        thickness_scale=0.0,
    )

    assert not preview
    assert preview.thickness_scale == 0.0


def test_arrows_share_at_most_twenty_reachable_surface_anchors_and_local_rates(
        sample: Structure,
) -> None:
    structure = ctor.add_material(
        sample,
        CHROME,
        ctor.box(sample.grid, lower=(60.0, 120.0), upper=(80.0, 180.0)),
    )
    library = didactic_library()
    duration, yield_fraction = 10.0, 0.25
    preview = build_step_preview(
        structure,
        "etch.ion_beam",
        {
            "duration": duration,
            "scale": 1.0,
            "angle": 0.0,
            "divergence": 3.0,
            "redeposition_yield": yield_fraction,
        },
        library,
    )

    starts = {arrow.start for arrow in preview.arrows}
    assert 1 < len(starts) <= 20
    assert all(sum(arrow.start == start for arrow in preview.arrows) == 6 for start in starts)
    seen = set()
    for arrow in preview.arrows:
        cell = np.clip(
            np.round((np.asarray(arrow.start) - structure.grid.origin) / structure.grid.spacing).astype(int),
            0,
            np.asarray(structure.grid.shape) - 1,
        )
        material = structure.materials[
            int(structure.nearest_material_index[cell[0], cell[1]])
        ]
        seen.add(material)
        base = library[material].rate_for(ION_BEAM) * duration
        assert arrow.length_nm == pytest.approx(base * (yield_fraction if arrow.dashed else 1.0))
    assert seen == {SILICON, CHROME}


def test_particle_preview_capacity_comes_from_domain_width_and_maximum_diameter(
        sample: Structure,
) -> None:
    count, radius, spread = 100, 10.0, 0.5
    preview = build_step_preview(
        sample,
        "particle.seed",
        {"count": count, "radius": radius, "radius_spread": spread},
        didactic_library(),
    )
    right0, right1 = sample.grid.extent(1)
    expected = int(0.9 * (right1 - right0) / (2.0 * radius * (1.0 + spread)))

    assert len({circle.center[1] for circle in preview.circles}) == expected
    assert len(preview.circles) == 3 * expected
    assert preview.note == f"{expected} of {count} particle positions shown"

    oversized = build_step_preview(
        sample,
        "particle.seed",
        {"count": 1, "radius": right1 - right0, "radius_spread": 0.0},
        didactic_library(),
    )
    assert oversized.circles == ()
    assert oversized.note == "0 of 1 particle positions shown"


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
