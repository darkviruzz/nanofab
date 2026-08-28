# Handoff: what M6–M9 left behind

- Written 2026-08-26, at the end of M9 — the last milestone of
  `docs/plans/m6-m9-roadmap.md`
- **Retrospective, not forward-looking.** The earlier handoffs in this directory
  say what to build next. This one collects the remarks that came up *while*
  M6–M9 were being implemented, evaluates each, and says what I would do about
  it. Nothing here is a task somebody assigned; all of it is something the work
  itself turned up.
- Full write-ups live in plan §22 (M6), §23 (M7), §24 (M8), §25 (M9), and the
  four `memory.md` entries of 2026-08-26. This file does not repeat them — it
  judges what is left over.

## 1. Where the code stands

| | end of M5 | end of M9 |
| --- | --- | --- |
| tests | 394 | **556**, 0 skipped |
| registered steps | 24 | **31** |
| process classes | 6 | **13** |
| materials | 6 in code | **11 as JSON**, none in code |
| frozen exe | 115 MB, 7/7 | 115 MiB, **7/7 in 4.7 s** |

`python -m compileall nanofab_v3 tests` is clean. All four DoDs are met. Two roadmap
*decisions* were never assigned to a milestone and are only partly built, one of
them because of a bug this document found and fixed — remark **R1** below.

Everything in this document is measured on this container unless it says
otherwise, and §23.7's warning applies throughout: a number measured on one
machine is a statement about that machine.

---

## 2. The remarks

### R1 — E13 and E17's "the material decides" clauses fell through · *one half fixed, one open*

**Observed.** The roadmap records two clauses of the same shape in §2:

- **E13**: *"Der Develop-Step liest `tone`/`clearing_dose` aus dem Resist-Material.
  Der redundante `tone`-Parameter bleibt als **Override** erhalten, wird im UI aber
  **read-only** angezeigt."*
- **E17**: *"Der `thickness`-Parameter am Spin-Coat-Step bleibt als **Override**
  erhalten und wird im UI read-only angezeigt, solange er aus der Kurve kommt
  (Muster wie E13s `tone`)."*

Neither appears in any milestone's task list in §4 — M6 was given E14/E15/E16/E17
and M8 E8–E12, and E13 was never assigned to anything. What actually shipped:

| clause | model half | UI half |
| --- | --- | --- |
| E17 (`thickness` from the spin curve) | **done in M6** | **missing** |
| E13 (`tone` from the develop model) | **was not wired at all** | **missing** |

**The E13 model half was a live bug, and this handoff is what found it.**
`_run_develop_ideal` passed `ctx["tone"]` straight through, and that parameter
defaulted to `"positive"` unconditionally — while the step's own description said
*"`tone` comes from the resist's own develop model"* and `lithography`'s module
docstring said *"The develop step reads tone and clearing dose from the resist's
`DevelopModel`"*. `DevelopModel.tone` existed, was serialised into every resist
JSON file, and was read by nobody. An operator who put a negative resist in their
own materials directory got it developed as a positive one — on the fixture in
the new test, **7080 cells left instead of 4779** — with a log line saying
"positive tone" and two pieces of documentation saying the material had decided
it.

**Fixed here**, because it is a defect rather than a feature: `tone` now defaults
to `""`, `developed_tone()` answers from the resist's `DevelopModel`, and the run
log says which of the two happened ("negative tone, from the resist" versus
"positive tone, typed"). Same convention as M6's `thickness` override and M7's
presets — **empty means take it from the model** — and unchanged for the shipped
library, where both resists are positive. `tests/test_processes.py` pins it.

**Evaluation.** The bug is the smaller half of this remark. The process finding is
that **a decision recorded in the roadmap's §2 but never written into a §4 task
list gets built only by luck** — E17's model half was in M6's list and shipped,
E13's was in nobody's and did not, and the two UI halves were in nobody's and did
not. Four DoDs passed over it because no DoD mentioned it, and two pieces of
documentation asserted the behaviour, which is what kept it invisible: the code
read as if somebody had already done it.

