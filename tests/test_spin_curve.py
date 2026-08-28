"""The spin curve: thickness from a speed, and the two things not to invent.

Roadmap E17 and §3.1. Process 11 of the student table is the one row that is not
a rate — `rates` is keyed by process class and answers nm/s, and this answers nm
at an rpm — so it is a fourth submodel on `MaterialType`, in the same row as
`develop`, `dissolve` and `sputter_response`, and for the same reason E13 puts
tone on the resist: the thickness a resist spins to is a property of the resist.

What the tests below are actually defending is the *restraint* in §3.1, because
that is what a later reader is most likely to undo:

- the curve is **interpolated, not fitted**. `d ~ rpm^-1/2` misses the measured
  5000 rpm point by 6.8 % in the opposite direction from its 2000 rpm error, so
  no single power law passes through these five points;
- outside 1000-5000 rpm it **clamps and says so**, rather than extrapolating a
  number nobody measured;
- there is **no time axis**. The step takes a spin time, records it, and does not
  let it touch the thickness.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import csg, measures
from nanofab_v3.materials import (
    CHROME,
    RESIST,
    SILICON,
    MaterialLibrary,
    MaterialType,
    SpinCurve,
    didactic_library,
)
from nanofab_v3.processes import ParameterError, builtin_registry, run_step
from nanofab_v3.processes import substrate
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes.lithography import (
    _levelled_top,
    _top_surface,
    levelled_spin_coat,
    spin_coat,
    spun_thickness,
)

MEASURED = ((1000.0, 150.0), (2000.0, 99.8), (3000.0, 82.0), (4000.0, 74.0), (5000.0, 72.0))
"""The five points of roadmap §3.1, as the table gives them."""


@pytest.fixture
def library() -> MaterialLibrary:
    return didactic_library()


@pytest.fixture
def wafer():
    grid = substrate.cross_section_grid(width=240.0, thickness=40.0, headroom=400.0)
    return substrate.select_substrate(grid, "silicon", surface=40.0)


# -- the model ----------------------------------------------------------------


def test_the_curve_returns_every_measured_point_exactly(library: MaterialLibrary) -> None:
    """Exactly, not approximately: a quoted measurement with a float tail invites doubt.

    `exp(log(82.0))` is 82.00000000000001, which is why the lookup answers a
    stored point before any arithmetic runs.
    """
    curve = library[RESIST].spin_curve
    assert curve is not None

    for speed, thickness in MEASURED:
        assert curve.thickness(speed) == thickness
        assert library[RESIST].spin_thickness(speed) == thickness


def test_a_power_law_would_not_carry_these_points() -> None:
    """§3.1's arithmetic, re-run here, because it is the whole reason for the design.

    If this ever stops failing, the data changed and `SpinCurve` could become a
    formula. Until then, a fit is a worse answer than five numbers.
    """
    k = 150.0 * math.sqrt(1000.0)  # anchored on the slowest measured point

    predicted = {speed: k / math.sqrt(speed) for speed, _ in MEASURED}
    errors = {
        speed: (predicted[speed] - thickness) / thickness for speed, thickness in MEASURED
    }

    assert errors[1000.0] == pytest.approx(0.0, abs=1e-12)
    assert errors[2000.0] == pytest.approx(0.063, abs=0.002)  # +6.3 %
    assert errors[5000.0] == pytest.approx(-0.068, abs=0.002)  # -6.8 %, the other way
    assert max(errors.values()) > 0.05 > min(errors.values()) + 0.05  # the sign changes


def test_between_the_points_the_curve_is_monotone_and_stays_inside_them() -> None:
    """Interpolation, not a fit: no segment may overshoot its own endpoints."""
    curve = SpinCurve(points=MEASURED)

    previous = float("inf")
    for speed in range(1000, 5001, 25):
        thickness = curve.thickness(float(speed))
        assert thickness <= previous + 1e-12, speed
        previous = thickness
    assert curve.thickness(1500.0) < 150.0
    assert curve.thickness(1500.0) > 99.8
    # Log-log interpolation is the geometric mean at the midpoint of a decade step.
    assert curve.thickness(math.sqrt(1000.0 * 2000.0)) == pytest.approx(
        math.sqrt(150.0 * 99.8)
    )


def test_outside_the_measured_range_it_clamps_and_admits_it() -> None:
    """§3.1: "außerhalb 1000-5000 rpm klemmen statt extrapolieren, und das sagen"."""
    curve = SpinCurve(points=MEASURED)

    assert curve.speed_range == (1000.0, 5000.0)
    assert curve.thickness(500.0) == 150.0
    assert curve.thickness(9000.0) == 72.0
    assert curve.clamps(500.0) and curve.clamps(9000.0)
    assert not curve.clamps(1000.0) and not curve.clamps(5000.0)


def test_a_curve_that_cannot_be_read_as_pairs_is_refused() -> None:
    """The reason points are pairs: two parallel lists can drift out of step."""
    with pytest.raises(ValueError, match="at least two"):
        SpinCurve(points=((1000.0, 150.0),))
    with pytest.raises(ValueError, match="strictly ascending"):
        SpinCurve(points=((2000.0, 99.8), (1000.0, 150.0)))
    with pytest.raises(ValueError, match="positive"):
        SpinCurve(points=((0.0, 150.0), (2000.0, 99.8)))


def test_a_material_with_no_curve_refuses_rather_than_guessing(
        library: MaterialLibrary,
) -> None:
    """B11's rule: an invented curve is worse than none, because only none is visible."""
    with pytest.raises(ValueError, match="no spin curve"):
        MaterialType(material_id="az10xt", name="AZ10XT").spin_thickness(3000.0)
    with pytest.raises(ValueError, match="no spin curve"):
        spun_thickness(library, "underlayer", 3000.0)
    with pytest.raises(ValueError, match="no MaterialType"):
        spun_thickness(library, "az10xt", 3000.0)


