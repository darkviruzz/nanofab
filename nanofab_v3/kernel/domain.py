"""Growing and shrinking the domain along the stacking axis (roadmap E5, M7).

**One function moves the domain, and it is `resize`.** Everything else here
decides *whether* and *by how much*; the handoff asks for that on purpose,
because backlog B1 — several stacked sub-domains, each with its own
`Grid.origin`, following the front — is built on this seam and would otherwise
have to find every place a shape is assumed.

## Why this exists at all

Roadmap §1's arithmetic: one `phi` costs `rows × columns × 4` bytes, so a 1.2 µm
wide cross-section at 1 nm with five materials is ~24 MB per revision at 1 µm
deep and **~2.4 GB at 100 µm**. A 625 µm wafer is not a domain that can be
allocated. So the domain is a *window* onto a sample whose real thickness is
metadata (`Structure.metadata`, roadmap E7), and the window has to move: a
deposition grows the stack upward past the headroom it was given, and an etch
eats downward past the substrate that was drawn.

Both directions are cheap to get right for the same reason, and it is a property
of the sample rather than of the code: **the top and bottom of the window are
homogeneous.** Above everything is empty and below everything is substrate, so
there is no geometry there to reconstruct — only a distance function to continue.

## The two padding rules, and why they differ

- A **`phi`** is a distance, so it is continued *linearly away from the front*:
  each new row is the edge row plus one cell spacing, signed by which side of the
  interface the edge row is on. That is exact for a half-space — which is what a
  substrate is — and correct in the far field for anything else, where "the
  nearest interface is in the direction we came from" is precisely the condition
  that makes the bottom row quiet enough to grow from.
- A **`Field`** is not a distance, it is a value. Dose does not increase because
  you looked further down. New rows repeat the edge row, which in a homogeneous
  region *is* the value that continues.

Reinitialisation cannot rescue a wrong choice here, which is why the choice is
made rather than left to the gate: `ReinitPolicy` works in a five-cell band
around the front (plan §17.4), and the rows being added are as far from the front
as rows in this domain get.

## The two ends are not the same question, and one predicate cannot answer both

The obvious implementation — "count the rows at each end that look like the edge
row" — is wrong at the top, and wrongly in the direction that matters. A resist
coat that fills the domain to the ceiling makes every upper row identical to the
top row, so a symmetric rule reads a stack with **no headroom left** as having
plenty. It is exactly the case the growth exists for.

So each side is asked what that side of the domain is *for*:

- **`headroom`** — consecutive rows at the top that are entirely **empty**.
  Headroom is empty space by definition; a solid row is not headroom however
  uniform it is.
- **`underroom`** — consecutive rows at the bottom that are laterally **uniform**
  and match the bottom row. Below, the domain is a window onto a homogeneous
  substrate that continues out of sight (roadmap §1), so what makes a row quiet
  there is that it is a vertical extrusion of the face. A trench that has reached
  the floor makes the bottom row non-uniform and drops this to zero, which is the
  signal to grow — or, once the substrate's real thickness is used up, to fail
  (roadmap E7).

Both are statements about *structure* rather than about solid: a buried blanket
layer is not quiet even though nothing is moving there, and that is right,
because shrinking past it would delete it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from nanofab_v3.model.grid import PHI_DTYPE, Grid
from nanofab_v3.model.structure import EMPTY, Structure

STACK_AXIS = 0
"""The axis the domain grows along. Axis 0 stacks (`substrate.cross_section_grid`).

