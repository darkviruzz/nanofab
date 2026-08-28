"""The resize itself: what it preserves, what it pads with, where it stops (M7).

`kernel.domain` is the one function that changes a domain's shape (roadmap E5),
and backlog B1 — several stacked sub-domains following the front — is built on
it. So what is asserted here is the arithmetic rather than the behaviour: the
behaviour an operator notices is `test_substrate_domain.py`'s.

The property everything else rests on is that **a resize is not a change to the
sample**. It moves the picture frame. If growing and shrinking could move an
interface by half a cell, every measurement in the acceptance scenarios would
depend on how deep the etch before it happened to be.
"""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3.kernel import domain
from nanofab_v3.kernel import measures
from nanofab_v3.materials import SILICON
from nanofab_v3.model.field import FieldKey
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes import lithography, substrate


@pytest.fixture
def wafer() -> Structure:
    grid = substrate.cross_section_grid(width=240.0, thickness=40.0, headroom=200.0)
    return substrate.select_substrate(grid, SILICON, surface=40.0)


def _surface_of(structure: Structure, material: str, column: int = 100) -> float:
    inside = structure.phi_of(material)[:, column] <= 0.0
    grid = structure.grid
    return grid.origin[0] + grid.spacing * float(np.max(np.flatnonzero(inside)))


# -- what a resize preserves --------------------------------------------------


def test_growing_moves_the_frame_and_not_the_sample(wafer: Structure) -> None:
    """The property every measurement downstream depends on."""
    before = _surface_of(wafer, SILICON)
    area = measures.solid_measure(wafer)

    grown = domain.resize(wafer, below=30, above=20)

    assert grown.grid.shape[0] == wafer.grid.shape[0] + 50
    assert grown.grid.origin[0] == pytest.approx(wafer.grid.origin[0] - 30.0)
    assert grown.grid.origin[1] == wafer.grid.origin[1]  # no lateral growth (E6)
    assert _surface_of(grown, SILICON) == pytest.approx(before)
    # 30 more rows of solid substrate below, and nothing else changed.
    assert measures.solid_measure(grown) == pytest.approx(
        area + 30 * wafer.grid.spacing * wafer.grid.shape[1] * wafer.grid.spacing
    )


def test_the_offset_rides_on_the_origin(wafer: Structure) -> None:
    """Trap 4 of the handoff: `Grid.origin` is the natural carrier of the shift.

    Rewriting coordinates everywhere else would be the expensive way, and it is
    also the way that makes B1's per-sub-domain origins impossible later.
    """
    grown = domain.resize(wafer, below=64)

    assert grown.grid.origin[0] == pytest.approx(-64.0)
    assert grown.grid.extent(0)[1] == pytest.approx(wafer.grid.extent(0)[1])


def test_growing_and_shrinking_back_is_exact(wafer: Structure) -> None:
    """Not "close": the same array. A resize that drifted would drift every step."""
    round_trip = domain.resize(domain.resize(wafer, below=30, above=20), below=-30, above=-20)

    assert round_trip.grid == wafer.grid
    for material in wafer.materials:
        assert np.array_equal(round_trip.phi_of(material), wafer.phi_of(material))


def test_a_grown_phi_is_still_a_distance_function(wafer: Structure) -> None:
    """Why `phi` is continued linearly and not replicated.

    Reinitialisation runs in a five-cell band around the front (plan §17.4) and
    the rows being added are as far from the front as rows in this domain get, so
    nothing downstream would repair a flat pad — it would simply be a field whose
    gradient is zero over a third of the domain.
    """
    grown = domain.resize(wafer, below=40, above=40)

    column = grown.phi_of(SILICON)[:, 120]
    steps = np.abs(np.diff(column))

    assert np.allclose(steps, grown.grid.spacing)


def test_a_field_repeats_its_edge_row_because_it_is_not_a_distance(wafer: Structure) -> None:
    """The other padding rule. Dose does not increase because you looked further up."""
    key = FieldKey("dose", SILICON)
    values = wafer.grid.zeros(dtype=np.float32)
    values[:] = 7.0
    with_field = wafer.with_field(key, values)

    grown = domain.resize(with_field, above=16)

    assert grown.field(key).shape == grown.grid.shape
    assert np.all(grown.field(key) == 7.0)


