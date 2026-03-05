# 7. Chain of Events: Current Mock Recipe (8-step Lithography + Lift-Off)

This section documents the **demonstrated** chain and the intended state mutations. This recipe is a template: the architecture must support larger chains and additional inspection insertions.

## Step 1 — Substrate Selection (initial step is `ready`)
**Action**
- User defines substrate: material + geometry.

**State Mutation**
- Initializes `SampleState` revision 0/1.
- `substrate` populated; sample becomes “loaded”.

**UI**
- Wafer visualization renders substrate block.
- Step 2 unlocks (`ready`).

---

## Step 2 — Cleaning
**Action**
- Choose cleaning method and duration.

**State Mutation**
- Updates substrate facet/notes/state marker: “Cleaned”.
- Optionally adds artifact (log/report) (future).

**UI**
- Step 3 unlocks.

---

## Step 3 — Resist Coating (AZ10XT)
**Action**
- Configure spin program (RPM/time), target thickness, EBR, softbake config.

**Validation / Mismatch**
- Compare predicted thickness (model) vs target thickness.
- If mismatch exceeds threshold, show warning + offer “Auto-tune”.

**State Mutation**
- Pushes new resist `Layer` to `stack.layers`.
- Adds artifact: spin curve/validation plot (mock).

**UI**
- Cross-section shows resist layer.
- Artifacts panel shows new artifact.

---

## Step 4 — Soft Bake
**Action**
- Configure temperature/time.

**State Mutation**
- Updates resist layer metadata (`facets.process.softbake` or layer property): “Soft baked”.

**UI**
- Step 5 unlocks.

---

## Step 5 — Projection Exposure
**Action**
- Configure dose and focus.
- Apply mask (in the mock: center region exposed).

**State Mutation (Mock Geometry Abstraction)**
- Converts uniform resist representation into **three segments**:
  - left: unexposed resist
  - center: exposed resist (marked)
  - right: unexposed resist

**UI**
- Cross-section shows segmented resist; center region has different shade/state.

---

## Step 6 — Development
**Action**
- Configure developer time.

**State Mutation**
- Removes exposed resist region (center segment becomes “void”).
- In state terms: resist coverage becomes patterned with openings.

**UI**
- Cross-section shows trench/opening down to substrate.

---

## Step 7 — Thin Film Deposition (Cr)
**Action**
- Configure thickness, rate, base pressure (future).

**State Mutation**
- Adds new metal layer to the stack.
- Logical meaning: blanket deposition over both resist and open trench.
- Artifact: thickness/profilometry report (future; mock optional).

**UI**
- Cross-section shows metal layer.

---

## Step 8 — Lift-Off
**Action**
- Removes sacrificial resist and metal sitting on top of resist.

**State Mutation (Mock Logic)**
- Deletes resist layer.
- Metal layer becomes patterned: metal remains only where deposition contacted substrate (i.e., in the developed opening).

**UI**
- Final structure: patterned Cr feature on fused silica substrate.

---
