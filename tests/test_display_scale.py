"""True to scale until it is not, and never quietly (M8, E8).

Roadmap E8: *"automatisch maßstabsgetreu bis ~4:1, darüber gestaucht — mit
permanent sichtbarem Verzerrungsfaktor und einem Knopf zum Umschalten"*, and the
reason it gives is the one that matters: **a silently compressed etch flank is
worse for a didactic tool than an awkward view**, because flank angles are
exactly what somebody is being asked to judge.

So the rule has three parts and all three are tested: a domain near square is
drawn honestly, a very deep or very narrow one has its long axis compressed
rather than becoming a sliver, and the factor is *always* reported — including
when it is 1.
"""

from __future__ import annotations

import pytest

from nanofab_v3.materials import SILICON
from nanofab_v3.processes import substrate
from nanofab_v3.ui.scene import ASPECT_LIMIT, display_scale


def test_a_domain_within_the_limit_is_drawn_true_to_scale() -> None:
    """The common case, and the one where a wrong angle would be most misleading."""
    for span_up, span_right in ((240.0, 480.0), (600.0, 600.0), (1000.0, 4000.0)):
        scale = display_scale(span_up, span_right, 600.0, 1000.0)

        assert scale.true_to_scale, (span_up, span_right)
        assert scale.describe() == "1:1 true to scale"


def test_the_reference_cross_section_is_drawn_honestly() -> None:
    """1200 x 240 nm is 5:1 — just past the limit, so 1.25x and said out loud."""
    scale = display_scale(240.0, 1200.0, 600.0, 1000.0)

    assert not scale.true_to_scale
    assert scale.distortion == pytest.approx(4.0 / 5.0)
    assert scale.describe() == "1.25x compressed horizontally — angles are not true"


def test_a_deep_narrow_domain_has_its_long_axis_compressed() -> None:
    """A 250 nm x 5 um window would otherwise be a sliver nobody can read."""
    scale = display_scale(5000.0, 250.0, 600.0, 1000.0)

    # The domain is 1:20; drawing it at 1:4 means stretching x relative to y by 5.
    assert scale.distortion == pytest.approx((1.0 / ASPECT_LIMIT) / (250.0 / 5000.0))
    assert "compressed vertically" in scale.describe()
    # The displayed picture is exactly at the limit, never past it.
    assert (250.0 * scale.right) / (5000.0 * scale.up) == pytest.approx(1.0 / ASPECT_LIMIT)


def test_the_compression_never_exceeds_the_limit() -> None:
    """Whatever the domain, the drawn aspect lands inside [1/limit, limit]."""
    for aspect in (0.001, 0.05, 0.3, 1.0, 3.0, 40.0, 900.0):
        scale = display_scale(1000.0, 1000.0 * aspect, 600.0, 1000.0)
        drawn = (1000.0 * aspect * scale.right) / (1000.0 * scale.up)

        assert 1.0 / ASPECT_LIMIT - 1e-9 <= drawn <= ASPECT_LIMIT + 1e-9, aspect


def test_the_picture_still_fits_the_widget() -> None:
    """Compression is about legibility, so it must not cost the fit."""
    for span_up, span_right in ((240.0, 1200.0), (5000.0, 250.0), (600.0, 600.0)):
        scale = display_scale(span_up, span_right, 600.0, 1000.0)

        assert span_right * scale.right <= 1000.0 + 1e-6
        assert span_up * scale.up <= 600.0 + 1e-6


def test_the_button_turns_it_off_completely() -> None:
    """E8's "Knopf zum Umschalten/Deaktivieren": an honest, awkward view on demand."""
    squashed = display_scale(5000.0, 250.0, 600.0, 1000.0)
    honest = display_scale(5000.0, 250.0, 600.0, 1000.0, isotropic=True)

    assert not squashed.true_to_scale
    assert honest.true_to_scale
    assert honest.up == honest.right


def test_a_degenerate_span_is_refused_rather_than_divided_by() -> None:
    with pytest.raises(ValueError, match="positive spans"):
        display_scale(0.0, 100.0, 600.0, 1000.0)


# -- the canvas ---------------------------------------------------------------


@pytest.fixture(scope="module")
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_canvas_reports_its_own_distortion_and_can_be_told_not_to(qt_app) -> None:
    """The factor is a property of the widget, not a string in a label somewhere:
    a test can read it, and so can anything else that needs to know."""
    from nanofab_v3.ui.canvas import CrossSectionCanvas
    from nanofab_v3.ui.scene import build

    grid = substrate.cross_section_grid(width=200.0, thickness=1000.0, headroom=3000.0)
    deep = substrate.select_substrate(grid, SILICON, surface=1000.0)
    canvas = CrossSectionCanvas()
    canvas.resize(1000, 600)
    canvas.set_scene(build(deep))

    squashed = canvas.display_scale()
    assert squashed is not None and not squashed.true_to_scale

    canvas.set_true_to_scale(True)

    assert canvas.display_scale().true_to_scale


def test_the_hit_test_follows_the_two_scales(qt_app) -> None:
    """The nm-to-pixel map got a second scale; the pixel-to-nm one has to agree,
    or "what is under the cursor" would answer about a different cell."""
    from nanofab_v3.ui.canvas import CrossSectionCanvas
    from nanofab_v3.ui.scene import build

    grid = substrate.cross_section_grid(width=200.0, thickness=1000.0, headroom=3000.0)
    deep = substrate.select_substrate(grid, SILICON, surface=1000.0)
    canvas = CrossSectionCanvas()
    canvas.resize(1000, 600)
    canvas.set_scene(build(deep))

    scale_up, scale_right, x0, y0, height = canvas._viewport()
    point = canvas._to_nm(x0 + 40.0 * scale_right, y0 + height - 250.0 * scale_up)

    assert point == pytest.approx((250.0, 40.0))