**Recommendation.** Build the UI half of both, together, as one widget behaviour:
when `thickness` is 0 or `tone` is empty, `ParameterForm` shows the derived value
greyed with where it came from, switching to an editable box the moment somebody
types. The spin-curve clamp message (`spin_speed` outside 1000–5000 rpm) belongs
in the same place — it currently reaches the operator only in the log, i.e. after
the mistake. And it is the same widget change R8 wants for `substrate.select`'s
preset-driven fields, so three remarks are paid for once.

For the roadmap itself: when a §2 decision has no §4 owner, that is a gap in the
plan, not a detail. Worth a pass over §2's remaining decisions before the next
milestone list is written.

### R2 — `seeded_distance` is wrong by up to a cell at a concave corner · *leave it, but know it*

**Observed.** M9's rebuilt union front adds the nearest interface cell's sub-cell
offset as a scalar along a straight EDT ray. That is exact where the surface is
locally planar and wrong where it is not: measured at the one concave corner in
the reproduction case — where the speck's dome emerges through the resist plane —
the field reads −1.7 nm one cell in against a true −0.9, i.e. `|grad(phi)| = 1.97`
across one step. The reference EDT reads 0.01–0.16 at the same cells, so this is
an artifact and not a real kink.

**Evaluation.** Bounded by one cell, local to concave corners, and it does not
move the interface (the interface cells keep `min_m phi[m]` bit-identically).
Nothing in 555 tests moved because of it. The principled fix is a sub-cell
fast-marching seed instead of EDT-plus-offset; the cheap fix — clamping the result
to within half a cell of the plain mask EDT — was tried and measured: it costs a
second full transform (7.9 ms, i.e. **double** `union_front`) and takes the worst
corner from 0.97 to 0.59. That is a bad trade for a function called every
sub-step.

**Recommendation.** Leave it, and revisit only if a geometry with many concave
corners on a coarse grid starts producing gate warnings. The place to look is
`motion.seeded_distance`, and the docstring says so.

### R3 — The occurrence labeller is two remarks that are one module · *worth doing*

This is the one place where remarks from two different milestones turned out to
describe the same thing, and where **the measurement corrected the remark**.

**Observed (M7, §23.7).** On a deeper domain the dominant cost is the commit gate,
and inside it `occurrences.label_occurrences`, which scales *worse* than linearly:
5× the cells cost 6.8× the time (95 → 642 ms), where reinitialisation scales
*better* (2.8×). Five milestones of measurement had pointed at the upwind stencil;
the stencil is not the problem.

**Observed (M8).** "The grating demos leave a component count that is higher than
the picture suggests (a 200 nm grating comes back as several `fused_silica`
occurrences) … the reinitialisation at sharp corners on a 2 nm grid splits the
label field."

**Measured now, and the M8 remark was overstated.** The chromium-hard-mask grating
ends with **14** `fused_silica` occurrences, and their sizes are:

    face-connected:  [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 130951]
    8-connected:     [1, 1, 1, 130961]

The grating is **not** fragmenting. It is one body of 130 951 cells plus
**thirteen isolated single-cell specks**; ten of the thirteen are diagonal
neighbours of the bulk, which face connectivity correctly refuses to join. So the
right description is not "the label field splits" but "the etch leaves one-cell
islands, and each is promoted to an occurrence with a lineage".

**Evaluation.** Both remarks now point at `kernel/occurrences.py`, and the second
one probably explains part of the first: an occurrence carries lineage matching
against the parent, so thirteen spurious bodies are thirteen extra match
candidates on every commit. Fixing the specks is likely to help the scaling more
than optimising the labeller would.

The obvious fix — "a single cell is not an occurrence" — **collides with a real
feature**: `contamination.scatter_particles` has `radius` minimum 0.5 nm, so on a
1 nm grid a deliberately modelled particle *is* one cell, and S5 is built on
exactly that. A blanket minimum size would silently delete the thing S5 tests.