Not a parameter: roadmap E6 decides there is **no** dynamic growth along x. The
lateral extent is a choice, not an automatism (backlog B9), and M9 has not yet
repaired the lateral boundary behaviour — growing into it would be building on
the part that is known to be broken.
"""


@dataclass(frozen=True)
class DomainPolicy:
    """When the domain grows, when it gives room back, and where it stops.

    **`margin` is a trigger, not a target**, and the difference is the whole
    reason the defaults look the way they do. A policy that grew every domain
    until it had a comfortable margin would silently replace the domain somebody
    chose: a 40 nm substrate drawn under 200 nm of headroom would come back 190
    nm deep before a single step ran, and every measurement taken against it
    would be taken against a different picture than the one asked for. So the
    trigger is a few cells — resize when the sample is about to touch a face —
    and the *growth* is generous, so it does not re-trigger on the next
    nanometre.

    Attributes:
        margin: How close the sample may come to a face before the domain grows,
            in nm. Small on purpose: see above.
        slack: Extra quiet domain tolerated beyond `margin` before shrinking, in
            nm. Large on purpose, for the same reason and one more: hysteresis,
            so a front oscillating around the threshold does not reallocate on
            every step. This is E5's "auch schrumpfen, wenn groß und leer", and
            "leer" is what a whole micron of nothing means.
        chunk: Growth is rounded up to a multiple of this, in nm. A resize copies
            every array, so growing by exactly what is missing would pay that on
            almost every step of a deep etch.
        cap: Maximum domain depth, in nm — roadmap E5's 5 µm. Raising it is a
            decision with a memory bill, which is why `memory_estimate` exists
            and why the cap is a policy value rather than a constant.
        floor: Minimum domain depth, in nm, so shrinking cannot squeeze a sample
            into a domain with no room to work in.
        retries: How many times a step that ran out of room may be given more and
            run again (see `extra_room`). Two, because the growth doubles each
            time and a third attempt would ask for a micron on top of a policy
            whose cap is five.
    """

    margin: float = 8.0
    slack: float = 1200.0
    chunk: float = 256.0
    cap: float = 5000.0
    floor: float = 200.0
    retries: int = 2

    def __post_init__(self) -> None:
        for name in ("margin", "slack", "chunk", "cap", "floor"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be a positive finite length, got {value}")
        if self.cap < self.floor:
            raise ValueError(f"cap {self.cap} is below floor {self.floor}")

    def rows(self, grid: Grid, length: float) -> int:
        """`length` in nm as a whole number of cells, rounded up."""
        return int(math.ceil(float(length) / grid.spacing - 1e-9))


@dataclass(frozen=True)
class DomainChange:
    """What one `fit` decided: rows added or removed, and whether it hit the cap.

    Attributes:
        below: Rows added at the low end of the stacking axis; negative removes.
        above: The same at the high end.
        capped: The fit wanted to grow further and `DomainPolicy.cap` stopped it.
            The one condition an operator has to be told about, because it is the
            point where the model stops being able to show what it is computing.
        wanted: Rows the fit would have added had the cap not been there.
    """

    below: int = 0
    above: int = 0
    capped: bool = False
    wanted: int = 0

    @property
    def moved(self) -> bool:
        """Whether anything actually changed."""
        return bool(self.below or self.above)

    @property
    def rows(self) -> int:
        """Net change in row count."""
        return self.below + self.above

    def describe(self, grid: Grid) -> tuple[str, ...]:
        """Lines for a run log — empty when nothing happened."""
        lines: list[str] = []
        if self.moved:
            parts = []
            if self.below:
                parts.append(f"{self.below:+d} below")
            if self.above:
                parts.append(f"{self.above:+d} above")
            lines.append(
                f"domain {'grew' if self.rows > 0 else 'shrank'} by "
                f"{abs(self.rows) * grid.spacing:.0f} nm ({', '.join(parts)}), "
                f"now {grid.shape[STACK_AXIS] * grid.spacing:.0f} nm deep"
            )
        if self.capped:
            shape = list(grid.shape)
            shape[STACK_AXIS] += self.wanted
            wanted_grid = Grid(grid.origin, grid.spacing, tuple(shape), grid.axes)
            lines.append(
                f"the domain needs {self.wanted * grid.spacing:.0f} nm more than its cap "
                f"allows and the sample is being clipped. Raising the cap to "
                f"{shape[STACK_AXIS] * grid.spacing / 1000.0:.2f} um would cost "
                f"{memory_estimate(wanted_grid).describe()}"
            )
        return tuple(lines)


@dataclass(frozen=True)
class MemoryEstimate:
    """What one revision of a domain costs, so raising the cap is an informed choice."""

    cells: int
    arrays: int
    bytes_per_revision: int

    def describe(self) -> str:
        """One sentence, with the honest range for what it costs on disk."""
        megabytes = self.bytes_per_revision / 1024**2
        # Plan §20.3 measured 6x (a field with per-cell entropy) to 493x (a clean
        # half-plane) across one real chain, so a single disk number would be a
        # fiction. The RAM number is not: it is `cells x arrays x 4` exactly.
        return (
            f"{self.cells:,} cells x {self.arrays} arrays = {megabytes:.1f} MB of RAM per "
            f"revision, and 6x to 500x less on disk depending on what the arrays hold"
        )


def memory_estimate(grid: Grid, arrays: int = 5) -> MemoryEstimate:
    """RAM per revision for a domain of this shape (roadmap §1's table).

    `arrays` defaults to five — roadmap §1's own assumption of about five
    materials — so the estimate answers "what would this domain cost me" rather
    than "what does this particular revision cost right now".
    """
    cells = int(np.prod(grid.shape))
    count = max(1, int(arrays))
    return MemoryEstimate(
        cells=cells,
        arrays=count,
        bytes_per_revision=cells * count * np.dtype(PHI_DTYPE).itemsize,
    )


# -- reading the window -------------------------------------------------------


def _lateral(index: np.ndarray) -> tuple[int, ...]:
    """The axes that are not the stacking axis — every one a row spreads over."""
    return tuple(axis for axis in range(index.ndim) if axis != STACK_AXIS)


def headroom(structure: Structure) -> int:
    """Consecutive entirely empty rows at the top of the domain.

    What a deposition has left to grow into. Solid rows are not headroom, however
    uniform — see the module docstring for why that asymmetry is the whole point.
    """
    if not structure.phi:
        return structure.grid.shape[STACK_AXIS]
    occupied = np.any(structure.material_index != EMPTY, axis=_lateral(structure.material_index))
    if not bool(occupied.any()):
        return structure.grid.shape[STACK_AXIS]
    return int(occupied.shape[0] - 1 - np.max(np.flatnonzero(occupied)))


def underroom(structure: Structure) -> int:
    """Consecutive laterally uniform rows at the bottom that match the bottom row.

    What an etch has left to eat into. Compared on `material_index` rather than on
    `phi`, because the question is what the sample *is*, not how far the nearest
    interface happens to be: two rows deep inside the same substrate differ in
    every `phi` value and are the same piece of wafer.
    """
    if not structure.phi:
        return structure.grid.shape[STACK_AXIS]
    index = structure.material_index
    lateral = _lateral(index)
    uniform = np.all(index == index[(slice(None),) + (slice(0, 1),) * len(lateral)], axis=lateral)
    matches_face = np.all(index == index[0], axis=lateral)
    quiet = uniform & matches_face
    if not bool(quiet[0]):
        return 0
    blocked = np.flatnonzero(~quiet)
    return int(blocked[0]) if blocked.size else int(index.shape[STACK_AXIS])


def window(structure: Structure) -> tuple[int, int]:
    """`(underroom, headroom)` — the quiet rows at each end of the stacking axis."""
    return underroom(structure), headroom(structure)


# -- the one function that moves the domain -----------------------------------


def out_of_room(structure: Structure) -> tuple[bool, bool]:
    """`(the low end is used up, the high end is used up)`.

    What a step running out of domain looks like from the outside: the sample
    reaches the very first or very last row, so there is nowhere left for it to
    go. `engine.run_step` reads this after a commit and, rather than handing back
    a sample that was clipped by the picture frame, grows the domain and runs the
    step again (`extra_room`).
    """
    if not structure.phi:
        return False, False
    below, above = window(structure)
    rows = structure.grid.shape[STACK_AXIS]
    if below >= rows and above >= rows:
        return False, False  # nothing in the domain yet decides nothing
    return below == 0, above == 0


def extra_room(
    grid: Grid,
    *,
    below: bool,
    above: bool,
    policy: DomainPolicy = DomainPolicy(),
    attempt: int = 0,
) -> DomainChange:
    """Room to add for another attempt at a step that used up what it had.

    A policy decision rather than a measurement, and it has to be: a front that
    was clipped by the domain face cannot be asked how much further it wanted to
    go. So the growth doubles per attempt — one `chunk`, then two — which reaches
    a micron of extra room in two tries and stops there.

    The cap applies here exactly as it does in `plan`: growth stops at
    `policy.cap`, `capped` says so, and `wanted` says by how much it fell short.
    """
    step = max(1, policy.rows(grid, policy.chunk)) * (2 ** max(0, int(attempt)))
    wants_below = step if below else 0
    wants_above = step if above else 0
    rows = grid.shape[STACK_AXIS]
    cap_rows = max(1, int(policy.cap / grid.spacing) + 1)
    wanted = wants_below + wants_above
    if rows + wanted <= cap_rows:
        return DomainChange(below=wants_below, above=wants_above)
    room = max(0, cap_rows - rows)
    granted_below, granted_above = _share(wants_below, wants_above, room)
    return DomainChange(
        below=granted_below,
        above=granted_above,
        capped=True,
        wanted=wanted - granted_below - granted_above,
    )


def resize(structure: Structure, *, below: int = 0, above: int = 0) -> Structure:
    """Add (or, negative, remove) rows at each end of the stacking axis.

    The only place in the package that changes a domain's shape. `Grid` is frozen
    and is the sole spatial authority, so this builds a **new** grid and new
    arrays — nothing is mutated, and the offset is carried by `Grid.origin`
    rather than by rewriting coordinates anywhere else (which is also what
    backlog B1 needs from this function).

    See the module docstring for the two padding rules: a `phi` continues
    linearly away from the front, a `Field` repeats its edge row.
    """
    below, above = int(below), int(above)
    if below == 0 and above == 0:
        return structure
    grid = structure.grid
    rows = grid.shape[STACK_AXIS]
    if rows + below + above < 1:
        raise ValueError(
            f"resizing by ({below:+d}, {above:+d}) would leave {rows + below + above} rows"
        )
    if below < 0 and -below > rows or above < 0 and -above > rows:
        raise ValueError(f"cannot remove more rows than the domain has ({rows})")

    shape = list(grid.shape)
    shape[STACK_AXIS] = rows + below + above
    origin = list(grid.origin)
    origin[STACK_AXIS] = grid.origin[STACK_AXIS] - below * grid.spacing
    moved = Grid(
        origin=tuple(origin), spacing=grid.spacing, shape=tuple(shape), axes=grid.axes
    )

    phi = {
        material: _resized_distance(values, below, above, grid.spacing)
        for material, values in structure.phi.items()
    }
    fields = {
        key: _resized_value(values, below, above) for key, values in structure.fields.items()
    }
    return Structure(moved, phi, fields, dict(structure.metadata))


def _crop(values: np.ndarray, below: int, above: int) -> np.ndarray:
    """The rows that survive a shrink at either end."""
    start = -below if below < 0 else 0
    stop = values.shape[STACK_AXIS] + (above if above < 0 else 0)
    return values[start:stop]


def _ramp(edge: np.ndarray, count: int, spacing: float, direction: int) -> np.ndarray:
    """`count` rows continuing `edge` away from the front, one spacing per row.

    `direction` is +1 for rows added above the edge and -1 for rows below. The
    sign of the edge decides whether the distance grows or falls: outside a
    material (`phi > 0`) moving further away increases it, inside (`phi < 0`) it
    becomes more negative. An edge value of exactly zero is the interface sitting
    on the domain face, and is treated as outside — the row beyond it is empty
    space, which is what growing there is for.
    """
    sign = np.where(edge < 0.0, -1.0, 1.0).astype(np.float64)
    steps = np.arange(1, count + 1, dtype=np.float64) * spacing
    if direction < 0:
        steps = steps[::-1]
    return (edge.astype(np.float64) + sign * steps[:, None]).astype(PHI_DTYPE)


def _resized_distance(
    values: np.ndarray, below: int, above: int, spacing: float
) -> np.ndarray:
    """One `phi`, padded by signed linear continuation and cropped where negative."""
    kept = _crop(values, below, above)
    parts = [kept]
    if below > 0:
        parts.insert(0, _ramp(kept[0], below, spacing, direction=-1))
    if above > 0:
        parts.append(_ramp(kept[-1], above, spacing, direction=+1))
    return np.concatenate(parts, axis=STACK_AXIS).astype(PHI_DTYPE)


def _resized_value(values: np.ndarray, below: int, above: int) -> np.ndarray:
    """One `Field`, padded by repeating its edge row — see the module docstring."""
    kept = _crop(values, below, above)
    parts = [kept]
    if below > 0:
        parts.insert(0, np.repeat(kept[:1], below, axis=STACK_AXIS))
    if above > 0:
        parts.append(np.repeat(kept[-1:], above, axis=STACK_AXIS))
    return np.concatenate(parts, axis=STACK_AXIS).astype(values.dtype)


# -- deciding how much --------------------------------------------------------


def plan(structure: Structure, policy: DomainPolicy = DomainPolicy()) -> DomainChange:
    """What `fit` would do to this structure, without doing it.

    Separate from `fit` so the decision is inspectable — a UI can say "this step
    will grow the domain" before it runs, and a test can assert the arithmetic
    without allocating anything.
    """
    grid = structure.grid
    rows = grid.shape[STACK_AXIS]
    if not structure.phi:
        return DomainChange()
    quiet_below, quiet_above = window(structure)
    if quiet_below >= rows and quiet_above >= rows:
        return DomainChange()  # a domain with no structure in it decides nothing

    margin = policy.rows(grid, policy.margin)
    slack = policy.rows(grid, policy.slack)
    chunk = max(1, policy.rows(grid, policy.chunk))
    cap_rows = max(1, int(policy.cap / grid.spacing) + 1)
    floor_rows = max(1, int(policy.floor / grid.spacing) + 1)

    below = _needed(quiet_below, margin, slack, chunk)
    above = _needed(quiet_above, margin, slack, chunk)

    wanted = max(0, below) + max(0, above)
    capped = False
    if rows + below + above > cap_rows:
        capped = True
        room = max(0, cap_rows - rows - min(0, below) - min(0, above))
        below, above = _share(below, above, room)
    if rows + below + above < floor_rows:
        # Only a shrink can get here; give back less rather than none.
        deficit = floor_rows - (rows + below + above)
        below, above = _share(-below, -above, deficit)
        below, above = -below, -above
    return DomainChange(
        below=below, above=above, capped=capped, wanted=max(0, wanted - max(0, below) - max(0, above))
    )


def _needed(quiet: int, margin: int, slack: int, chunk: int) -> int:
    """Rows to add (positive) or give back (negative) at one end."""
    if quiet < margin:
        return int(math.ceil((margin - quiet) / chunk)) * chunk
    if quiet > margin + slack:
        return -(((quiet - margin) // chunk) * chunk)
    return 0


def _share(below: int, above: int, room: int) -> tuple[int, int]:
    """Split `room` rows of allowed growth between two ends that each want some.

    Proportional to what each end asked for, remainder to the low end — which is
    the end an etch is heading for, and the end where running out means losing
    the sample rather than losing headroom.
    """
    wants_below, wants_above = max(0, below), max(0, above)
    total = wants_below + wants_above
    if total <= 0 or room <= 0:
        return min(0, below), min(0, above)
    share_above = min(wants_above, int(room * wants_above / total))
    return min(0, below) + room - share_above, min(0, above) + share_above


def fit(
    structure: Structure, policy: DomainPolicy = DomainPolicy()
) -> tuple[Structure, DomainChange]:
    """Grow or shrink the domain so the sample keeps `policy.margin` of room.

    Autonomous and without asking, which is roadmap E5 — the alternative is a
    dialog on a step that had nothing to do with the domain. What is *not* silent
    is hitting the cap: `DomainChange.capped` is what the shell turns into a
    warning with a memory estimate, because that is the point where the model
    stops being able to show what it is computing.
    """
    change = plan(structure, policy)
    if not change.moved:
        return structure, change
    return resize(structure, below=change.below, above=change.above), change
