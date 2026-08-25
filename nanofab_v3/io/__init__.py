"""Persistence and exchange (plan §9).

Empty in M0 by design. One format serves saving, the replay cache and
external-solver exchange: per revision a compressed `.npz` of the `phi_*` and
`Field` arrays plus a JSON manifest (`schema_id: "structure.v2"`, `Grid`,
material ids, capabilities, history, content hashes), with `ArtifactRef`s staying
URI-referenced files. Milestone M4.
"""

from __future__ import annotations

__all__: list[str] = []
