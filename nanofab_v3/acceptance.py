"""S1-S5 as shipped code, so the packaged application can run them (plan §13.3, §14).

Plan §14's definition of done for M5 is *"packaged exe runs S1-S4"*, and the
acceptance scenarios lived in `tests/test_scenarios.py`, which pytest runs and an
exe does not carry. So the **recipes** and one headline check per scenario live
here, in the package, and the test module imports the recipes from this file.
One definition of what S1 is; the detailed per-mechanism assertions stay next
door, where they belong.

What that division means, stated because it is the honest limit: running
`--selftest` in the exe checks that each scenario's *mechanism* holds — that S1
leaves one metal pattern of the designed width, that S3's resist is unreachable
and nothing lifts, that S4 leaves fences, that S5's buried particle survives the
clean. It does **not** run the thirty-odd assertions `tests/test_scenarios.py`
makes about how each of those comes about. An exe that passes the self-test is
an exe whose model works; the suite is what says the model works *for the right
reasons*, and it needs a source checkout.

`tests/test_scenarios.py` also asserts that every scenario here passes, so the
two cannot drift without the suite going red.

## Why a flag rather than a menu entry

The handoff (§6, item 7) asks for one and says to write down which. It is a
**`--selftest` flag** (`nanofab_v3.cli`), for three reasons:

1. The DoD is a *checkable claim*. A flag has an exit code, so "the exe runs
   S1-S5" is something CI, a build script or a person with a terminal can
   establish. A menu entry needs a display, a human, and their report of what
   they saw.
2. A frozen exe on somebody else's machine is exactly the case handoff §4 warns
   the numbers will be wrong about. The first thing to run there is the thing
   that needs no window.
3. Each scenario is seconds of solver. In a menu entry that is a frozen UI or a
   second threading story; on a command line it is a progress line.

The cost is recorded rather than hidden: the exe is built with `console=True`
(see `nanofab_v3.spec`), so `--selftest` has somewhere to print. On Windows that
means a terminal behind the application window. `--report PATH` writes the
result to a file for a build that would rather not look at a console.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from nanofab_v3.kernel import occurrences, predicates
from nanofab_v3.materials import (
    ALUMINA,
    METAL,
    OXIDE,
    PARTICLE,
    RESIST,
    SILICON,
    UNDERLAYER,
    MaterialLibrary,
    didactic_library,
)
from nanofab_v3.model.grid import Grid
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes.engine import StepOutcome, run_chain
from nanofab_v3.processes.registry import ProcessRegistry, builtin_registry
from nanofab_v3.processes.substrate import cross_section_grid

SURFACE = 40.0
"""Where the substrate's top face sits, in nm. Every scenario measures against it."""

CENTRE = 150.0
"""Lateral centre of the patterned feature, in nm."""

WINDOW = 100.0
"""Design width of S1's and S3's window, in nm — what the pattern is measured against."""

PARTICLE_SEED: Mapping[str, Any] = {"count": 5, "radius": 8.0}
"""S5's particles. Two of them overlap at this seed and count as one occurrence,
which is ADR-0003 doing its job rather than a fixture to fix."""

Steps = tuple[tuple[str, Mapping[str, Any]], ...]
"""A recipe as `(step_id, params)` pairs — registry-independent, so this module
describes scenarios without holding one."""


# -- the recipes --------------------------------------------------------------


def lift_off_steps(*, metal_thickness: float = 20.0, resist_thickness: float = 90.0) -> Steps:
    """substrate -> resist -> ideal exposure -> ideal development -> evaporation."""
    return (
        ("substrate.select", {"material": SILICON, "surface": SURFACE}),
        ("resist.spin_coat", {"material": RESIST, "thickness": resist_thickness}),
        (
            "litho.expose_ideal",
            {"material": RESIST, "pattern": "window", "center": CENTRE, "width": WINDOW},
        ),
        ("develop.ideal", {"material": RESIST}),
        ("deposit.evaporate", {"material": METAL, "thickness": metal_thickness}),
    )


