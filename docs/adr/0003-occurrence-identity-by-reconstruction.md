# ADR-0003: Occurrence identity is reconstructed, not stored

- Status: accepted (design interview 2026-08-24/25) — implementation pending
- Detail: `docs/plans/v2-structure-model.md` §3.5

v2 stores two material tiers only: the `MaterialType` library and the per-material
geometry/fields. A **Materialvorkommen (occurrence)** — a connected region of one
material — is a *derived view*, computed per revision by connected-component
labelling; its identity across revisions is reconstructed by overlap matching
against the parent revision, yielding an explicit lineage (split/merge/vanish)
report. No occurrence IDs are stored in the structure.

Rejected alternative: stored per-occurrence identity (an ID field per cell).
Stored identity is undefined exactly where it matters — an etch splitting a film in
two, or ALD pinch-off merging two films, forces an arbitrary bookkeeping choice,
and it is precisely this class of topology-change bookkeeping the level-set
representation (ADR-0002) was chosen to eliminate. Reconstruction gives a
defensible answer ("#7 split into #7a/#7b") and turns topology changes into
findings. Measured costs at 1 nm/cell: label 2.3 ms, lineage matching 5.2 ms —
paid only when asked (and once per commit), not carried by every operation.
Lift-off needs no identity at all: "which metal detaches" is substrate-support
connectivity, a 2.9 ms query.
