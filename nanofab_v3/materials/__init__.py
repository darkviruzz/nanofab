"""Material library: `MaterialType` entries and `MaterialId` keys (plan §3.4).

Pure data and small model objects — rates per process class, angle-dependent
sputter response, `develop_rate(dose)`, dissolve models. Nothing here imports
`nanofab_v3.kernel` (see `material.py`'s docstring: `kernel.motion` imports
`MaterialId` from here, so the reverse would be a cycle). The seam that turns
these models into the kernel's `SurfaceRates` and `flux.AngularYield` is
`nanofab_v3.processes.rates`.
"""

from __future__ import annotations

from nanofab_v3.materials.library import (
    ALUMINA,
    METAL,
    OXIDE,
    RESIST,
    SILICON,
    UNDERLAYER,
    MaterialLibrary,
    didactic_library,
)
from nanofab_v3.materials.material import (
    DEPOSIT,
    DEVELOP,
    DISSOLVE,
    DRY_ETCH,
    ION_BEAM,
    PROCESS_CLASSES,
    WET_ETCH,
    DevelopModel,
    DissolveModel,
    MaterialId,
    MaterialType,
    SputterResponse,
)

__all__ = [
    "ALUMINA",
    "DEPOSIT",
    "DEVELOP",
    "DISSOLVE",
    "DRY_ETCH",
    "ION_BEAM",
    "METAL",
    "OXIDE",
    "PROCESS_CLASSES",
    "RESIST",
    "SILICON",
    "UNDERLAYER",
    "WET_ETCH",
    "DevelopModel",
    "DissolveModel",
    "MaterialId",
    "MaterialLibrary",
    "MaterialType",
    "SputterResponse",
    "didactic_library",
]