def test_the_curve_belongs_to_the_generic_resist_and_says_so(
        library: MaterialLibrary,
) -> None:
    """§3.1's first open point: the table says "photo resist" and names no product."""
    assert library[RESIST].spin_curve is not None
    assert "B11" in library[RESIST].notes
    for material in library:
        if material != RESIST:
            assert library[material].spin_curve is None, material


# -- the step -----------------------------------------------------------------


def test_a_spin_coat_at_3000_rpm_is_82_nm_without_anybody_typing_a_thickness(
        wafer, library: MaterialLibrary
) -> None:
    """M6's DoD sentence, as the test it is: no thickness in, 82 nm out."""
    outcome = run_step(builtin_registry()["resist.spin_coat"], wafer, {}, library=library)

    assert outcome.measurements["thickness"].value == 82.0
    assert outcome.measurements["spin_speed"].value == 3000.0
    assert any("from the resist's spin curve" in line for line in outcome.logs)


def test_the_speed_moves_the_thickness(wafer, library: MaterialLibrary) -> None:
    """The point of the whole submodel: an operator sets a machine, not a number."""
    step = builtin_registry()["resist.spin_coat"]

    slow = run_step(step, wafer, {"spin_speed": 1000.0}, library=library)
    fast = run_step(step, wafer, {"spin_speed": 5000.0}, library=library)

    assert slow.measurements["thickness"].value == 150.0
    assert fast.measurements["thickness"].value == 72.0


def test_typed_thickness_belongs_only_to_the_ideal_sibling(
        wafer, library: MaterialLibrary
) -> None:
    registry = builtin_registry()
    didactic = {spec.name for spec in registry["resist.spin_coat"].parameter_schema()}
    ideal = {spec.name for spec in registry["resist.spin_coat_ideal"].parameter_schema()}

    assert "thickness" not in didactic
    assert ideal == {"material", "thickness"}
    outcome = run_step(
        registry["resist.spin_coat_ideal"],
        wafer,
        {"material": RESIST, "thickness": 110.0},
        library=library,
    )
    assert outcome.measurements["thickness"].value == 110.0


def test_a_speed_outside_the_measured_range_is_reported_in_the_run_log(
        wafer, library: MaterialLibrary
) -> None:
    """The clamp is only honest if somebody is told about it."""
    outcome = run_step(
        builtin_registry()["resist.spin_coat"], wafer, {"spin_speed": 9000.0}, library=library
    )

    assert outcome.measurements["thickness"].value == 72.0
    assert any("clamped, not extrapolated" in line for line in outcome.logs)


def test_the_spin_time_is_recorded_and_does_not_touch_the_thickness(
        wafer, library: MaterialLibrary
) -> None:
    """§3.1's second open point, as a step contract rather than a silent convention.

    The measured curve parameterises speed alone. That is physically reasonable
    above some minimum time and it is still an assumption, so the time is a
    documented field whose help text says it does not enter — never a factor
    folded quietly into the number.
    """
    step = builtin_registry()["resist.spin_coat"]

    brief = run_step(step, wafer, {"spin_time": 5.0}, library=library)
    long = run_step(step, wafer, {"spin_time": 120.0}, library=library)

    assert brief.measurements["thickness"].value == long.measurements["thickness"].value == 82.0
    help_text = next(
        spec.description for spec in step.parameter_schema() if spec.name == "spin_time"
    )
    assert "does NOT enter the thickness" in help_text