def test_metadata_comes_along(wafer: Structure) -> None:
    """A wafer does not get thinner because the window around it got taller."""
    described = wafer.with_metadata(**{"substrate.thickness": 525_000.0})

    assert domain.resize(described, below=8).meta("substrate.thickness") == 525_000.0


def test_a_resize_that_would_empty_the_domain_is_refused(wafer: Structure) -> None:
    with pytest.raises(ValueError, match="would leave"):
        domain.resize(wafer, below=-wafer.grid.shape[0], above=-1)


# -- the two ends are two questions -------------------------------------------


def test_headroom_counts_empty_rows_and_underroom_counts_uniform_ones(
    wafer: Structure,
) -> None:
    """The asymmetry the module exists to get right — see its docstring."""
    assert domain.underroom(wafer) == 41  # rows 0..40 are all substrate
    assert domain.headroom(wafer) == 200  # rows 41..240 are all empty


def test_a_coat_that_fills_the_domain_has_no_headroom_however_uniform_it_is(
    wafer: Structure,
) -> None:
    """The bug a symmetric rule would have.

    A resist coat to the ceiling makes every upper row identical to the top row.
    "Count rows that look like the edge" would call that plenty of headroom — and
    it is the exact case the growth exists for.
    """
    filled = lithography.spin_coat(wafer, "resist", thickness=250.0)

    assert domain.headroom(filled) == 0
    assert domain.out_of_room(filled) == (False, True)


def test_an_empty_domain_decides_nothing(wafer: Structure) -> None:
    """There is no sample yet to size a window around, so nothing is resized."""
    empty = Structure(wafer.grid)

    assert domain.out_of_room(empty) == (False, False)
    assert not domain.plan(empty).moved


# -- the policy ---------------------------------------------------------------


def test_the_margin_is_a_trigger_and_not_a_target(wafer: Structure) -> None:
    """A policy that normalised every domain would replace the one somebody chose.

    40 nm of substrate under 200 nm of headroom is what this recipe asked for,
    and it comes back untouched.
    """
    assert not domain.plan(wafer).moved


def test_a_domain_with_far_too_much_room_gives_some_back(wafer: Structure) -> None:
    """E5's "auch schrumpfen, wenn groß und leer"."""
    roomy = domain.resize(wafer, above=2000)

    change = domain.plan(roomy)

    assert change.above < 0
    assert domain.fit(roomy)[0].grid.shape[0] < roomy.grid.shape[0]


def test_shrinking_has_hysteresis_so_a_front_cannot_thrash_the_allocator(
    wafer: Structure,
) -> None:
    """Grow below `margin`, give back only above `margin + slack` — never both."""
    policy = domain.DomainPolicy()
    spacing = wafer.grid.spacing
    threshold = policy.rows(wafer.grid, policy.margin) + policy.rows(wafer.grid, policy.slack)

    # Just under the shrink threshold: quiet, roomy, and deliberately left alone.
    just_under = domain.resize(wafer, above=threshold - domain.headroom(wafer) - 4)
    assert domain.headroom(just_under) == threshold - 4
    assert not domain.plan(just_under, policy).moved

    # A little over it, and the room comes back.
    just_over = domain.resize(just_under, above=policy.rows(wafer.grid, policy.chunk) + 8)
    assert domain.plan(just_over, policy).above < 0
    assert spacing > 0.0


def test_the_cap_stops_growth_and_says_by_how_much_it_fell_short() -> None:
    """E5's 5 µm ceiling — the point where the model stops being able to draw."""
    grid = substrate.cross_section_grid(width=100.0, thickness=40.0, headroom=4900.0)

    change = domain.extra_room(grid, below=True, above=True)

    assert change.capped
    assert change.wanted > 0
    assert grid.shape[0] + change.rows <= int(5000.0 / grid.spacing) + 1


def test_the_estimate_is_ram_exactly_and_disk_as_a_range() -> None:
    """Plan §20.3 measured 6x to 500x across one chain, so one disk number is a fiction."""
    grid = substrate.cross_section_grid(width=1200.0, thickness=1000.0, headroom=1000.0)

    estimate = domain.memory_estimate(grid, arrays=5)

    assert estimate.bytes_per_revision == grid.size * 5 * 4
    assert "MB of RAM per revision" in estimate.describe()
    assert "6x to 500x less on disk" in estimate.describe()


def test_a_policy_with_a_cap_below_its_floor_is_refused() -> None:
    with pytest.raises(ValueError, match="below floor"):
        domain.DomainPolicy(cap=100.0, floor=200.0)
