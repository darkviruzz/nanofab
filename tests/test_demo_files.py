"""The demos are files, and the files are the ones an operator edits.

The follow-up to M9, and roadmap E14 one milestone later: the recipes moved out
of `ui/demos.py` and into `nanofab_v3/data/demos/*.json`, for the reason the
material library moved before them — a number nobody can open is a number nobody
can correct. A frozen build places that directory **next to the executable**
(`nanofab_v3.spec`, note 6), so changing a duration and restarting is the whole
loop: no checkout, no toolchain, no rebuild.

Three properties are worth a test and none of them is "it parses":

- **The files are the definition.** `lift_off()` and its three siblings are
  lookups now, so a demo the code disagrees with is not possible.
- **A hand-written file fails loudly.** Unknown fields are an error, which is the
  opposite of §9's rule for a *revision* file and deliberately so: a revision is
  written by this program for a later one, where tolerance is compatibility; a
  demo is written by a person, where a silently dropped `durration` is a demo
  that does the wrong thing without saying so.
- **A broken file costs one demo.** The picker still opens, and `--version` says
  which file was skipped and why. A menu emptied by a stray comma is the failure
  this leniency exists to prevent.
"""

from __future__ import annotations

import json

import pytest

from nanofab_v3 import paths
from nanofab_v3.ui import demos as demo_module
from nanofab_v3.ui.demos import (
    DEMOS_ENV,
    Demo,
    DemoFileError,
    builtin_demos_dir,
    demo,
    demos,
    from_dict,
    invalidate_cache,
    load_demos,
    read_demo,
    to_dict,
    write_demo,
)


@pytest.fixture
def shipped():
    """The four files as they ship, reloaded from disk rather than from the cache."""
    entries, report = load_demos((builtin_demos_dir(),))
    assert report.failures == ()
    return entries


# -- the files are the definition ---------------------------------------------


def test_every_shipped_demo_is_a_file(shipped) -> None:
    assert {entry.key for entry in shipped} == {
        "lift_off",
        "chrome_grating",
        "titania_stop",
        "black_silicon",
    }
    assert [entry.key for entry in shipped] == [entry.key for entry in demos()]


def test_the_named_builders_are_lookups_now(shipped) -> None:
    """`lift_off()` reads the file; it does not hold a second copy of the recipe."""
    assert demo_module.lift_off() == demo("lift_off")
    assert demo_module.chrome_hard_mask_grating() == demo("chrome_grating")
    assert demo_module.titania_grating_on_an_etch_stop() == demo("titania_stop")
    assert demo_module.black_silicon() == demo("black_silicon")


def test_the_filename_orders_the_menu(shipped) -> None:
    """Numbered files, so a demo dropped in beside the exe lands at the end."""
    assert [entry.key for entry in shipped][0] == "lift_off"
    names = sorted(path.name for path in builtin_demos_dir().glob("*.json"))
    assert names == [
        "01_lift_off.json",
        "02_chrome_grating.json",
        "03_titania_stop.json",
        "04_black_silicon.json",
    ]


def test_a_demo_survives_a_round_trip_including_its_notes(shipped, tmp_path) -> None:
    """`note` is why a number is what it is, and it is written back."""
    original = demo("titania_stop")
    assert any(original.notes), "the etch-stop demo explains its durations"
    written = write_demo(tmp_path, original)
    assert read_demo(written) == original


def test_notes_are_padded_to_the_steps() -> None:
    """A file may leave `note` off every step, most of them, or none."""
    entry = demo("lift_off")
    assert len(entry.notes) == len(entry.steps)
    assert entry.note(0) == ""
    assert entry.note(999) == ""  # out of range is a missing note, not an error


def test_more_notes_than_steps_is_refused() -> None:
    with pytest.raises(ValueError, match="notes for"):
        Demo(key="k", title="t", summary="", watch_for="", grid=demo("lift_off").grid,
             steps=(), notes=("orphan",))


# -- a hand-written file fails loudly -----------------------------------------


def test_an_unknown_field_is_an_error_not_a_shrug() -> None:
    data = to_dict(demo("lift_off"))
    data["durration"] = 40.0
    with pytest.raises(DemoFileError, match="unknown field"):
        from_dict(data)


def test_an_unknown_field_inside_a_step_is_an_error_too() -> None:
    data = to_dict(demo("lift_off"))
    data["steps"][0]["duraton"] = 4.0
    with pytest.raises(DemoFileError, match="unknown field.*step 0"):
        from_dict(data)


def test_another_schema_version_is_refused() -> None:
    data = to_dict(demo("lift_off"))
    data["schema_version"] = 99
    with pytest.raises(DemoFileError, match="schema_version"):
        from_dict(data)


def test_a_step_without_a_step_id_is_refused() -> None:
    data = to_dict(demo("lift_off"))
    del data["steps"][2]["step_id"]
    with pytest.raises(DemoFileError, match="step 2 has no step_id"):
        from_dict(data)


# -- a broken file costs one demo ---------------------------------------------


