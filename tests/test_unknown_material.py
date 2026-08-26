"""An unknown material warns and asks (roadmap E15).

The bug this milestone closes, from a real project: a **chromium particle** on a
sample the library had never heard of. `processes.rates` filters every lookup on
`material in library`, so the particle got rate 0 everywhere and behaved like a
perfect hard mask — through every step, without a word anywhere. The picture was
wrong and looked right.

What is asserted here is the whole of E15's shape, which is two claims that pull
against each other and both have to hold:

1. free text stays legal — a material nobody has described still runs, because
   trying something uncalibrated is the didactic point and a plugin may bring its
   own material anyway (plan §5.4);
2. it is never silent — a warning, a run-log line, and a question that names what
   would fix it.

And one boundary: a **missing rate** is not this. `rate_for` answering 0.0 for a
class a material has no entry for is a documented statement — "this does not
move" — and it is how a hard mask works. Warning about it would fire on nearly
every step and teach everybody to ignore warnings.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.materials import (
    ICP_FLUORINE,
    SILICON,
    WET_ETCH,
    MaterialLibrary,
    MissingMaterial,
    UnknownMaterialWarning,
    didactic_library,
    read_material,
    unknown_materials,
)
from nanofab_v3.materials import store
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes import builtin_registry, run_step
from nanofab_v3.processes import substrate

PARTICLE_ID = "chrome_particle"
"""The material of the failure this feature is named after."""


@pytest.fixture
def library() -> MaterialLibrary:
    return didactic_library()


@pytest.fixture
def wafer() -> Structure:
    grid = substrate.cross_section_grid(width=240.0, thickness=40.0, headroom=200.0)
    return substrate.select_substrate(grid, SILICON, surface=40.0)


@pytest.fixture
def contaminated(wafer: Structure) -> Structure:
    """A wafer with a speck of something the library has never heard of."""
    grid = wafer.grid
    return ctor.add_material(
        wafer, PARTICLE_ID, ctor.ball(grid, center=(44.0, 120.0), radius=6.0)
    )


@pytest.fixture
def user_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the writable material root at a temp directory for the whole test."""
    monkeypatch.setenv(store.MATERIALS_ENV, str(tmp_path))
    store.invalidate_cache()
    yield tmp_path
    store.invalidate_cache()


# -- the detection ------------------------------------------------------------


def test_the_structures_materials_are_what_is_checked_not_the_recipes(
    contaminated: Structure, library: MaterialLibrary
) -> None:
    """The particle arrived without a step naming it, which is the whole case.

    `particle.seed` scatters debris and a plugin deposits its own film; neither
    appears in a recipe as a material anybody typed. Checking what the recipe
    mentions would have missed exactly the failure this exists for.
    """
    unknown = unknown_materials(library, contaminated.materials, seen_in="etch.wet")

    assert unknown.ids == (PARTICLE_ID,)
    assert unknown and len(unknown) == 1
    assert PARTICLE_ID in unknown.describe()[0]
    assert "behaves like a perfect mask" in unknown.describe()[0]


def test_a_library_that_knows_everything_says_nothing(
    wafer: Structure, library: MaterialLibrary
) -> None:
    """The normal case has to stay quiet, or the warning is worth nothing."""
    assert not unknown_materials(library, wafer.materials)
    assert unknown_materials(library, wafer.materials).describe() == ()


def test_running_a_step_on_an_unknown_material_warns(
    contaminated: Structure, library: MaterialLibrary
) -> None:
    """The end of the silent zero: one warning per step, from the one place all steps pass."""
    with pytest.warns(UnknownMaterialWarning, match=PARTICLE_ID):
        outcome = run_step(
            builtin_registry()["etch.wet"], contaminated, {"duration": 2.0}, library=library
        )

    assert outcome.unknown.ids == (PARTICLE_ID,)
    assert any(PARTICLE_ID in line for line in outcome.logs)


def test_the_step_still_runs_because_free_text_stays_legal(
    contaminated: Structure, library: MaterialLibrary
) -> None:
    """E15 warns; it does not refuse. Trying something uncalibrated is the point."""
    with pytest.warns(UnknownMaterialWarning):
        outcome = run_step(
            builtin_registry()["etch.wet"], contaminated, {"duration": 2.0}, library=library
        )

    assert outcome.ok
    assert PARTICLE_ID in outcome.structure.materials