def test_the_didactic_schema_has_speed_and_no_thickness() -> None:
    """M12: a curve-driven step cannot silently become a typed ideal step."""
    schema = {spec.name: spec for spec in builtin_registry()["resist.spin_coat"].parameter_schema()}

    assert "thickness" not in schema
    assert not schema["spin_speed"].required
    with pytest.raises(ParameterError):
        schema["spin_speed"].validate(-5.0)


def test_the_coated_film_really_is_that_thick(wafer, library: MaterialLibrary) -> None:
    """The measurement and the geometry are the same number, not two.

    `spin_coat` planarises: its top sits `thickness` above the highest solid, so
    on a flat wafer with its surface at 40 nm a 3000 rpm coat tops out at 122 nm.
    """
    import numpy as np

    outcome = run_step(builtin_registry()["resist.spin_coat"], wafer, {}, library=library)
    resist = outcome.structure.phi[RESIST][:, 120] < 0.0
    top = outcome.structure.grid.origin[0] + outcome.structure.grid.spacing * float(
        np.flatnonzero(resist).max()
    )

    assert top == pytest.approx(40.0 + 82.0, abs=1.0)


# -- M12 / E41: feature-scale planarisation ----------------------------------


def test_flat_leveling_is_bit_identical_to_the_ideal_constructor(wafer) -> None:
    ideal = spin_coat(wafer, RESIST, thickness=82.0)
    levelled = levelled_spin_coat(wafer, RESIST, thickness=82.0)

    assert np.array_equal(levelled.phi_of(RESIST), ideal.phi_of(RESIST))


def test_fourth_order_leveling_conserves_volume_and_depends_on_feature_width() -> None:
    narrow = np.zeros(201)
    narrow[95:106] = 40.0
    broad = np.zeros(201)
    broad[60:141] = 40.0

    narrow_top = _levelled_top(narrow, 20.0, 2.0)
    broad_top = _levelled_top(broad, 20.0, 2.0)
    narrow_film = narrow_top - narrow
    broad_film = broad_top - broad

    assert float(narrow_film.mean()) == pytest.approx(20.0, abs=1e-10)
    assert float(broad_film.mean()) == pytest.approx(20.0, abs=1e-10)
    assert np.all(narrow_film >= 0.0) and np.all(broad_film >= 0.0)
    assert float(narrow_film.min()) < float(broad_film.min())


def test_spin_coating_a_grating_levels_without_losing_film_volume() -> None:
    grid = substrate.cross_section_grid(
        width=400.0, thickness=40.0, headroom=180.0, spacing=2.0
    )
    wafer = substrate.select_substrate(grid, SILICON, surface=40.0)
    topography = wafer
    for left in (40.0, 140.0, 240.0, 340.0):
        ridge = ctor.box(grid, lower=(40.0, left), upper=(80.0, left + 40.0))
        topography = ctor.add_material(topography, CHROME, ridge)

    reference = levelled_spin_coat(wafer, RESIST, thickness=40.0)
    coated = levelled_spin_coat(topography, RESIST, thickness=40.0)
    before_relief = float(np.ptp(_top_surface(topography)))
    after_relief = float(np.ptp(_top_surface(coated)))
    reference_volume = measures.enclosed_measure(grid, reference.phi_of(RESIST))
    coated_volume = measures.enclosed_measure(grid, coated.phi_of(RESIST))

    assert 0.0 < after_relief < before_relief
    assert coated_volume == pytest.approx(reference_volume, rel=0.05)


def test_didactic_spin_coat_does_not_fill_a_sealed_cavity() -> None:
    grid = substrate.cross_section_grid(
        width=240.0, thickness=40.0, headroom=120.0, spacing=2.0
    )
    wafer = substrate.select_substrate(grid, SILICON, surface=40.0)
    cavity = ctor.box(grid, lower=(10.0, 90.0), upper=(30.0, 150.0))
    holed = Structure(
        grid,
        {SILICON: csg.difference(wafer.phi_of(SILICON), cavity)},
    )

    coated = levelled_spin_coat(holed, RESIST, thickness=40.0)
    y = int(round((20.0 - grid.origin[0]) / grid.spacing))
    x = int(round((120.0 - grid.origin[1]) / grid.spacing))
    assert not coated.inside(RESIST)[y, x]