def test_a_file_that_does_not_parse_costs_that_demo_and_nothing_else(tmp_path) -> None:
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    write_demo(tmp_path, demo("lift_off"))

    entries, report = load_demos((tmp_path,))

    assert [entry.key for entry in entries] == ["lift_off"]
    assert len(report.failures) == 1
    assert report.failures[0][0].name == "broken.json"
    assert "demos: 1 from 1 root(s)" in report.describe()[0]
    assert any("skipped broken.json" in line for line in report.describe())


def test_an_edited_file_beside_the_exe_replaces_the_shipped_one(tmp_path, monkeypatch) -> None:
    """The whole point of placing the directory next to the executable.

    A key that is already there keeps its **position** and takes the later file's
    content, so an edited etch-stop demo replaces the packaged one rather than
    appearing twice in the menu.
    """
    import dataclasses

    faster = dataclasses.replace(demo("titania_stop"), title="TiO2, but quicker")
    write_demo(tmp_path, faster)
    monkeypatch.setenv(DEMOS_ENV, str(tmp_path))
    invalidate_cache()
    try:
        keys = [entry.key for entry in demos()]
        assert keys.count("titania_stop") == 1
        assert keys.index("titania_stop") == 2  # the shipped position, kept
        assert demo("titania_stop").title == "TiO2, but quicker"
    finally:
        invalidate_cache()


# -- where the editable copy lives --------------------------------------------


def test_a_source_checkout_has_no_folder_next_to_the_program() -> None:
    """`None`, not the repository root — see `paths.portable_root`.

    A checkout's "next to the program" would be the working copy, and quietly
    reading an operator-editable directory out of one is how a test starts
    depending on somebody's scratch files.
    """
    assert paths.frozen() is False
    assert paths.portable_root() is None
    assert paths.portable_dir("data", "demos") is None


def test_the_portable_folder_is_only_used_when_it_is_really_there(monkeypatch, tmp_path) -> None:
    """An exe copied somewhere on its own keeps working off its packaged copy."""
    monkeypatch.setattr(paths, "frozen", lambda: True)
    monkeypatch.setattr(paths.sys, "executable", str(tmp_path / "nanofab_v3"))

    assert paths.portable_root() == tmp_path
    assert paths.portable_dir("data", "demos") is None  # not created, so not used

    (tmp_path / "data" / "demos").mkdir(parents=True)
    assert paths.portable_dir("data", "demos") == tmp_path / "data" / "demos"


def test_the_materials_writable_root_follows_the_program(monkeypatch, tmp_path) -> None:
    """One editable directory, not two — see `materials.store.user_materials_dir`."""
    from nanofab_v3.materials import store

    monkeypatch.delenv(store.MATERIALS_ENV, raising=False)
    monkeypatch.setattr(paths, "frozen", lambda: True)
    monkeypatch.setattr(paths.sys, "executable", str(tmp_path / "nanofab_v3"))
    (tmp_path / "data" / "materials").mkdir(parents=True)

    assert store.user_materials_dir() == tmp_path / "data" / "materials"
    assert store.material_roots()[-1] == tmp_path / "data" / "materials"


def test_the_environment_variable_still_wins(monkeypatch, tmp_path) -> None:
    """Tests and tools override the portable folder, or they could not run at all."""
    from nanofab_v3.materials import store

    monkeypatch.setattr(paths, "frozen", lambda: True)
    monkeypatch.setattr(paths.sys, "executable", str(tmp_path / "nanofab_v3"))
    (tmp_path / "data" / "materials").mkdir(parents=True)
    monkeypatch.setenv(store.MATERIALS_ENV, str(tmp_path / "elsewhere"))

    assert store.user_materials_dir() == tmp_path / "elsewhere"


def test_the_demo_files_are_valid_json_a_person_can_edit() -> None:
    """Indented, newline-terminated, and no surprises — these get opened by hand."""
    for path in builtin_demos_dir().glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert text.endswith("\n")
        assert "\n  " in text  # indented rather than one long line
        json.loads(text)


# -- the delivered build has the library twice, and must not say so -----------


def test_an_identical_file_in_two_roots_is_not_an_override(tmp_path, monkeypatch) -> None:
    """A delivered exe carries the library *and* reads the editable copy beside it.

    Every material therefore shadows an identical twin, and reporting all eleven
    would bury the one line that means something — a lab's own chromium. Only a
    definition that actually differs is an override.
    """
    import shutil

    from nanofab_v3.materials import application_library, invalidate_cache as forget
    from nanofab_v3.materials import store

    shutil.copytree(store.builtin_materials_dir(), tmp_path, dirs_exist_ok=True)
    monkeypatch.setenv(store.MATERIALS_ENV, str(tmp_path))
    forget()

    _library, report = application_library()
    assert report.overridden == {}
    assert report.describe() == ("materials: 11 from 2 root(s)",)

    edited = json.loads((tmp_path / "chrome.json").read_text(encoding="utf-8"))
    edited["rates"]["icp_fluorine"] = 0.5
    (tmp_path / "chrome.json").write_text(json.dumps(edited), encoding="utf-8")
    forget()

    _library, report = application_library()
    assert set(report.overridden) == {"chrome"}
    forget()