**Recommendation.** Two separable pieces, in this order:
1. **Stop creating the specks**, rather than filtering them afterwards. They come
   from the etch front leaving cells a hair below zero at a sharp corner; that is
   a question for `motion._clipped` / the gate's renormalisation, and it is
   measurable (count single-cell components before and after each step in the
   grating demo). This is the honest fix and it does not touch S5.
2. Only if 1 is not enough: make the *promotion* rule explicit rather than the
   size rule — a body is an occurrence if it was ever named by a step or exceeds
   a size, so a scattered particle qualifies by provenance and a numerical speck
   does not. That is a bigger change and needs an ADR.

Do **not** start by optimising `label_occurrences`. The measurement says the input
is wrong, not the algorithm.

### R4 — `DomainPolicy` is not in the replay cache key · *worth doing*

**Observed (M7).** `DomainPolicy` is an argument like `ReinitPolicy` and
`GateTolerances`, none of which are in ADR-0004's cache key.

**Evaluation.** Benign *today*, and the reason is specific: a resize only adds
quiet rows, the sample inside the window is the same sample, the lateral extent
never changes (E6), and even `particle.seed`'s draws are unaffected because the
RNG re-seeds per attempt. It stops being benign the moment a policy changes
geometry rather than framing — B9 (lateral extent in the UI) is exactly that day,
and B9 is in the backlog.

**Recommendation.** Add a line to ADR-0004 now, while the reasoning is fresh:
*policies are outside the key because they change framing, not physics; a policy
that changes geometry must be inside it.* One paragraph, no code. Cheaper than
rediscovering it when B9 lands and stale cache entries start replaying the wrong
domain.

### R5 — Three "obviously right" fixes were measurably wrong · *a lesson, not a task*

**Observed (M9).** The roadmap's diagnosis of the domain-edge bug was right in its
first link and its ordering, and **both of the mechanisms it proposed were
refuted by measurement**:

| proposed | what happened |
| --- | --- |
| Neumann/ghost cells in `kernel.stencil` | broke two tests that defend linear continuation; the wall column was measurably *stable* over 286 reinit passes |
| narrowing `motion._clipped` to emptied cells | `max` also keeps a material's field continuous as the front approaches; every duration failed |
| (mine) rebuilding the union over the whole domain | broke three tests; an ALD that seals a void left ten spurious pockets |

**Evaluation.** The pattern is the same all three times: a **local** fix proposed
for a **global** defect, plausible enough that nobody would ask for a measurement
first. The third one is mine and is the instructive one — it passed the
reproduction case and only a full suite run caught it, which is an argument for
running the whole suite before believing a kernel change, not the affected file.

**Recommendation.** Nothing to build. All three are recorded where they will be
found again — in `_clipped`'s docstring, in `stencil`'s, in
`tests/test_domain_edge.py`'s module docstring, and in plan §25.5 — because the
next person reading §M9 will otherwise try them again. That is the deliverable.

### R6 — The library reads a directory the tests do not · *leave it, but know it*

**Observed (M6).** `application_library()` reads the operator's writable root
(`$NANOFAB_MATERIALS`, else `$XDG_DATA_HOME/nanofab_v3/materials`) on top of the
shipped one; `didactic_library()` reads only what ships. Tests, scenarios and
`--selftest` use the second.

**Evaluation.** This is the intended split and it is right — a check whose numbers
depended on somebody's home directory would answer differently on every machine.
But it means a stray file in that directory changes what the **shell** shows and
nothing any test can see, and E15's dialog writes there by design. The first bug
report of the form "my chromium etches wrong" will be this.

**Recommendation.** No code change. Make it diagnosable instead: `--version`
already prints the roots and the count; the shell should print the same line at
startup into the run log, so a screenshot of a wrong result carries its own
provenance. Two lines.

### R7 — Assumed and invented numbers are marked, but the convention is not written down · *worth doing*

**Observed.** Three separate decisions in M6 and M8 all landed on the same rule
without ever stating it as one:

- **E18** (M6): the sputter-etch row got its own process class rather than
  overwriting `ion_beam`, because writing the table into that key would have
  changed what every existing recipe means. *A rate key is a claim about
  provenance as much as about physics.*
