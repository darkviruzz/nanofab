"""The material library: rates, yields, develop and dissolve models (plan §3.4).

Layer 1 of plan §13's pyramid for the one module that holds no geometry at all.
What is worth asserting here is not arithmetic but the *contracts* the process
layer relies on — that a missing rate is zero rather than an error, that an
unknown process class is an error rather than zero, and that `MaterialType`
answers questions about materials the recipe never mentioned.
"""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3.materials import (
    DEPOSIT,
    DRY_ETCH,
    ION_BEAM,
    METAL,
    OXIDE,
    RESIST,
    SILICON,
    UNDERLAYER,
    WET_ETCH,
    DevelopModel,
    DissolveModel,
    MaterialLibrary,
    MaterialType,
    SputterResponse,
    didactic_library,
)


def test_a_material_with_no_rate_for_a_process_simply_does_not_move() -> None:
    """The rule mask behaviour rests on (plan §4.2), stated at the library.

    A hard mask is not a special case anywhere in the solver; it is a material
    whose rate table has no entry for the process being run. If this returned an
    error instead, every step would have to enumerate the materials it does not
    attack.
    """
    inert = MaterialType(material_id="alumina", name="Alumina")

    assert inert.rate_for(WET_ETCH) == 0.0
    assert inert.rate_for(ION_BEAM, default=0.3) == 0.3


def test_an_unknown_process_class_is_an_error_at_both_ends() -> None:
    """A typo in a rate key must not become a silent zero.

    The other half of the rule above: "no entry" means "does not move", so a
    misspelt key would be indistinguishable from a deliberate omission and a
    material would quietly stop etching.
    """
    with pytest.raises(ValueError, match="unknown process class"):
        MaterialType(material_id="x", name="X", rates={"plasma_etch": 1.0})
    with pytest.raises(ValueError, match="unknown process class"):
        MaterialType(material_id="x", name="X").rate_for("plasma_etch")


def test_a_negative_rate_is_rejected() -> None:
    """Direction is the process's business (`sign` in the speed field), not the material's."""
    with pytest.raises(ValueError, match="non-negative"):
        MaterialType(material_id="x", name="X", rates={WET_ETCH: -1.0})


def test_develop_rate_rises_with_dose_and_saturates_at_the_clearing_dose() -> None:
    """`develop_rate(dose)` — plan §3.4's named model, as a contrast curve."""
    model = DevelopModel(clearing_dose=100.0, clear_rate=20.0, dark_rate=0.1, contrast=4.0)

    rates = model.rate(np.array([0.0, 50.0, 100.0, 400.0]))

    assert rates[0] == pytest.approx(0.1)  # unexposed resist still creeps
    assert rates[2] == pytest.approx(20.0)
    assert rates[3] == pytest.approx(20.0)  # saturated, not extrapolated
    assert 0.1 < rates[1] < 20.0
    assert np.all(np.diff(rates) >= 0.0)
    assert model.bound == pytest.approx(20.0)


def test_contrast_is_what_separates_the_two_fidelity_tiers() -> None:
    """A high-gamma resist approaches the ideal tier's step function.

    Not a curiosity: it is the honest statement of what "ideal development" is —
    this same model with infinite contrast — and it is why the two tiers can
    share a `Structure` and differ only in which field they read (plan §3.3).
    """
    soft = DevelopModel(clearing_dose=100.0, clear_rate=20.0, dark_rate=0.0, contrast=1.0)
    hard = DevelopModel(clearing_dose=100.0, clear_rate=20.0, dark_rate=0.0, contrast=16.0)

    half = 50.0
    assert soft.rate(half) == pytest.approx(10.0)
    assert hard.rate(half) < 0.001


def test_a_negative_tone_resist_dissolves_where_it_was_not_exposed() -> None:
    """Tone is a property of the material, not of the development step."""
    negative = DevelopModel(clearing_dose=100.0, clear_rate=10.0, dark_rate=0.0, tone="negative")

    assert negative.rate(0.0) == pytest.approx(10.0)
    assert negative.rate(100.0) == pytest.approx(0.0)


