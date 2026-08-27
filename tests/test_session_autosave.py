"""Autosave, the cache ladder and the artifact sink (roadmap E38, E40).

E38's decision in one line: **the recipe is saved, the computation is not.** A
recipe is about a kilobyte; one revision's structures are 23 MB, so a ten-step
chain would be 230 MB written after every step, plus the seconds the application
spends not responding. The structures are already in the replay cache, which
replays 68x faster than solving.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from nanofab_v3.ui import wafer
from nanofab_v3.ui.session import AUTOSAVE_FILE, Session, autosaved_recipe_path


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOFAB_CACHE", str(tmp_path))
    return tmp_path


# -- E38: where it goes -------------------------------------------------------


def test_the_session_and_the_replay_cache_are_siblings_not_one_directory(cache):
    """"Clear the cache" must reclaim gigabytes without taking the recipe."""
    assert wafer.default_cache_dir() == cache / "replay"
    assert wafer.session_cache_dir() == cache / "session"
    assert autosaved_recipe_path() == cache / "session" / AUTOSAVE_FILE


def test_windows_gets_local_appdata_before_a_dot_directory_in_the_profile(monkeypatch):
    """E38's added rung. `C:\\Users\\<name>\\.cache\\` is a Unix convention in a
    place a Windows user has no reason to look, and "where did my session go" is
    a question somebody will ask."""
    import sys

    monkeypatch.delenv("NANOFAB_CACHE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\somebody\AppData\Local")
    monkeypatch.setenv("XDG_CACHE_HOME", "/should/not/win")
    monkeypatch.setattr(sys, "platform", "win32")
    assert str(wafer.cache_root()).startswith(r"C:\Users\somebody\AppData\Local")

    monkeypatch.setattr(sys, "platform", "linux")
    assert wafer.cache_root() == Path("/should/not/win") / "nanofab_v3"


# -- E38: what it writes ------------------------------------------------------


def test_every_step_writes_the_recipe_and_no_structures(cache):
    session = Session(autosave=autosaved_recipe_path())
    session.run("substrate.select", {"preset": "wafer_fs_100"})
    session.run("resist.spin_coat", {"material": "resist", "thickness": 90.0})

    path = autosaved_recipe_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["steps"]) == 2
    # A recipe, not a build: kilobytes, and nothing that looks like an array.
    assert path.stat().st_size < 4096
    assert not list(path.parent.glob("*.npz"))


def test_the_write_is_atomic_so_a_half_written_recipe_cannot_be_offered(cache, monkeypatch):
    """`os.replace` is atomic on all three platforms; a crash mid-write leaves
    the previous recipe, never a file that parses into a different one."""
    session = Session(autosave=autosaved_recipe_path())
    session.run("substrate.select", {"preset": "wafer_fs_100"})
    good = autosaved_recipe_path().read_text(encoding="utf-8")

    def explode(src, dst):
        raise OSError("interrupted")

    monkeypatch.setattr(os, "replace", explode)
    session.run("resist.spin_coat", {"material": "resist", "thickness": 90.0})

    assert autosaved_recipe_path().read_text(encoding="utf-8") == good


def test_rewinding_shortens_the_autosave_too(cache):
    """The file has to say what the session says, or restoring re-runs a step
    somebody deliberately threw away."""
    session = Session(autosave=autosaved_recipe_path())
    session.run("substrate.select", {"preset": "wafer_fs_100"})
    session.run("resist.spin_coat", {"material": "resist", "thickness": 90.0})
    session.rewind(1)

    payload = json.loads(autosaved_recipe_path().read_text(encoding="utf-8"))
    assert len(payload["steps"]) == 1


def test_a_read_only_cache_costs_the_autosave_and_never_the_step(tmp_path):
    """Losing an autosave is acceptable; losing the step somebody just ran is not."""
    session = Session(autosave=tmp_path / "nope" / "x.json")
    session.autosave = Path("/proc/definitely/not/writable/x.json")
    revision = session.run("substrate.select", {"preset": "wafer_fs_100"})
    assert revision.index == 0


def test_peeking_at_a_recipe_does_not_touch_the_session(cache):
    """The restore prompt has to count the steps before anybody agrees to load."""
    session = Session(autosave=autosaved_recipe_path())
    session.run("substrate.select", {"preset": "wafer_fs_100"})

    other = Session()
    assert len(other.peek_recipe(autosaved_recipe_path())) == 1
    assert len(other.recipe) == 0
    assert len(other.chain) == 0


def test_loading_a_restored_recipe_computes_nothing(cache):
    """The whole of the offer. A recipe whose replay crashes must not be able to
    stop the program from starting."""
    session = Session(autosave=autosaved_recipe_path())
    session.run("substrate.select", {"preset": "wafer_fs_100"})
    session.run("resist.spin_coat", {"material": "resist", "thickness": 90.0})

    fresh = Session()
    steps = fresh.load_recipe(autosaved_recipe_path())
    assert len(steps) == 2
    assert len(fresh.chain) == 0
    assert len(fresh.pending) == 2


# -- E40: the artifact wire, plugged in ---------------------------------------


def test_a_session_hands_its_steps_somewhere_to_put_an_artifact():
    """§0.6: the wire was laid in M5 and never plugged in — `Session.sink` was
    `None`, so the SEM and the profilometer produced nothing at all."""
    session = Session()
    session.run("substrate.select", {"preset": "wafer_fs_100"})
    revision = session.run("inspect.profilometer", {"tag": "before"})

    assert revision.artifacts
    assert "profile-before" in session.sink.payloads


def test_saving_a_build_takes_the_artifacts_into_the_folder(tmp_path):
    """E40's other half: memory while there is nowhere to write, files once
    there is. A directory sink would force an unsaved session to invent a path."""
    session = Session()
    session.run("substrate.select", {"preset": "wafer_fs_100"})
    session.run("inspect.sem", {"tag": "stack"})
    session.run("inspect.profilometer", {"tag": "surface"})

    _recipe, directory = session.save_build(tmp_path / "build")

    written = sorted(path.name for path in (directory / "artifacts").glob("*.npy"))
    assert written == ["profile-surface.npy", "sem-stack.npy"]


def test_a_session_with_no_artifacts_writes_no_artifact_folder(tmp_path):
    session = Session()
    session.run("substrate.select", {"preset": "wafer_fs_100"})
    _recipe, directory = session.save_build(tmp_path / "build")
    assert not (directory / "artifacts").exists()
