"""Every step explains itself, and the list can be searched (M8, E10 and E11).

Two decisions that turn out to be one feature. E10 puts a long description at
each registration — one source, in the code, beside the thing it describes — and
E11 makes the step list searchable over *name and description*. The second is
only worth having because of the first: a list you can search for "undercut" or
"hard mask" needs steps that say what they do.

What is checked here is mostly that the texts exist and answer the three
questions E10 asks of them (what it does, what the fields mean, what it needs),
plus the one structural rule that makes a language catalog possible later without
touching the registry.
"""

from __future__ import annotations

import pytest

from nanofab_v3 import text
from nanofab_v3.model import capability
from nanofab_v3.processes import FIDELITIES, builtin_registry
from nanofab_v3.processes.contract import FunctionStep, ProcessStep, StepResult


@pytest.fixture
def registry():
    return builtin_registry()


# -- E10: every step explains itself ------------------------------------------


def test_every_registered_step_has_a_real_description(registry) -> None:
    """M8's first DoD sentence, counted rather than hoped for."""
    for step in registry:
        described = registry.describe(step.step_id)
        assert described != step.display_name, step.step_id
        assert len(described) > 200, step.step_id


def test_a_description_says_what_the_step_needs(registry) -> None:
    """E10 asks for three things; this is the one a reader acts on first.

    Inspections and the substrate step are the exceptions that prove it: an
    inspection says it changes nothing, and the substrate step says it needs
    nothing because it is what everything else needs.
    """
    for step in registry:
        described = registry.describe(step.step_id)
        assert "Needs:" in described, step.step_id


def test_the_description_lives_at_the_registration_and_not_in_a_table(registry) -> None:
    """"Keine zweite Quelle" (E10). The step object carries its own text."""
    for step in registry:
        assert getattr(step, "description", "").strip(), step.step_id


def test_a_step_without_a_description_gets_its_name_rather_than_a_blank(registry) -> None:
    """And a plugin written before E10 existed still registers.

    `description` is deliberately **not** on the `ProcessStep` protocol: that
    protocol is `runtime_checkable`, so a member added there would make every
    plugin without one fail `isinstance` and be refused registration.
    """
    quiet = FunctionStep(
        step_id="plugin.quiet",
        display_name="A plugin from before M8",
        fidelity="ideal",
        schema=(),
        required=frozenset(),
        provided=frozenset(),
        run_function=lambda ctx: StepResult(structure=ctx.structure),
    )
    registry.register(quiet)

    assert isinstance(quiet, ProcessStep)
    assert registry.describe("plugin.quiet") == "A plugin from before M8"


# -- E10's other half: the indirection, not the catalog -----------------------


def test_a_catalog_can_replace_the_text_without_touching_the_registry(registry) -> None:
    """The whole of E10's "dünne Übersetzungs-Indirektion".

    Backlog B10 says not to build the catalog until there is a second language,
    and it is right; what is not free later is retrofitting 31 call sites. So the
    key exists now and the catalog does not.
    """
    english = registry.describe("etch.wet")
    previous = text.set_catalog(
        text.MappingCatalog({"step.etch.wet.description": "Nassätzen im Bad."})
    )
    try:
        assert registry.describe("etch.wet") == "Nassätzen im Bad."
        # A key the catalog does not know falls back to English, not to the key.
        assert registry.describe("etch.rie") != "step.etch.rie.description"
    finally:
        text.set_catalog(previous)

    assert registry.describe("etch.wet") == english


def test_the_key_is_structural_so_fixing_a_typo_does_not_break_a_translation() -> None:
    """Using the English text as its own key would be the alternative, and worse."""
    assert text.step_description("etch.wet", "x") == "x"
    previous = text.set_catalog(text.MappingCatalog({"step.etch.wet.description": "y"}))
    try:
        assert text.step_description("etch.wet", "a completely different english text") == "y"
    finally:
        text.set_catalog(previous)


# -- E11: the filter ----------------------------------------------------------


def test_the_search_reaches_the_descriptions(registry) -> None:
    """Which is why E10 comes first — the interesting words are not in the names."""
    undercutting = {step.step_id for step in registry.matching("undercut")}

    assert "etch.wet" in undercutting
    assert "etch.rie" in undercutting
    assert "deposit.evaporate" not in undercutting
    # ... and a word that appears in no name at all still finds its steps.
    assert {step.step_id for step in registry.matching("hard mask")}


def test_the_fidelity_tags_filter_and_all_of_them_is_the_same_as_none(registry) -> None:
    ideal = {step.step_id for step in registry.matching(fidelities=["ideal"])}

    assert "develop.ideal" in ideal and "develop.rate" not in ideal
    assert len(registry.matching(fidelities=FIDELITIES)) == len(registry)
    assert len(registry.matching(fidelities=[])) == len(registry)


def test_search_and_tags_combine(registry) -> None:
    """Both filters narrow, and they narrow the same list rather than two lists."""
    text_only = {step.step_id for step in registry.matching("develop")}
    both = {step.step_id for step in registry.matching("develop", fidelities=["didactic"])}

    assert "develop.ideal" in text_only and "develop.ideal" not in both
    assert both == {"develop.rate", "litho.expose_dose"}
    assert both < text_only


def test_the_filter_can_compose_with_the_gate_rather_than_contradict_it(registry) -> None:
    """A filter hides; the gate greys out. Asking for both is asking for runnable steps."""
    everything = {step.step_id for step in registry.matching("wafer")}
    on_nothing = {step.step_id for step in registry.matching("wafer", capabilities=frozenset())}

    assert "substrate.select" in everything and len(everything) > 1
    # With nothing on the sample the substrate step is the only runnable one, so
    # asking for both filters leaves exactly it.
    assert on_nothing == {"substrate.select"}
    # "undercut" is in several etch descriptions and in no step that can run on
    # an empty sample, so composing the two filters leaves nothing at all.
    assert registry.matching("undercut", capabilities=frozenset()) == ()
    assert registry.matching("undercut", capabilities={capability.DOMAIN})


def test_a_search_that_matches_nothing_matches_nothing(registry) -> None:
    assert registry.matching("photolithostereography") == ()


# -- the panel ----------------------------------------------------------------


@pytest.fixture(scope="module")
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_step_list_filters_but_keeps_showing_what_is_blocked(qt_app, registry) -> None:
    """Filtering and gating are different things and must stay different.

    Hiding what the sample cannot run would answer "why can I not do this?" by
    removing the question. So a filtered-out step is gone and a blocked one is
    grey with a reason.
    """
    from nanofab_v3.ui.panels import StepListPanel

    panel = StepListPanel(registry)
    panel.refresh(frozenset())  # nothing on the sample: everything but the substrate blocked

    assert "etch.wet" in panel.visible_step_ids()  # shown, and grey

    panel.search.setText("undercut")

    assert "etch.wet" in panel.visible_step_ids()
    assert "deposit.evaporate" not in panel.visible_step_ids()

    panel.search.setText("")
    panel.tags["didactic"].setChecked(False)
    panel.tags["physical"].setChecked(False)

    assert "develop.ideal" in panel.visible_step_ids()
    assert "develop.rate" not in panel.visible_step_ids()


def test_choosing_a_step_shows_its_description_where_it_is_about_to_be_run(
    qt_app, registry
) -> None:
    """M8's DoD: every step explains itself, next to its own parameters."""
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    window._on_step_chosen("strip.lift_off")

    assert "Lift-off" in window.form.description.text()
    assert "connectivity question" in window.form.description.text()
    assert window.form.title.text().startswith("Lift-off")