def test_a_known_material_with_no_rate_for_this_process_does_not_warn(
    wafer: Structure, library: MaterialLibrary
) -> None:
    """The boundary. "The bath does not attack this" is an answer, not a silence.

    Silicon has an explicit `wet_etch` rate of 0.0 and no `rie_chlorine` entry at
    all. Neither is a missing material: the library was asked and had something
    to say, which is exactly what a hard mask is.
    """
    assert library[SILICON].rate_for(WET_ETCH) == 0.0
    assert "rie_chlorine" not in library[SILICON].rates

    with warnings.catch_warnings():
        warnings.simplefilter("error", UnknownMaterialWarning)
        run_step(builtin_registry()["etch.wet"], wafer, {"duration": 2.0}, library=library)
        run_step(
            builtin_registry()["etch.rie_chlorine"], wafer, {"duration": 2.0}, library=library
        )


def test_a_material_introduced_by_the_step_itself_is_caught(
    wafer: Structure, library: MaterialLibrary
) -> None:
    """Checked after the commit, not before: the step is how the material arrives."""
    with pytest.warns(UnknownMaterialWarning, match="tungsten"):
        outcome = run_step(
            builtin_registry()["deposit.evaporate"],
            wafer,
            {"material": "tungsten", "thickness": 10.0},
            library=library,
        )

    assert outcome.unknown.ids == ("tungsten",)


# -- the answer ---------------------------------------------------------------


def test_the_question_becomes_a_material_the_dataclass_validates() -> None:
    """The same validator a file goes through, so both are refused for one reason."""
    missing = MissingMaterial(material_id=PARTICLE_ID, seen_in="etch.wet")

    described = missing.draft(name="Chromium particle", rates={ICP_FLUORINE: 0.0333})

    assert described.material_id == PARTICLE_ID
    assert described.rate_for(ICP_FLUORINE) == 0.0333
    assert "Uncalibrated" in described.notes
    with pytest.raises(ValueError, match="unknown process class"):
        missing.draft(rates={"plasma": 1.0})
    with pytest.raises(ValueError, match="non-negative"):
        missing.draft(rates={ICP_FLUORINE: -1.0})


def test_a_described_material_is_written_where_the_next_session_will_find_it(
    user_root: Path,
) -> None:
    """E15's last clause: the dialog writes to `data/materials/`, so the answer keeps.

    The *writable* root, never the shipped one — a build's own files are part of
    the delivery, and an application that edited them would make two installs of
    the same version disagree.
    """
    described = MissingMaterial(material_id=PARTICLE_ID).draft(rates={ICP_FLUORINE: 0.0333})

    path = store.save_material(described)

    assert path == user_root / f"{PARTICLE_ID}.json"
    assert read_material(path) == described
    library, _ = store.load_library((store.builtin_materials_dir(), user_root))
    assert PARTICLE_ID in library
    assert PARTICLE_ID not in didactic_library()  # the shipped set is not edited


def test_describing_it_takes_the_session_out_of_the_warning(
    contaminated: Structure, user_root: Path
) -> None:
    """The loop closes: warn, describe, and the next step is quiet.

    `Session.describe_material` rebinds the library rather than mutating it (a
    `MaterialLibrary` is a value), which is why the session sees the answer
    immediately and the file makes it survive a restart.
    """
    from nanofab_v3.ui.session import Session

    session = Session()
    session.library = session.library  # explicit: the session owns a value
    described = MissingMaterial(material_id=PARTICLE_ID).draft(rates={WET_ETCH: 0.4})

    session.describe_material(described)

    assert PARTICLE_ID in session.library
    assert not unknown_materials(session.library, contaminated.materials)
    assert (user_root / f"{PARTICLE_ID}.json").is_file()


def test_the_session_reports_what_its_head_revision_cannot_answer_for(
    user_root: Path,
) -> None:
    """What the shell reads to decide whether to raise the dialog at all."""
    from nanofab_v3.ui.session import Session

    session = Session()
    session.run("substrate.select", {"material": str(SILICON), "surface": 40.0})
    assert not session.unknown_materials()

    with pytest.warns(UnknownMaterialWarning):
        session.run("deposit.evaporate", {"material": "tungsten", "thickness": 10.0})

    assert session.unknown_materials().ids == ("tungsten",)


# -- the dialog, where a headless runner has Qt -------------------------------


@pytest.fixture(scope="module")
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_form_holds_the_answers_and_the_material_type_validates_them(qt_app) -> None:
    """ADR-0001's line through a dialog: the form decides nothing, it collects."""
    from nanofab_v3.ui.material_dialog import MaterialDialog

    dialog = MaterialDialog(MissingMaterial(material_id=PARTICLE_ID, seen_in="etch.wet"))
    dialog._name.setText("Chromium particle")
    dialog._rates[ICP_FLUORINE].setValue(0.0333)

    described = dialog.described()

    assert described.name == "Chromium particle"
    assert described.rate_for(ICP_FLUORINE) == 0.0333
    # A class the operator left blank stays unstated rather than becoming a zero:
    # "no entry" already means "does not move", and thirteen deliberate-looking
    # zeros would be thirteen statements nobody made.
    assert WET_ETCH not in described.rates
