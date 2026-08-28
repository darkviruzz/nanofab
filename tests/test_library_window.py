"""The library window, and the two rules E37 attaches to editing (roadmap E37).

The window is a reference work first: until now the only way to see what a build
had loaded was `--version` in a terminal, which is the wrong place for the person
looking at a cross-section. The editor half is where a project like this quietly
goes wrong, and both rules below are about provenance rather than about files.
"""

from __future__ import annotations

import dataclasses
import datetime
from pathlib import Path

import pytest

from nanofab_v3.materials import (
    MaterialType,
    didactic_library,
    invalidate_cache,
    read_material,
    write_material,
)
from nanofab_v3.materials import editing, store

qt = pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture()
def room(tmp_path, monkeypatch):
    """A writable library root with the shipped files and an `.original/` beside."""
    monkeypatch.setenv(store.MATERIALS_ENV, str(tmp_path))
    original = tmp_path / editing.ORIGINAL_DIR
    original.mkdir()
    for path in store.builtin_materials_dir().glob("*.json"):
        text = path.read_text(encoding="utf-8")
        (tmp_path / path.name).write_text(text, encoding="utf-8")
        (original / path.name).write_text(text, encoding="utf-8")
    invalidate_cache()
    yield tmp_path
    invalidate_cache()


# -- E37's first rule: a canonical, atomic write ------------------------------


def test_editing_one_rate_leaves_every_other_field_byte_identical(room):
    """The whole reason `write_material` is the only writer."""
    before = (room / "chrome.json").read_text(encoding="utf-8")
    chrome = read_material(room / "chrome.json")
    editing.save_edit(
        dataclasses.replace(chrome, rates={**dict(chrome.rates), "ion_beam": 0.9}),
        root=room,
    )
    after = (room / "chrome.json").read_text(encoding="utf-8")

    changed = [
        (b, a) for b, a in zip(before.splitlines(), after.splitlines()) if a != b
    ]
    # The rate line, and the note line that has to move with it. Nothing else.
    assert len(changed) == 2
    assert all("ion_beam" in b or "Edited" in a or "0.7" in b for b, a in changed)


def test_a_write_leaves_no_scratch_file_behind(room):
    chrome = read_material(room / "chrome.json")
    editing.save_edit(dataclasses.replace(chrome, name="Chromium"), root=room)
    assert not list(room.glob("*.part"))


# -- E37's second rule: the provenance is carried forward ---------------------


def test_a_changed_rate_rewrites_its_note_to_say_what_it_was(room):
    """Editing a rate turns "student table, row 1" into a claim that is no longer
    true. The note says so, and keeps the old claim inside it — it is still true
    about the old number."""
    chrome = read_material(room / "chrome.json")
    was = chrome.rate_for("ion_beam")
    old_note = chrome.rate_note("ion_beam")

    editing.save_edit(
        dataclasses.replace(chrome, rates={**dict(chrome.rates), "ion_beam": 0.9}),
        root=room,
        today=datetime.date(2026, 8, 27),
    )
    note = read_material(room / "chrome.json").rate_note("ion_beam")

    assert note.startswith("Edited 2026-08-27 (was ")
    assert f"{was:g}" in note
    assert old_note in note


def test_an_untouched_rate_keeps_its_note_exactly(room):
    """Stamping every note on every save would make ten untouched rates look
    edited, which destroys the information this exists to preserve."""
    chrome = read_material(room / "chrome.json")
    before = chrome.rate_note("wet_etch_cr")

    editing.save_edit(
        dataclasses.replace(chrome, rates={**dict(chrome.rates), "ion_beam": 0.9}),
        root=room,
    )
    assert read_material(room / "chrome.json").rate_note("wet_etch_cr") == before


def test_a_note_the_editor_typed_wins_over_the_generated_one(room):
    """Somebody who wrote a provenance by hand knows more about it than we do."""
    chrome = read_material(room / "chrome.json")
    editing.save_edit(
        dataclasses.replace(
            chrome,
            rates={**dict(chrome.rates), "ion_beam": 0.9},
            rate_notes={**dict(chrome.rate_notes), "ion_beam": "Measured on our IBE, 2026-08."},
        ),
        root=room,
    )
    assert read_material(room / "chrome.json").rate_note("ion_beam") == (
        "Measured on our IBE, 2026-08."
    )


def test_reset_puts_the_delivered_file_back(room):
    chrome = read_material(room / "chrome.json")
    editing.save_edit(
        dataclasses.replace(chrome, rates={**dict(chrome.rates), "ion_beam": 0.9}),
        root=room,
    )
    assert editing.reset_material("chrome", root=room) is not None
    assert read_material(room / "chrome.json").rate_for("ion_beam") == chrome.rate_for(
        "ion_beam"
    )


def test_the_original_directory_is_not_a_library_root(room):
    """E19's two-truths problem stays closed: `.original/` is a backup, and a
    dot directory, so `read_root`'s glob never sees it."""
    _library, report = store.load_library((room,))
    assert all(editing.ORIGINAL_DIR not in str(path) for path in report.loaded.values())


# -- the window ---------------------------------------------------------------


def test_the_window_lists_every_material_and_says_where_it_came_from(qt_app, room):
    from nanofab_v3.ui.library_window import LibraryWindow

    window = LibraryWindow()
    tab = window.materials
    assert tab.list.count() == 12
    tab._select("chrome")
    assert "chrome.json" in tab.source.text()
    assert tab._notes["ion_beam"].text()  # rate_notes are visible, not hidden


def test_the_window_shows_the_files_that_did_not_parse(qt_app, room):
    """The only place a failed material is visible at all: `load_library` is
    lenient by design so one stray comma cannot empty the library."""
    (room / "broken.json").write_text('{"schema": 1, "material_id": ', encoding="utf-8")
    invalidate_cache()

    from nanofab_v3.ui.library_window import LibraryWindow

    window = LibraryWindow()
    assert "broken.json" in window.materials.failures.text()


def test_saving_from_the_window_writes_the_file_and_announces_it(qt_app, room):
    from nanofab_v3.ui.library_window import LibraryWindow

    window = LibraryWindow()
    tab = window.materials
    tab._select("chrome")
    tab._rates["ion_beam"].setValue(0.9)

    seen = []
    tab.library_changed.connect(lambda: seen.append(True))
    tab._save()

    assert seen == [True]
    assert read_material(room / "chrome.json").rate_for("ion_beam") == pytest.approx(0.9)


def test_a_zeroed_rate_leaves_the_file_rather_than_claiming_a_measurement(qt_app, room):
    """The library's own convention: absent beats invented (handoff §3.3)."""
    from nanofab_v3.ui.library_window import LibraryWindow

    window = LibraryWindow()
    tab = window.materials
    tab._select("chrome")
    tab._rates["ion_beam"].setValue(0.0)
    entry = tab.edited_entry()
    assert "ion_beam" not in entry.rates


def test_the_demo_tab_lists_the_demos_and_their_files(qt_app, room):
    from nanofab_v3.ui.library_window import LibraryWindow

    window = LibraryWindow()
    assert window.demos.list.count() == 5
    assert ".json" in window.demos.source.text()