def bilayer_steps(
    *, mouth: float = 80.0, cavity: float = 120.0, under: float = 50.0, imaging: float = 60.0
) -> Steps:
    """A real lift-off stack: an underlayer that clears wider than the imaging resist.

    The undercut profile is what a lift-off resist *is*. It cannot come from one
    layer here, because ideal development removes exactly what was exposed and
    nothing laterally — so the bilayer is modelled the way it works in a
    cleanroom: a non-imaging underlayer the developer clears further back than
    the top layer's own window.
    """
    return (
        ("substrate.select", {"material": SILICON, "surface": SURFACE}),
        ("resist.spin_coat", {"material": UNDERLAYER, "thickness": under}),
        ("resist.spin_coat", {"material": RESIST, "thickness": imaging}),
        (
            "litho.expose_ideal",
            {"material": RESIST, "pattern": "window", "center": CENTRE, "width": mouth},
        ),
        (
            "litho.expose_ideal",
            {"material": UNDERLAYER, "pattern": "window", "center": CENTRE, "width": cavity},
        ),
        ("develop.ideal", {"material": RESIST}),
        ("develop.ideal", {"material": UNDERLAYER}),
    )


def masked_oxide_steps(*, window: float = 80.0) -> Steps:
    """60 nm of oxide on silicon under a resist mask with a window in it — S2's start."""
    return (
        ("substrate.select", {"material": SILICON, "surface": SURFACE}),
        ("deposit.conformal_offset", {"material": OXIDE, "thickness": 60.0}),
        ("resist.spin_coat", {"material": RESIST, "thickness": 60.0}),
        (
            "litho.expose_ideal",
            {"material": RESIST, "pattern": "window", "center": CENTRE, "width": window},
        ),
        ("develop.ideal", {"material": RESIST}),
    )


def particle_steps(*, bury: bool) -> Steps:
    """substrate -> particles -> (a conformal film) -> clean.

    `bury=False` is S5's control: the identical draw from the identical seed,
    cleaned before anything covers it.
    """
    steps: list[tuple[str, Mapping[str, Any]]] = [
        ("substrate.select", {"material": SILICON, "surface": SURFACE}),
        ("particle.seed", dict(PARTICLE_SEED)),
    ]
    if bury:
        steps.append(("deposit.conformal_offset", {"material": ALUMINA, "thickness": 10.0}))
    steps.append(("clean.particles", {"material": PARTICLE}))
    return tuple(steps)


# -- measurements the checks share --------------------------------------------


def pattern_count(structure: Structure, material=METAL) -> int:
    """How many separate pieces of a material there are (ADR-0003, derived)."""
    _, count = occurrences.label_region(structure.grid, structure.inside(material))
    return int(count)


def width_at(structure: Structure, row: int, material=METAL) -> float:
    """Lateral extent of a material in one row, in nm."""
    return float(np.count_nonzero(structure.inside(material)[row])) * structure.grid.spacing


def top_profile(structure: Structure, material=METAL) -> np.ndarray:
    """Topmost occupied row per column where the material is present."""
    cells = structure.inside(material)
    columns = np.flatnonzero(np.any(cells, axis=0))
    return np.array([int(np.flatnonzero(cells[:, c]).max()) for c in columns])


def skyline(structure: Structure) -> np.ndarray:
    """Height of the topmost solid cell per column, in nm — the sample's outline."""
    solid = structure.solid_mask
    rows = np.arange(solid.shape[0])
    top = np.where(solid, rows[:, None], -1).max(axis=0)
    return structure.grid.origin[0] + top * structure.grid.spacing


