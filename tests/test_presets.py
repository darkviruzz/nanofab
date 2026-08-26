"""Presets, and the rule about overwriting what somebody typed (M7, item 2).

The handoff asks for this generically rather than as a substrate special case,
because resist presets and etch recipes are coming and "may a preset overwrite
this field" should be answered once. So `ui.presets` knows nothing about
substrates: a `PresetOption` is a labelled bundle of parameter values and
`apply_preset` splits it into what may be written silently and what has to be
asked about.

The rule, and the whole of it: **a field the operator changed by hand is theirs.**
The tests below are mostly about the edges of that sentence, because those are
where a preset stops helping and starts being fought.
"""

from __future__ import annotations

import pytest

from nanofab_v3.processes.substrate import SUBSTRATE_PRESETS
from nanofab_v3.ui import presets


@pytest.fixture
def option() -> presets.PresetOption:
    return presets.PresetOption(
        key="demo",
        label="Demo",
        section="Wafers",
        values={"material": "fused_silica", "thickness": 1.0, "domain_width": 1200.0},
    )


@pytest.fixture
def form() -> dict[str, object]:
    return {"material": "silicon", "thickness": 0.0, "domain_width": 0.0, "surface": 40.0}


def test_an_untouched_field_is_filled_in_silently(option, form) -> None:
    """The common case: a preset that helps does not ask permission to help."""
    plan = presets.apply_preset(option, form, touched=())

    assert plan.silent == option.values
    assert not plan.needs_asking
    assert plan.resolved()["material"] == "fused_silica"


def test_a_field_the_operator_changed_is_a_question(option, form) -> None:
    """M7's rule: "überschreibt manuell geänderte Folgefelder nur nach Rückfrage"."""
    form["thickness"] = 0.525

    plan = presets.apply_preset(option, form, touched={"thickness"})

    assert plan.conflicts == {"thickness": (0.525, 1.0)}
    assert plan.needs_asking
    assert "keep 0.525" in plan.describe()[0]
    # Saying nothing keeps what is there — the right way round for a question
    # about losing work.
    assert "thickness" not in plan.resolved()
    assert plan.resolved(["thickness"])["thickness"] == 1.0


def test_a_touched_field_the_preset_agrees_with_is_not_a_question(option, form) -> None:
    """There is nothing to lose, so asking would only teach people to click yes."""
    form["thickness"] = 1.0

    plan = presets.apply_preset(option, form, touched={"thickness"})

    assert not plan.needs_asking
    assert plan.silent["thickness"] == 1.0


def test_spin_box_rounding_is_not_a_disagreement(option, form) -> None:
    """A form's numbers come back through a widget; 1.0 and 0.9999999999 are one answer."""
    form["thickness"] = 1.0 - 1e-12

    assert not presets.apply_preset(option, form, touched={"thickness"}).needs_asking


def test_a_parameter_the_form_does_not_have_is_reported_not_dropped(option) -> None:
    """A preset that silently sets nothing looks exactly like one that worked."""
    plan = presets.apply_preset(option, {"material": "silicon"}, touched=())

    assert plan.missing == ("domain_width", "thickness")
    assert set(plan.silent) == {"material"}


def test_touched_is_not_the_same_fact_as_differs_from_the_default(option, form) -> None:
    """Why `touched` is passed in rather than inferred.

    Two forms holding the same value, one because a person typed it and one
    because a previous preset filled it in. Only the first is a question, and no
    comparison of values can tell them apart.
    """
    form["thickness"] = 0.525

    typed = presets.apply_preset(option, form, touched={"thickness"})
    filled = presets.apply_preset(option, form, touched=())

    assert typed.needs_asking
    assert not filled.needs_asking


# -- the substrate adapter (E2, E3) -------------------------------------------


def test_the_substrate_options_are_grouped_and_in_the_tables_order() -> None:
    """E3's two-section dropdown. The order is the table's, decided once."""
    options = presets.options_for("substrate.select", "preset")
    sections = presets.grouped(options)

    assert list(sections) == ["Wafers", "Mask blanks"]
    assert len(options) == len(SUBSTRATE_PRESETS)
    assert [option.key for option in options] == [preset.key for preset in SUBSTRATE_PRESETS]


def test_a_substrate_option_fills_in_the_substrate_and_the_domain(option) -> None:
    """E2: one choice drives both, which is what makes them unable to disagree."""
    by_key = {o.key: o for o in presets.options_for("substrate.select", "preset")}

    mask = by_key["mask_6025"]

    assert mask.values["material"] == "fused_silica"
    assert mask.values["form_factor"] == "mask"
    assert mask.values["thickness"] == 6.35  # mm, the unit the form's ParamSpec declares
    assert mask.values["size_x"] == mask.values["size_y"] == 152.0
    assert mask.values["diameter"] == 0.0  # a blank is not round
    assert mask.values["domain_width"] == 2400.0 and mask.values["spacing"] == 2.0


def test_a_step_with_no_presets_gets_none() -> None:
    """The registry is a UI fact: to a recipe the parameter is a plain string."""
    assert presets.options_for("etch.wet", "duration") == ()
    assert presets.options_for("substrate.select", "material") == ()
