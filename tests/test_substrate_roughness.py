"""Roughness as a number, and the two presets E30 asked for (roadmap §4 item 7).

The decision this file is about is *where* roughness lives. At 1 nm per cell a
polished wafer's Ra of 0.5 nm is below what the level set can carry and the
reinitialisation would pull it flat within a few sub-steps; an unpolished back
side at Ra ~ 1 um would be taller than the whole domain. So it is metadata, and
the instruments read it — which teaches the right thing rather than hiding the
limitation.
"""

from __future__ import annotations

import pytest

from nanofab_v3.processes.substrate import (
    PRESETS_BY_KEY,
    ROUGHNESS_KEY,
    SEMI_INFINITE,
    SURFACE_KEY,
    SubstrateSpec,
)
from nanofab_v3.ui.session import Session


@pytest.mark.parametrize(
    "preset, roughness, surface",
    [("wafer_fs_100", 0.5, 100.0), ("mask_6025", 0.3, 100.0), ("semi_infinite", 0.0, 50.0)],
)
def test_a_preset_carries_its_roughness_and_where_it_puts_the_surface(
    preset, roughness, surface
):
    metadata = Session().run("substrate.select", {"preset": preset}).structure.metadata
    assert metadata[ROUGHNESS_KEY] == pytest.approx(roughness)
    assert metadata[SURFACE_KEY] == pytest.approx(surface)


def test_semi_infinite_is_now_reachable_from_the_list():
    """It was a form factor with no preset — pickable only by typing it."""
    preset = PRESETS_BY_KEY["semi_infinite"]
    assert preset.form_factor == SEMI_INFINITE
    assert SubstrateSpec.from_preset("semi_infinite").thickness is None


def test_a_stated_roughness_overrides_the_preset_and_zero_means_the_preset():
    """E33's marker, third instance: 0 is "from the preset", like thickness 0."""
    stated = Session().run(
        "substrate.select", {"preset": "wafer_fs_100", "roughness": 4.0}
    )
    assert stated.structure.metadata[ROUGHNESS_KEY] == pytest.approx(4.0)
    default = Session().run("substrate.select", {"preset": "wafer_fs_100"})
    assert default.structure.metadata[ROUGHNESS_KEY] == pytest.approx(0.5)


def test_a_stated_surface_still_wins_over_the_preset():
    revision = Session().run(
        "substrate.select", {"preset": "wafer_fs_100", "surface": 40.0}
    )
    assert revision.structure.metadata[SURFACE_KEY] == pytest.approx(40.0)


def test_the_profilometer_measures_roughness_the_picture_cannot_show():
    """E30's payload. The cross-section is flat; the instrument reads 0.5 nm."""
    session = Session()
    session.run("substrate.select", {"preset": "wafer_fs_100"})
    revision = session.run("inspect.profilometer", {})

    assert revision.measurements["profile_ra"].value == pytest.approx(0.0, abs=1e-9)
    assert revision.measurements["roughness_ra"].value == pytest.approx(0.5)
    assert any("from the substrate" in line for line in revision.logs)


def test_a_substrate_with_no_roughness_reports_the_profile_alone():
    session = Session()
    session.run("substrate.select", {"preset": "semi_infinite"})
    revision = session.run("inspect.profilometer", {})
    assert revision.measurements["roughness_ra"].value == pytest.approx(
        revision.measurements["profile_ra"].value
    )
    assert not any("from the substrate" in line for line in revision.logs)