# -- the scenarios ------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """One acceptance scenario: a domain, a recipe, and what has to be true after.

    Attributes:
        name: `"S1"` … `"S5"`.
        title: The sentence the scenario is about.
        grid: The domain it runs on.
        steps: The recipe, as `(step_id, params)`.
        check: `(outcomes) -> failures`. Empty means the scenario passed. It
            returns rather than asserts, because this runs in an exe where an
            `AssertionError` and a traceback are not a result anyone can read.
        strict: Whether a broken invariant should abort the chain.
    """

    name: str
    title: str
    grid: Grid
    steps: Steps
    check: Callable[[Sequence[StepOutcome]], tuple[str, ...]]
    strict: bool = True


def _gate_failures(outcomes: Sequence[StepOutcome]) -> tuple[str, ...]:
    """Every step's commit gate held — the check every scenario starts with."""
    return tuple(
        f"step {index} ({outcome.step_id}) failed the gate: "
        + "; ".join(outcome.report.failures)
        for index, outcome in enumerate(outcomes)
        if not outcome.ok
    )


def _check_s1(outcomes: Sequence[StepOutcome]) -> tuple[str, ...]:
    """Plan §13.3: "S1 pattern width == design ± tol"."""
    failures = list(_gate_failures(outcomes))
    deposited, final = outcomes[-2].structure, outcomes[-1].structure

    if pattern_count(deposited) != 3:
        failures.append(
            f"the evaporation should leave 3 metal pieces, left {pattern_count(deposited)}"
        )
    if final.materials != (SILICON, METAL):
        failures.append(f"lift-off should leave silicon and metal, left {final.materials}")
    elif pattern_count(final) != 1:
        failures.append(f"lift-off should leave 1 pattern, left {pattern_count(final)}")
    else:
        width = width_at(final, int(SURFACE) + 1)
        if abs(width - WINDOW) > 4.0:
            failures.append(f"the pattern is {width:.0f} nm wide, designed {WINDOW:.0f}")
    return tuple(failures)


def _check_s2(outcomes: Sequence[StepOutcome]) -> tuple[str, ...]:
    """Plan §13.3: "S2 undercut ratio" — isotropic undercuts, directional does not."""
    failures = list(_gate_failures(outcomes))
    measured = predicates.undercut(outcomes[-1].structure, RESIST)

    if abs(measured.vertical - 30.0) > 3.0:
        failures.append(f"the etch should be 30 nm deep, measured {measured.vertical:.0f}")
    if abs(measured.ratio - 1.0) > 0.25:
        failures.append(
            "an isotropic front is a circle, so it should undercut by what it etches "
            f"down; ratio {measured.ratio:.2f}"
        )
    return tuple(failures)


def _check_s2_control(outcomes: Sequence[StepOutcome]) -> tuple[str, ...]:
    failures = list(_gate_failures(outcomes))
    measured = predicates.undercut(outcomes[-1].structure, RESIST)

    if abs(measured.vertical - 30.0) > 3.0:
        failures.append(f"the etch should be 30 nm deep, measured {measured.vertical:.0f}")
    if measured.ratio >= 0.1:
        failures.append(f"an ion beam should undercut nothing; ratio {measured.ratio:.2f}")
    return tuple(failures)


def _check_s3(outcomes: Sequence[StepOutcome]) -> tuple[str, ...]:
    """Plan §13.3: "S3 resist-unreachable and film continuous". Nothing lifts."""
    failures = list(_gate_failures(outcomes))
    sealed, final = outcomes[-2].structure, outcomes[-1].structure

    if predicates.is_reachable(sealed, RESIST):
        failures.append("the conformal film should have sealed the resist, and did not")
    if RESIST not in final.phi:
        failures.append("nothing should have lifted, and the resist is gone")
    if not any("never reached" in line for line in outcomes[-1].logs):
        failures.append("the failed lift-off should say the solvent never reached the resist")
    if pattern_count(sealed, ALUMINA) != 1:
        failures.append("the conformal film should be one continuous piece")
    return tuple(failures)


