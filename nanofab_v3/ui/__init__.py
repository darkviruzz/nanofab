"""Rendering and the application shell (plan §10, ADR-0001).

Rendering is a **consumer** of the kernel and never the other way round. The
package is split along that sentence, and the split is the structural answer to
ADR-0001's central finding — that v1 let `QPainterPath` be the working geometry,
so every process decision was made by a renderer:

- `scene` — `SceneSnapshot` v2. numpy, nm and the kernel; **no Qt**. Anything
  that decides geometry lives here or below.
- `session` — one interactive run: a recipe being built one step at a time, the
  chain it produced, and save/load. **No Qt** either, so "what happens when you
  press Run" is testable without a display.
- `canvas` — paints a `SceneSnapshot`. Maps nm to pixels and fills; builds
  throwaway `QPainterPath`s and reads none of them back.
- `panels` — the v0.2.0 shell's step list, parameter form, revision list and run
  log, with gating rewired from step ids to capabilities.
- `window` — wiring, and nothing else.

Importing `nanofab_v3.ui` pulls in nothing from Qt: `scene` and `session` import
cleanly on a machine with no PySide6, which is what lets the test suite assert
the render model and the interactive session on a headless runner. `canvas`,
`panels` and `window` are the Qt half and are imported explicitly.

Run it with `python -m nanofab_v3.ui`.
"""

from __future__ import annotations

from nanofab_v3.ui.scene import (
    OVERLAY_KINDS,
    MaterialShape,
    Overlay,
    SceneSnapshot,
    build,
    surface_normals,
)
from nanofab_v3.ui.session import Session, default_grid, demo_recipe

__all__ = [
    "OVERLAY_KINDS",
    "MaterialShape",
    "Overlay",
    "SceneSnapshot",
    "Session",
    "build",
    "default_grid",
    "demo_recipe",
    "surface_normals",
]