def test_a_material_without_a_develop_model_does_not_develop() -> None:
    """Zero, not an error — a developer bath is applied to the whole sample."""
    metal = MaterialType(material_id="metal", name="Metal")

    assert np.all(metal.develop_rate(np.array([0.0, 500.0])) == 0.0)


def test_insolubility_is_the_absence_of_a_model_and_not_a_zero_rate() -> None:
    """"The bath does not attack this" and "it attacks it slowly" are different.

    A lift-off depends on the difference: the metal must survive a bath that the
    resist does not, and a zero-rate `DissolveModel` would make the metal
    *technically* soluble in a way the ideal tier's set operation cannot express.
    """
    resist = MaterialType(
        material_id="resist", name="Resist", dissolve=DissolveModel(solvent="acetone", rate=40.0)
    )
    metal = MaterialType(material_id="metal", name="Metal")

    assert resist.dissolves_in("acetone")
    assert not resist.dissolves_in("developer")
    assert not metal.dissolves_in("acetone")
    assert resist.dissolve_rate("acetone") == pytest.approx(40.0)
    assert metal.dissolve_rate("acetone") == 0.0


def test_the_sputter_response_carries_the_two_numbers_the_flux_model_needs() -> None:
    """The material owns its yield curve; `processes.rates` converts it (plan §5.4)."""
    response = SputterResponse(rise=2.0, fall=1.0)

    assert response.fall / response.rise == pytest.approx(0.5)  # the peak, cos(theta) = 1/2
    with pytest.raises(ValueError, match="positive"):
        SputterResponse(rise=0.0)


# -- the library --------------------------------------------------------------


def test_the_library_refuses_a_material_it_does_not_know() -> None:
    """Lookup raises; a defaulted `MaterialType` would produce a plausible, wrong answer."""
    library = didactic_library()

    with pytest.raises(KeyError, match="no MaterialType"):
        library["tungsten"]
    assert library.get("tungsten") is None
    assert SILICON in library


def test_the_library_keys_have_to_match_their_entries() -> None:
    """A mis-keyed entry would answer for the wrong material, silently."""
    with pytest.raises(ValueError, match="does not match entry id"):
        MaterialLibrary({"gold": MaterialType(material_id="metal", name="Metal")})


def test_blanket_rates_are_restricted_to_the_materials_actually_present() -> None:
    """A step never carries a rate for a material the sample does not contain."""
    library = didactic_library()

    rates = library.blanket_rates(WET_ETCH, {SILICON: None, OXIDE: None})

    assert set(rates) == {SILICON, OXIDE}
    assert rates[OXIDE] > 0.0
    assert rates[SILICON] == 0.0  # the wet etch stops at the interface — S2 depends on it


def test_the_didactic_set_carries_the_contrasts_the_scenarios_need() -> None:
    """The library's numbers are didactic; their *ratios* are the physics.

    Each assertion here is a scenario's precondition, which is why they are worth
    pinning: S1 needs a resist that dissolves and a metal that does not, S2 needs
    an etchant that attacks the oxide and not the wafer, S4 needs an underlayer
    that clears faster than the imaging resist.
    """
    library = didactic_library()

    assert library[RESIST].dissolves_in("acetone")
    assert not library[METAL].dissolves_in("acetone")
    assert library[OXIDE].rate_for(WET_ETCH) > library[SILICON].rate_for(WET_ETCH) == 0.0
    assert library[UNDERLAYER].develop.clear_rate > library[RESIST].develop.clear_rate
    assert library[UNDERLAYER].develop.contrast < library[RESIST].develop.contrast
    assert library[METAL].rate_for(DEPOSIT) > 0.0
    assert library[RESIST].rate_for(ION_BEAM) > library[OXIDE].rate_for(ION_BEAM)
    assert library[RESIST].rate_for(DRY_ETCH) < library[SILICON].rate_for(DRY_ETCH)


def test_a_library_is_extended_without_being_mutated() -> None:
    """`with_entry` returns a new library — the same value-object rule as `Structure`."""
    library = didactic_library()

    extended = library.with_entry(MaterialType(material_id="gold", name="Gold"))

    assert "gold" in extended and "gold" not in library
    assert len(extended) == len(library) + 1