- **The two SiO₂ entries** (M6): where the table is silent, one takes the other's
  value and `rate_notes[class]` begins with `"Assumed, not measured."` — a
  **field**, not a comment, so a UI can say "assumed" next to the number.
- **B12** (M8): the etch-stop demo needed a selectivity nobody measured. The ratio
  (25:1) is didactic, the direction is physics (a fluorine plasma makes AlF₃,
  which is not volatile), and both files say so. *An invented number is dishonest
  when it is indistinguishable from a measured one, not when it is invented.*
- **`titania`** (M6) carries no table-derived rate at all, and its `notes` say a
  zero means "nobody stated one", not "inert".

**Evaluation.** This is now a repository-wide convention that exists only as four
precedents in four different files. B7 (calibrated rates) will arrive through this
exact seam, from a lab that has real numbers for some classes and nothing for
others — and whoever writes those files will have to infer the rule from
examples.

**Recommendation.** One section in `nanofab_v3/data/materials/README.md` stating
it: every rate is measured, assumed, or didactic; assumed and didactic say so in
`rate_notes`; absent beats invented; a new provenance means a new class, never a
reused one. It is thirty lines and it is the difference between a convention and
four coincidences.

### R8 — The UI's three rough edges · *worth doing, cheaply*

Grouped because they are independent and all small.

- **The etch-stop demo blocks the window for ~24 s.** Events are pumped between
  steps and a wait cursor is set, so the chain and log fill in, but nothing is
  clickable. Backgrounding it the way the wafer fan does was deliberately not
  done — that runner is built around wafer *positions* and one interactive chain
  is not that. **Evaluation:** correct call for one demo, wrong if demos get
  longer or if a student runs a 350 s etch of their own. **Recommendation:** the
  general fix is a cancellable chain runner, which is a real piece of work; the
  cheap one is a progress line naming the step and its elapsed time, so the
  freeze is legible. Do the cheap one now.
- **`substrate.select` has twelve parameters in one form.** **Evaluation:** the
  presets make eleven of them optional, which is the mitigation, but the form does
  not say which ones the chosen preset is driving. **Recommendation:** grey the
  preset-driven fields the way R1 wants `thickness` greyed — same widget
  behaviour, two features paid for once.
- **`ParameterForm` renders the description as Markdown in a `QLabel` with no
  scroll area**, so a long description on a small window is clipped rather than
  scrollable. **Evaluation:** the descriptions written in M8 are exactly the
  content this truncates, so E10 partly defeats itself on a small screen.
  **Recommendation:** wrap it in a `QScrollArea` with a maximum height. Small.

### R9 — Measurement hygiene: two things this repository cannot currently notice · *do next*

**Observed.**
1. **There is no CI.** `.github/workflows` does not exist. Every green suite in
   M6–M9 was green on one container, run by hand.
2. **Nine Qt tests are behind `pytest.importorskip("PySide6")`.** They run here
   because M8 installed PySide6 — the count is 0 skipped — but the guard means
   that on a machine without Qt they go back to skipping silently, which is
   precisely the failure M8 §24.1 documents (they had been skipping since M5, and
   hid an M7 regression for a day).
3. **End-to-end step timings on this VM were reproducibly non-monotonic** (the same
   spin coat: 169 ms at 0.5 µm, 283 ms at 1 µm, **129 ms at 5 µm**) while every
   component measured in isolation scaled upward. Not reproducible outside
   `run_step`; no structural difference explains it.

**Evaluation.** (1) and (2) are the same hole seen from two sides: nothing outside
a person's own terminal ever asserts that the suite is green *and complete*. The
lesson M8 paid for is already at risk of being unlearned, because the mechanism
that hid the tests is still in place and the thing that would catch it does not
exist. (3) is a different kind of problem — it means the end-to-end numbers in
§23.7 cannot support a scaling argument, and they are labelled that way, but only
in prose.

