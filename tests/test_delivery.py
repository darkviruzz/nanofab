"""What a delivered folder is, and what it does when a piece of it is missing.

Roadmap E19/E20/E36/E39. Everything here is about the **frozen** build, which is
the one class of failure a source checkout cannot see: M6's `data/` migration
worked perfectly in a working copy and shipped an exe with no materials in it, and
E19 removes the fallback that made the second copy survivable. So the delivered
build is faked rather than frozen — `sys.frozen` and `sys.executable` are all
`paths` reads — and the checks are about *decisions*, not about PyInstaller.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

from nanofab_v3 import branding, paths, settings as app_settings
from nanofab_v3.materials import (
    MaterialType,
    didactic_library,
    invalidate_cache,
    library_fingerprint,
    load_library,
    write_material,
)
from nanofab_v3.materials import store


@pytest.fixture()
def delivered(tmp_path, monkeypatch):
    """A directory that behaves like a delivered folder: exe, `bin/`, `data/`."""
    monkeypatch.delenv(store.MATERIALS_ENV, raising=False)
    monkeypatch.delenv("NANOFAB_DEMOS", raising=False)
    monkeypatch.delenv(app_settings.SETTINGS_ENV, raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nanofab_v3"))
    (tmp_path / "bin").mkdir()
    invalidate_cache()
    app_settings.invalidate_cache()
    yield tmp_path
    invalidate_cache()
    app_settings.invalidate_cache()


def _place_library(root: Path) -> Path:
    """Copy the shipped library into a delivered folder's `data/materials/`."""
    target = root / "data" / "materials"
    target.mkdir(parents=True)
    for entry in store.builtin_materials_dir().glob("*.json"):
        (target / entry.name).write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
    return target


# -- E19: one directory, and the library in it exactly once -------------------


def test_a_delivered_build_reads_one_library_root_and_it_is_the_visible_one(delivered):
    """The packaged copy is gone, so both root lists collapse onto the same folder.

    This is E19's whole substance. Two roots meant that when the sealed copy and
    the visible one disagreed, the visible one silently won and nobody could say
    which numbers had run.
    """
    materials = _place_library(delivered)
    assert store.delivered_only() is True
    assert store.material_roots() == (materials,)
    assert store.didactic_roots() == (materials,)
    assert len(didactic_library()) == 11


def test_a_rate_edited_in_the_delivered_folder_is_the_rate_that_runs(delivered):
    """The DoD's sentence: change a number there, restart, and it is that number."""
    materials = _place_library(delivered)
    before = didactic_library()["chrome"].rate_for("ion_beam")
    edited = MaterialType(
        **{
            **{
                field: getattr(didactic_library()["chrome"], field)
                for field in ("material_id", "name", "display_color", "sputter_response")
            },
            "rates": {**dict(didactic_library()["chrome"].rates), "ion_beam": before * 3.0},
        }
    )
    write_material(edited, materials / "chrome.json")
    invalidate_cache()  # a restart, in the one way a test can spell it
    assert didactic_library()["chrome"].rate_for("ion_beam") == pytest.approx(before * 3.0)


def test_a_delivery_with_no_materials_says_where_it_looked_instead_of_starting(delivered):
    """No fallback is the decision; a sentence naming the path is what replaces it.

    An empty library is not a degraded mode — every rate lookup answers zero and
    every scenario fails on physics that is not wrong. The failure has to name the
    folder, or the bug report is about the model.
    """
    reason = store.missing_library_reason()
    assert reason is not None
    assert str(delivered / "data" / "materials") in reason
    assert "data/materials" in reason


def test_a_source_checkout_still_has_two_roots_and_needs_no_rescue():
    """The split is real where it can be: shipped is shipped, and tests see only it."""
    assert store.delivered_only() is False
    assert store.material_roots() == (store.builtin_materials_dir(), store.user_materials_dir())
    assert store.didactic_roots() == (store.builtin_materials_dir(),)
    assert store.missing_library_reason() is None


def test_missing_demos_cost_the_menu_and_not_the_program(delivered):
    """E19's asymmetry: a demo is a worked example, the library is the physics."""
    _place_library(delivered)
    from nanofab_v3.ui import demos as demo_module

    entries, report = demo_module.load_demos(demo_module.demo_roots())
    assert entries == ()
    assert report.failures == ()
    assert store.missing_library_reason() is None


# -- E36: the fingerprint that replaces the isolation E19 gave up -------------