def _check_s4(outcomes: Sequence[StepOutcome]) -> tuple[str, ...]:
    """Plan §19.8: S4's fences are attached to the film; the assertion is their height."""
    failures = list(_gate_failures(outcomes))
    final = outcomes[-1].structure

    if final.materials != (SILICON, METAL):
        failures.append(f"lift-off should leave silicon and metal, left {final.materials}")
        return tuple(failures)
    profile = top_profile(final)
    film = float(np.median(profile))
    if profile.max() - film < 10.0:
        failures.append(
            f"the fences should stand well above the film; {profile.max() - film:.0f} nm"
        )
    edges = np.flatnonzero(profile >= profile.max() - 2)
    if not (edges.min() < 0.2 * profile.size and edges.max() > 0.8 * profile.size):
        failures.append("the fences should be at both edges of the pattern")
    return tuple(failures)


def _check_s5(outcomes: Sequence[StepOutcome]) -> tuple[str, ...]:
    """M5's scenario: a buried particle is unreachable, so the clean leaves it."""
    failures = list(_gate_failures(outcomes))
    buried, final = outcomes[-2].structure, outcomes[-1].structure

    if predicates.is_reachable(buried, PARTICLE):
        failures.append("the film should have buried the particles, and did not")
    if PARTICLE not in final.phi:
        failures.append("the clean should have left the buried particles, and took them")
        return tuple(failures)
    if outcomes[-1].measurements["removed"].value != 0.0:
        failures.append("the clean reached a particle it should not have")
    if outcomes[-1].measurements["micromasked"].value < 1.0:
        failures.append("the clean reported no micromasked particles")
    return tuple(failures)


def _check_s5_control(outcomes: Sequence[StepOutcome]) -> tuple[str, ...]:
    failures = list(_gate_failures(outcomes))
    final = outcomes[-1]

    if PARTICLE in final.structure.phi:
        failures.append("an unburied particle should be cleaned off, and was not")
    if final.measurements["removed"].value < 1.0:
        failures.append("the clean removed nothing it should have removed")
    return tuple(failures)


def scenarios() -> tuple[Scenario, ...]:
    """S1-S5 and the two controls that are cheap enough to ship with them.

    The controls matter more than they look: an assertion that S5's clean left
    the particles behind is satisfied just as well by a clean that does nothing
    at all, and an assertion that S2 undercuts is satisfied by an etch that
    removes everything. `tests/test_scenarios.py` runs the rest of them.
    """
    return (
        Scenario(
            name="S1",
            title="naive lift-off leaves one metal pattern of the designed width",
            grid=cross_section_grid(width=300.0, thickness=SURFACE, headroom=200.0),
            steps=lift_off_steps() + (("strip.lift_off", {"material": RESIST}),),
            check=_check_s1,
        ),
        Scenario(
            name="S2",
            title="an isotropic wet etch undercuts the mask by what it etches down",
            grid=cross_section_grid(width=300.0, thickness=SURFACE, headroom=220.0),
            steps=masked_oxide_steps() + (("etch.wet", {"duration": 30.0}),),
            check=_check_s2,
        ),
        Scenario(
            name="S2c",
            title="control: an ion beam of the same depth undercuts nothing",
            grid=cross_section_grid(width=300.0, thickness=SURFACE, headroom=220.0),
            # `scale` brings the oxide's 0.8 nm/s ion-beam rate up to the wet
            # etch's 1.0, so the two are compared at equal depth, not equal time.
            steps=masked_oxide_steps() + (("etch.ibe", {"duration": 30.0, "scale": 1.25}),),
            check=_check_s2_control,
        ),
        Scenario(
            name="S3",
            title="a conformal film seals the resist, so nothing lifts off",
            grid=cross_section_grid(width=300.0, thickness=SURFACE, headroom=200.0),
            steps=lift_off_steps()
            + (
                ("deposit.ald", {"material": ALUMINA, "thickness": 15.0}),
                ("strip.lift_off", {"material": RESIST}),
            ),
            check=_check_s3,
        ),
        Scenario(
            name="S4",
            title="a broad lobe leaves fences standing at the pattern's edges",
            grid=cross_section_grid(width=300.0, thickness=SURFACE, headroom=230.0),
            steps=bilayer_steps()
            + (
                (
                    "deposit.sputter",
                    {"material": METAL, "thickness": 25.0, "exponent": 1.0,
                     "mobility_length": 10.0},
                ),
                ("strip.lift_off", {"material": UNDERLAYER}),
            ),
            check=_check_s4,
        ),
        Scenario(
            name="S5",
            title="a particle buried by a film is unreachable, so the clean leaves it",
            grid=cross_section_grid(width=300.0, thickness=SURFACE, headroom=200.0),
            steps=particle_steps(bury=True),
            check=_check_s5,
        ),
        Scenario(
            name="S5c",
            title="control: the same particles, cleaned before anything buries them",
            grid=cross_section_grid(width=300.0, thickness=SURFACE, headroom=200.0),
            steps=particle_steps(bury=False),
            check=_check_s5_control,
        ),
    )