**Recommendation.**
- Add a workflow that runs `python -m compileall nanofab_v3 tests` and
  `python -m pytest`, with PySide6 installed and `QT_QPA_PLATFORM=offscreen`, and
  **fails on any skip** (`-p no:cacheprovider --strict-markers` plus a check that
  the skip count is zero). That last clause is the one that matters; a suite that
  reports skips as a number is a suite whose skips are invisible.
- Keep the `importorskip` guards. They are right for a contributor without Qt;
  what was missing was never the guard, it was the assertion that CI has no
  excuse to use it.
- Leave (3) alone. It is honestly labelled, the per-component numbers are sound,
  and chasing a VM's scheduler is not model work.

### R10 — `union_front` in 3D · *leave it, but know it*

**Observed (M9).** `union_front` is called every sub-step and now allocates a full
EDT plus an index array. At 241×301 it is **6.4 ms**, which is 2.2× *faster* than
the narrow-band reinitialisation it replaced.

**Evaluation.** The win is real in 2D and the mechanism is why: a transform does
not iterate. In 3D the index array is `ndim` full-size integer fields, so the
memory cost grows with the dimension while the reinit's did not. Nothing in this
repository runs a 3D solve as real work today (`kernel` is N-D generic and
`kernel.flux` is a named 2D-only seam, plan §4.3/Q7), so this is a note about a
door, not a room.

**Recommendation.** Nothing now. If 3D becomes real work, `seeded_distance` is one
of the two places to measure first (the other is R3's labeller), and the fix is
`return_indices=False` plus a second transform for the offsets, trading time for
memory.

---

## 3. Four things worth promoting from remark to rule

These are not tasks. They are the sentences M6–M9 paid for, stated once so they
do not have to be paid for again.

1. **A skipped test is not a passing test, and a count is not a list.** "9 skipped"
   appeared in every commit message from M5 to M8 and nobody read it as "the UI
   has no tests". R9 is the mechanism that would make this impossible; §24.1 is
   the story.

2. **A local fix for a global defect is the default wrong answer, and it is always
   plausible.** Three times in M9 (R5), and each time the code looked more correct
   after the change than before it. The tell is the shape of the defect, not the
   shape of the fix: a five-cell band cannot repair a domain-wide error, and no
   amount of care at the wall repairs a field that was already wrong when it
   arrived there.

3. **A number's provenance is part of the number.** E18, the two SiO₂ entries,
   B12 and `titania`'s deliberate zeros are four instances (R7). The general form:
   *absent beats invented; invented-and-marked beats invented; and a value whose
   provenance changed needs a new key, not a new value in the old one.*

4. **Documentation asserting a behaviour is not evidence of the behaviour, and it
   actively hides its absence.** E13's `tone` was described correctly in a module
   docstring and in the step's own help text, and implemented nowhere (R1). Both
   texts were written by somebody who had just decided the design, which is
   exactly when it is easiest to describe it as done. This repository leans hard
   on prose — it is a real strength, and the cost is that prose reads like a
   test. The mitigation is cheap: **a sentence in a docstring that says the code
   reads X from Y is a sentence that deserves an assertion**, and it is usually a
   three-line one.

---

## 4. What I would do next, ranked

1. **R1** — the read-only display for `thickness` and `tone`, and a pass over the
   roadmap's §2 decisions for others with no §4 owner. The model half of E13 is
   fixed here; the UI half of both is still open.
2. **R9** — a CI workflow that fails on a skip. The cheapest insurance in this
   list, and the lesson it protects is one this repository already paid for.
3. **R3.1** — stop the etch leaving one-cell islands, measured on the grating demo.
   Likely also the cheapest real win on M7's scaling finding.
4. **R7** — write the provenance convention into the materials README, before B7
   arrives and somebody has to infer it.
5. **R8** — the three UI edges, in one sitting; two of them share a widget change
   with R1.
6. **R4** — one paragraph in ADR-0004.

R2, R6 and R10 are deliberate no-ops, documented where they will be found.

The backlog (`docs/plans/backlog-later.md`) is unchanged by any of this: B1–B11
were all still out of scope at the end of M9, and B12 is the one that closed.
