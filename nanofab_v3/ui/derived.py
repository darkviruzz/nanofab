"""What a parameter's marker value resolves to, and where it came from (handoff R1).

Three places in this repository now use the same convention — a parameter whose
default is a real number cannot say *"I did not choose"*, so a marker says it:

| marker | means |
| --- | --- |
| `tone = ""` | from the resist's develop model (E13) |
| `material = ""`, `surface = 0`, `roughness = 0` | from the substrate preset (E2, E30) |
| `center = 0`, `period = 0`, `grating_center = 0` | from the domain (E33) |

The convention works and the handoff's R1 is about what it costs: **the operator
cannot see the resolved value until after the step has run**, in the log, which
is after the mistake. E13's `tone` was worse than that — two pieces of prose said
the material decided it, and nothing did, for four milestones.

So this module answers "what will that 0 turn into, and who decided" *before* the
step runs. Qt-free, because it is a computation: the form displays what this
returns and decides nothing. Every answer names its source, because "90 nm" is a
number and "90 nm, from the resist's spin curve at 3000 rpm" is an explanation —
and the second is what makes a wrong number diagnosable.

It never raises. A half-typed value in a spin box is a normal state for a form to
be in, and a hint is not worth an exception; a parameter this cannot answer for
simply has no hint.
"""

from __future__ import annotations

from typing import Any, Mapping

from nanofab_v3.materials import MaterialLibrary, MaterialId
from nanofab_v3.model.grid import Grid


def derived_hints(
        step_id: str,
        params: Mapping[str, Any],
        *,
        library: MaterialLibrary | None = None,
        grid: Grid | None = None,
) -> dict[str, str]:
    """`{parameter: what it resolves to and why}` for the markers in `params`.

    Only for parameters that are *currently* holding their marker: a stated value
    needs no explanation, and hinting at one anyway would suggest it was going to
    be replaced.
    """
    try:
        return _hints(step_id, dict(params), library, grid)
    except Exception:  # pragma: no cover - a hint is never worth an exception
        return {}


def _hints(
        step_id: str,
        params: dict[str, Any],
        library: MaterialLibrary | None,
        grid: Grid | None,
) -> dict[str, str]:
    hints: dict[str, str] = {}
    if step_id == "resist.spin_coat":
        hints.update(_spin_coat(params, library))
    if step_id.startswith("develop."):
        hints.update(_develop(params, library))
    if step_id.startswith("litho.") and grid is not None:
        hints.update(_litho(params, grid))
    if step_id == "substrate.select":
        hints.update(_substrate(params))
    return hints


def _spin_coat(params: dict[str, Any], library: MaterialLibrary | None) -> dict[str, str]:
    """E17's half of R1: the thickness the curve gives, and the clamp message.

    The clamp is here rather than only in the log because that is R1's actual
    finding: a spin speed outside the measured range reached the operator *after*
    the step, which is after the mistake.
    """
    if library is None:
        return {}
    material = MaterialId(str(params.get("material", "") or ""))
    entry = library.get(material)
    if entry is None or entry.spin_curve is None:
        return {
            "spin_speed": (
                f"no spin curve for {material or 'this material'} — add one to its file, "
                "or choose the ideal spin-coat step"
            )
        }
    speed = float(params.get("spin_speed", 0.0) or 0.0)
    from nanofab_v3.processes.lithography import spun_thickness

    thickness, clamped = spun_thickness(library, material, speed)
    where = f"from {material}'s spin curve at {speed:.0f} rpm"
    if clamped:
        low, high = entry.spin_curve.speed_range
        return {
            "spin_speed": (
                f"{thickness:.1f} nm, {where} — **clamped**: the curve was measured "
                f"between {low:.0f} and {high:.0f} rpm"
            )
        }
    return {"spin_speed": f"{thickness:.1f} nm, {where}"}


def _develop(params: dict[str, Any], library: MaterialLibrary | None) -> dict[str, str]:
    """E13's half of R1, the one that was a live bug for four milestones."""
    if library is None or str(params.get("tone", "") or "").strip():
        return {}
    material = MaterialId(str(params.get("material", "") or ""))
    entry = library.get(material)
    if entry is None or entry.develop is None:
        return {"tone": f"no develop model for {material or 'this material'} — type a tone"}
    return {
        "tone": (
            f"{entry.develop.tone}, from {material}'s own develop model "
            f"(D0 {entry.develop.clearing_dose:.0f} mJ/cm^2)"
        )
    }


def _litho(params: dict[str, Any], grid: Grid) -> dict[str, str]:
    """E33's markers: what the domain decides when nobody chose."""
    from nanofab_v3.processes.lithography import domain_defaults

    resolved = domain_defaults(
        grid,
        {
            "center": params.get("center", 0.0) or 0.0,
            "grating_center": params.get("grating_center", 0.0) or 0.0,
            "period": params.get("period", 0.0) or 0.0,
        },
    )
    grating = str(params.get("pattern", "")) == "grating"
    words = {
        "center": "the middle of the domain",
        "grating_center": "the middle of the domain",
        "period": "a third of the domain width, so three lines",
    }
    hints = {
        name: f"{value:.1f} nm, {words[name]}" for name, value in resolved.items()
    }
    # A window has no period and a grating has no window centre; hinting at the
    # one the pattern does not use is noise that trains people to ignore hints.
    for name in ("grating_center", "period") if not grating else ("center",):
        hints.pop(name, None)
    return hints


def _substrate(params: dict[str, Any]) -> dict[str, str]:
    """E2's and E30's markers: what the chosen preset drives (handoff R8)."""
    from nanofab_v3.processes.substrate import PRESETS_BY_KEY

    preset = PRESETS_BY_KEY.get(str(params.get("preset", "") or "").strip())
    if preset is None:
        return {}
    label = f"from the {preset.key} preset"
    hints: dict[str, str] = {}
    if not str(params.get("material", "") or "").strip():
        hints["material"] = f"{preset.material}, {label}"
    if not str(params.get("form_factor", "") or "").strip():
        hints["form_factor"] = f"{preset.form_factor}, {label}"
    if float(params.get("surface", 0.0) or 0.0) <= 0.0:
        hints["surface"] = f"{preset.surface_nm:.0f} nm, {label}"
    if float(params.get("roughness", 0.0) or 0.0) <= 0.0:
        hints["roughness"] = f"Ra {preset.roughness_nm:.2g} nm, {label}"
    if float(params.get("thickness", 0.0) or 0.0) <= 0.0 and preset.thickness_mm:
        hints["thickness"] = f"{preset.thickness_mm:.3g} mm, {label}"
    if float(params.get("diameter", 0.0) or 0.0) <= 0.0 and preset.diameter_mm:
        hints["diameter"] = f"{preset.diameter_mm:.4g} mm, {label}"
    if float(params.get("size_x", 0.0) or 0.0) <= 0.0 and preset.side_mm:
        hints["size_x"] = f"{preset.side_mm:.4g} mm, {label}"
    if float(params.get("size_y", 0.0) or 0.0) <= 0.0 and preset.side_mm:
        hints["size_y"] = f"{preset.side_mm:.4g} mm, {label}"
    return hints


__all__ = ["derived_hints"]