def test_the_fingerprint_moves_with_a_rate_and_not_with_the_formatting(tmp_path):
    """Over the models, not the bytes: a reformatted file is the same library."""
    shipped, _ = load_library((store.builtin_materials_dir(),))
    baseline = library_fingerprint(shipped.entries)
    assert len(baseline) == 12

    room = tmp_path / "materials"
    room.mkdir()
    for entry in store.builtin_materials_dir().glob("*.json"):
        text = entry.read_text(encoding="utf-8")
        (room / entry.name).write_text(text.replace("\n", "\n\n"), encoding="utf-8")
    reformatted, _ = load_library((room,))
    assert library_fingerprint(reformatted.entries) == baseline

    chrome = shipped["chrome"]
    changed = dict(shipped.entries)
    changed["chrome"] = MaterialType(
        material_id=chrome.material_id,
        name=chrome.name,
        rates={**dict(chrome.rates), "ion_beam": chrome.rate_for("ion_beam") + 0.001},
    )
    assert library_fingerprint(changed) != baseline


def test_the_version_line_carries_the_fingerprint():
    """`--version` is where somebody checks which numbers a screenshot came from."""
    import io

    from nanofab_v3.cli import describe_build

    stream = io.StringIO()
    describe_build(stream)
    text = stream.getvalue()
    assert "materials: fingerprint " in text
    assert "settings: " in text


def test_the_selftest_banner_names_the_library_before_it_runs_anything():
    import io

    from nanofab_v3.cli import selftest

    stream = io.StringIO()
    selftest(["S5c"], stream=stream)
    assert "fingerprint" in stream.getvalue().splitlines()[1]


# -- E39: settings.ini documents itself, and is never written back ------------


def test_the_generated_ini_parses_back_to_exactly_the_defaults():
    """The file is rendered from the same table `parse` reads, so it cannot drift."""
    parsed = app_settings.parse(app_settings.default_ini_text())
    assert parsed.values == app_settings.defaults().values
    assert parsed.problems == ()


def test_every_setting_is_in_the_file_with_a_comment():
    text = app_settings.default_ini_text()
    for spec in app_settings.KEYS:
        assert f"[{spec.section}]" in text
        assert f"{spec.key} = " in text
        assert spec.comment.splitlines()[0] in text
    assert f"[{app_settings.PARAMETERS_SECTION}]" in text


def test_a_typo_in_the_ini_is_reported_and_does_not_stop_the_program():
    """The one file an operator is invited to edit must not be able to brick a start."""
    parsed = app_settings.parse(
        "[view]\npicture = watercolour\nsideways = yes\n[domain]\ncap_um = 9.0\n"
    )
    assert parsed["domain.cap_um"] == 9.0
    assert parsed["view.picture"] == "contours"
    assert len(parsed.problems) == 2


def test_parameter_prefills_are_read_per_step_and_left_as_text():
    parsed = app_settings.parse(
        f"[{app_settings.PARAMETERS_SECTION}]\n"
        "etch.icp_fluorine.duration = 120\n"
        "etch.icp_fluorine.scale = 1.5\n"
    )
    assert parsed.prefill("etch.icp_fluorine") == {"duration": "120", "scale": "1.5"}
    assert parsed.prefill("deposit.evaporate") == {}


def test_a_deleted_settings_file_is_restored_with_the_documented_defaults(delivered):
    """Deleting it is how you ask for the comments back; editing it is never undone."""
    written = app_settings.ensure_delivered_settings()
    assert written == delivered / paths.SETTINGS_FILE
    assert written.read_text(encoding="utf-8") == app_settings.default_ini_text()

    written.write_text("[domain]\ncap_um = 2.0\n", encoding="utf-8")
    assert app_settings.ensure_delivered_settings() == written
    assert app_settings.load(written)["domain.cap_um"] == 2.0


# -- E20: there is an icon, and it is generated from a versioned SVG ----------


def test_the_icon_is_an_ico_with_the_four_sizes_windows_asks_for():
    """The `.ico` is checked as an artefact, never re-rendered.

    Re-rendering would pin whatever rasteriser this machine's Qt happens to use,
    as if it were one of this project's numbers. `scripts/make_icon.py` is the
    generator and the SVG beside it is the source.
    """
    icon = branding.icon_file()
    assert icon is not None and branding.svg_file() is not None
    blob = icon.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", blob[:6])
    assert (reserved, kind) == (0, 1)
    sizes = []
    for index in range(count):
        entry = blob[6 + 16 * index : 6 + 16 * (index + 1)]
        width = entry[0] or 256
        sizes.append(width)
    assert sorted(sizes) == [16, 32, 48, 256]
