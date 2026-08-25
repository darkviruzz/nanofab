"""Capabilities: named promises about sample state (plan §5.3, `CONTEXT.md`).

A capability is what v1's step-id `prerequisites` should have been. Instead of
"development is blocked until step #4 ran", a development variant says it
`requires` `"resist.exposed"` and the engine asks the revision whether it has
that. The reason it is better is the reason `CONTEXT.md` gives: *gating runs on
capabilities*, so two lithography tiers that write different fields
(`resist.exposed` vs `resist.dose`) gate their matching development without
either knowing the other exists.

Two of the three forms a capability name can take are **structural**: they are
statements about the `Structure` itself, and can therefore be checked rather
than trusted.

- `material:<id>` — that material is present.
- `<material_id>.<field>` — that material-scoped `Field` is present.
- anything else — a free-form promise the structure cannot back or refute
  (`"chamber_pumped"`, `"stage_aligned"`). Carried through untouched.

**The dot is reserved**, and that is a naming rule rather than a heuristic: plan
§5.3's own example is `resist.dose`, so a name containing a `.` is read as
`<material>.<field>` and checked against the structure. A free-form promise that
happened to contain one would be read as a field capability of a material that
does not exist, and dropped on the first commit. Free-form names do not contain
dots; `is_structural` is where the rule is applied and `of_field` is the only
thing that should ever build a dotted name.

This module is the vocabulary only. The commit gate (§4.5's sixth step) is what
applies it to a revision: it re-derives the structural ones, keeps the free-form
ones, and drops whatever the structure stopped backing — which is how a
capability disappears when the step that mattered removed its material, without
any step having to remember to retract it.

It lives in `model/` rather than in `processes/` because plan §3.6 puts
`capabilities` on the `Revision`: it is state, and both the kernel's gate and the
process contract read it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from nanofab_v3.materials import MaterialId

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance, typing only
    from nanofab_v3.model.structure import Structure

MATERIAL_PREFIX = "material:"
"""Prefix marking a capability that asserts a material's presence."""


def of_material(material: MaterialId) -> str:
    """The capability `"material:<id>"` — that material exists in the structure."""
    return f"{MATERIAL_PREFIX}{material}"


def of_field(material: MaterialId, name: str) -> str:
    """The capability `"<material>.<field>"` — that scoped `Field` exists.

    Plan §5.3's own example: ideal exposure provides `resist.exposed`, physical
    exposure provides `resist.dose`, and the two development variants require the
    one they can consume.
    """
    return f"{material}.{name}"


def is_structural(capability: str) -> bool:
    """Whether the structure itself can decide this capability.

    True for `material:<id>` and for any dotted name, which is read as
    `<material>.<field>` — see the module docstring: the dot is reserved, so a
    free-form promise must not contain one.
    """
    return capability.startswith(MATERIAL_PREFIX) or "." in capability


def backed_by(structure: "Structure", capability: str) -> bool:
    """Whether `structure` carries what `capability` claims.

    Free-form capabilities are not structural, so the structure has nothing to
    say about them and this returns `True`: the gate must not drop a promise it
    cannot check. Only what can be refuted is refuted.
    """
    if capability.startswith(MATERIAL_PREFIX):
        return capability[len(MATERIAL_PREFIX) :] in structure.phi
    if "." in capability:
        material, _, name = capability.partition(".")
        return structure.has_field((name, MaterialId(material)))
    return True


def derived(structure: "Structure") -> frozenset[str]:
    """Every structural capability `structure` backs right now.

    The mechanical half of the gate's capability update: a step that spin-coats
    resist provides `material:resist` whether or not it thought to say so, and a
    step that dissolves it retracts the capability by the same mechanism. What a
    step still has to declare is the part the geometry cannot see.
    """
    found = {of_material(material) for material in structure.materials}
    found |= {
        of_field(key.material, key.name)
        for key in structure.fields
        if key.material is not None
    }
    return frozenset(found)


def unmet(required: Iterable[str], available: Iterable[str]) -> tuple[str, ...]:
    """The required capabilities `available` does not contain, sorted."""
    return tuple(sorted(set(required) - set(available)))