# -- running them -------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioResult:
    """What one scenario did.

    Attributes:
        name / title: From the `Scenario`.
        ok: Whether every check passed and nothing raised.
        seconds: Wall-clock time.
        failures: What went wrong, as sentences; empty when `ok`.
        steps: How many steps ran.
    """

    name: str
    title: str
    ok: bool
    seconds: float
    failures: tuple[str, ...] = ()
    steps: int = 0

    def describe(self) -> str:
        """One line: `S1  ok    7.6 s  naive lift-off leaves …`."""
        mark = "ok  " if self.ok else "FAIL"
        return f"{self.name:<4} {mark} {self.seconds:6.1f} s  {self.title}"


Progress = Callable[[ScenarioResult], None]
"""Called after each scenario — what a console self-test prints."""


def run_scenario(
    scenario: Scenario,
    *,
    registry: ProcessRegistry | None = None,
    library: MaterialLibrary | None = None,
    recipe_id: str = "",
) -> ScenarioResult:
    """Run one scenario and check it. Never raises for the scenario's sake.

    An exception inside the model is a failure of *this* scenario with the
    exception as its reason, because a self-test that dies on S2 has said
    nothing about S3, S4 or S5 — and in a frozen exe a traceback on stderr is
    not a result anybody can act on.
    """
    registry = builtin_registry() if registry is None else registry
    library = didactic_library() if library is None else library
    started = time.perf_counter()
    try:
        outcomes = run_chain(
            [(registry[step_id], dict(params)) for step_id, params in scenario.steps],
            Structure(scenario.grid),
            library=library,
            recipe_id=recipe_id or scenario.name.lower(),
            strict=scenario.strict,
        )
        failures = tuple(scenario.check(outcomes))
        ran = len(outcomes)
    except Exception as error:  # noqa: BLE001 - one scenario's failure is its own
        return ScenarioResult(
            name=scenario.name,
            title=scenario.title,
            ok=False,
            seconds=time.perf_counter() - started,
            failures=(f"{type(error).__name__}: {error}",),
        )
    return ScenarioResult(
        name=scenario.name,
        title=scenario.title,
        ok=not failures,
        seconds=time.perf_counter() - started,
        failures=failures,
        steps=ran,
    )


def run_all(
    names: Sequence[str] | None = None,
    *,
    registry: ProcessRegistry | None = None,
    library: MaterialLibrary | None = None,
    progress: Progress | None = None,
) -> tuple[ScenarioResult, ...]:
    """Run every scenario (or the named ones) and return what each did.

    `registry` defaults to `builtin_registry()` rather than the application one:
    a self-test says whether *this build's* model works, and a third-party
    plugin that failed to load must not be able to turn S1 red. Whether the
    plugins loaded is `plugins.DiscoveryReport`'s job to say, and the CLI
    reports it separately.
    """
    registry = builtin_registry() if registry is None else registry
    library = didactic_library() if library is None else library
    wanted = None if names is None else {name.upper() for name in names}
    results = []
    for scenario in scenarios():
        if wanted is not None and scenario.name.upper() not in wanted:
            continue
        result = run_scenario(scenario, registry=registry, library=library)
        results.append(result)
        if progress is not None:
            progress(result)
    return tuple(results)
