"""The v2 structure model: `Grid`, `Structure`, `Field` types (plan §3).

`Grid` is the sole spatial authority, `Structure` the single stored geometry
truth. Nothing in here knows about processes, rendering or Qt.
"""

from __future__ import annotations

from nanofab_v3.model.field import FieldKey, FieldSpec
from nanofab_v3.model.grid import PHI_DTYPE, Grid
from nanofab_v3.model.structure import EMPTY, Structure

__all__ = ["EMPTY", "PHI_DTYPE", "FieldKey", "FieldSpec", "Grid", "Structure"]
