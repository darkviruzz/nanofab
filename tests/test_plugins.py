"""Entry-point discovery (plan §5.4, §11) — with a second implementer.

Two halves, and the second is the one that earns the file.

**Fast, always run**: the loader's own branches, driven through the
`entry_points` seam with entry points a test describes. Both accepted shapes, and
every way a plugin can be broken — an import that raises, an object of the wrong
type, a `step_id` that collides with a builtin — asserted to be *recorded and
skipped* rather than fatal, because an application that will not start because of
one stale third-party package is the failure worth avoiding.

**Slow, skipped without pip**: `examples/nanofab-plugin-example` really built and
really installed into a temp directory, with discovery run against it in a
subprocess. That is the only thing that checks the parts a mock cannot reach —
whether the entry-point group name in the plugin's `pyproject.toml` matches the
one the loader reads, whether the objects it names are the shapes the loader
accepts, and whether the packaging metadata produces an entry point at all.
The handoff's sentence: *a discovery mechanism with no second implementer is a
discovery mechanism that does not work yet.*

The subprocess also matters for a reason the tree cannot fake: the plugin is
installed, not importable from the repo, so a passing run proves the loader found
it through `importlib.metadata` and not through `sys.path` happening to contain
the source.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from nanofab_v3.processes import (
    IDEAL,
    FunctionStep,
    ProcessRegistry,
    StepResult,
    application_registry,
    builtin_registry,
    discover_plugins,
)

PLUGIN_SOURCE = Path(__file__).resolve().parent.parent / "examples" / "nanofab-plugin-example"


# -- 1. the loader, against entry points a test describes ---------------------


@dataclass
class FakeDist:
    name: str


@dataclass
class FakeEntryPoint:
    """Enough of `importlib.metadata.EntryPoint` for the loader.

    Deliberately not a real one: a real `EntryPoint` resolves by importing a
    module path, which would mean shipping a module per failure mode. What the
    loader actually needs from it is a name, a distribution and `load()`.
    """

    name: str
    value: object = None
    dist: FakeDist | None = None
    error: Exception | None = None

    def load(self):
        if self.error is not None:
            raise self.error
        return self.value


def _points(*entries: FakeEntryPoint):
    return lambda group: tuple(entries)


def _a_step(step_id: str = "plugin.example") -> FunctionStep:
    return FunctionStep(
        step_id=step_id,
        display_name="Example",
        fidelity=IDEAL,
        schema=(),
        required=frozenset(),
        provided=frozenset(),
        run_function=lambda ctx: StepResult(ctx.structure),
    )


def test_an_entry_point_that_is_a_step_is_registered() -> None:
    """The ordinary shape: one step, no boilerplate."""
    registry = ProcessRegistry()
    step = _a_step()

    report = discover_plugins(registry, entry_points=_points(FakeEntryPoint("one", step)))

    assert report.ok
    assert report.loaded == ("plugin.example",)
    assert registry["plugin.example"] is step


def test_an_entry_point_that_is_a_callable_is_handed_the_registry() -> None:
    """The general shape: a package that registers several, or has setup to do."""
    registry = ProcessRegistry()

    def register(target: ProcessRegistry) -> None:
        target.register(_a_step("plugin.first"))
        target.register(_a_step("plugin.second"))

    report = discover_plugins(registry, entry_points=_points(FakeEntryPoint("many", register)))

    assert report.loaded == ("plugin.first", "plugin.second")
    assert len(registry) == 2


def test_a_plugin_that_fails_to_import_is_skipped_and_the_rest_still_load() -> None:
    """The failure an application must survive: one stale third-party package."""
    registry = ProcessRegistry()

    report = discover_plugins(
        registry,
        entry_points=_points(
            FakeEntryPoint("broken", dist=FakeDist("stale-plugin"),
                           error=ModuleNotFoundError("no module named 'gone'")),
            FakeEntryPoint("good", _a_step()),
        ),
    )

    assert not report.ok
    assert report.loaded == ("plugin.example",)
    (failure,) = report.failures
    assert failure.name == "broken"
    assert "ModuleNotFoundError" in failure.reason
    assert "stale-plugin" in failure.describe()
    assert "plugin.example" in registry


def test_an_entry_point_of_the_wrong_shape_is_a_failure_not_a_crash() -> None:
    registry = ProcessRegistry()

    report = discover_plugins(registry, entry_points=_points(FakeEntryPoint("odd", 42)))

    assert len(registry) == 0
    assert "neither a ProcessStep nor a callable" in report.failures[0].reason


def test_a_plugin_cannot_take_a_builtin_s_step_id() -> None:
    """`register()` already refuses it; discovery reports rather than propagates.

    This is plan §5.4's "in-tree builtins use the same mechanism" doing work: the
    rule is enforced once, at the door every step comes through, and a plugin
    trying to redefine `develop.ideal` for every recipe in the application is
    stopped there.
    """
    registry = builtin_registry()
    before = len(registry)

    report = discover_plugins(
        registry, entry_points=_points(FakeEntryPoint("shadow", _a_step("develop.ideal")))
    )

    assert len(registry) == before
    assert "already registered" in report.failures[0].reason


def test_a_plugin_that_reaches_for_a_global_generator_is_refused() -> None:
    """§5.2's lint is at the same door, so discovery inherits it."""
    registry = ProcessRegistry()

    def _run(ctx):  # pragma: no cover - never runs
        import numpy as np

        return StepResult(ctx.structure, swept=float(np.random.normal()))

    report = discover_plugins(
        registry,
        entry_points=_points(
            FakeEntryPoint(
                "sloppy",
                FunctionStep(
                    step_id="plugin.sloppy",
                    display_name="Sloppy",
                    fidelity=IDEAL,
                    schema=(),
                    required=frozenset(),
                    provided=frozenset(),
                    run_function=_run,
                ),
            )
        ),
    )

    assert len(registry) == 0
    assert "process-global random generator" in report.failures[0].reason


def test_the_builtin_registry_never_discovers_anything() -> None:
    """It has to be a fixed set, and the reason is the cache key.

    Recipe hashes and implementation digests (plan §21.1) are computed against a
    registry. A test whose registry depended on what happened to be installed
    would be a test with a different answer on every machine, so the tests take
    the builtins and the application takes `application_registry`.
    """
    registry, report = application_registry(plugins=False)

    assert sorted(registry.steps) == sorted(builtin_registry().steps)
    assert report.loaded == ()


# -- 2. the second implementer, really installed ------------------------------


PROBE = textwrap.dedent(
    """
    import json
    from nanofab_v3.materials import SILICON, didactic_library
    from nanofab_v3.processes import application_registry, run_chain
    from nanofab_v3.processes.substrate import cross_section_grid, select_substrate

    registry, report = application_registry()
    grid = cross_section_grid(width=120.0, thickness=20.0, headroom=80.0)
    wafer = select_substrate(grid, SILICON, surface=20.0)
    outcomes = run_chain(
        [
            (registry["sog.spin"], {"thickness": 30.0}),
            (registry["sog.cure"], {"duration": 150.0}),
        ],
        wafer,
        library=didactic_library(),
    )
    print(json.dumps({
        "loaded": sorted(report.loaded),
        "failures": [f.reason for f in report.failures],
        "total": len(registry),
        "ok": [o.ok for o in outcomes],
        "capabilities": sorted(outcomes[-1].capabilities),
        "digest": registry.digest("sog.spin"),
        "from_metadata": True,
    }))
    """
)


@pytest.mark.slow
def test_a_plugin_installed_out_of_tree_is_discovered_and_runs(tmp_path) -> None:
    """The one that proves the mechanism: build, install, discover, run.

    Roughly 4 s — 3.4 to build and install the wheel, the rest the subprocess —
    which is why it is the only test in this file that costs anything and why the
    fast half above exists at all.
    """
    if shutil.which("pip") is None:  # pragma: no cover - environment dependent
        pytest.skip("pip is not available")
    assert PLUGIN_SOURCE.is_dir(), f"the example plugin is missing at {PLUGIN_SOURCE}"

    target = tmp_path / "site"
    install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target),
         str(PLUGIN_SOURCE)],
        capture_output=True,
        text=True,
    )
    if install.returncode != 0:  # pragma: no cover - environment dependent
        pytest.skip(f"the example plugin could not be built here:\n{install.stderr[-2000:]}")

    probe = subprocess.run(
        [sys.executable, "-c", PROBE],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(target), "PATH": "/usr/bin:/bin"},
        cwd=str(PLUGIN_SOURCE.parent.parent),
    )
    assert probe.returncode == 0, probe.stderr

    import json

    result = json.loads(probe.stdout)
    assert result["failures"] == []
    assert result["loaded"] == ["sog.cure", "sog.spin"]
    assert result["total"] == len(builtin_registry()) + 2
    assert all(result["ok"])
    assert "material:sog" in result["capabilities"]
    assert "sog.cure" in result["capabilities"]
    # the plugin's own step reaches the cache key exactly as a builtin does
    assert result["digest"].startswith("src:")


@pytest.mark.slow
def test_an_installed_plugin_changes_the_recipe_hash_of_recipes_that_use_it(
    tmp_path,
) -> None:
    """Plan §21.1 from the plugin side, which is the case it was decided for.

    Editing a plugin's step must retire exactly the recipes that use it. Here the
    weaker but load-bearing half: the plugin's implementation is *in* the key at
    all, which `code_version()` alone could never see.
    """
    if shutil.which("pip") is None:  # pragma: no cover - environment dependent
        pytest.skip("pip is not available")

    target = tmp_path / "site"
    install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target),
         str(PLUGIN_SOURCE)],
        capture_output=True,
        text=True,
    )
    if install.returncode != 0:  # pragma: no cover - environment dependent
        pytest.skip("the example plugin could not be built here")

    probe = textwrap.dedent(
        """
        from nanofab_v3.io import recipe_hash
        from nanofab_v3.processes import application_registry, builtin_registry
        from nanofab_v3.processes.substrate import cross_section_grid
        from nanofab_v3.runtime import Recipe, RecipeStep

        registry, _ = application_registry()
        grid = cross_section_grid(width=100.0, thickness=20.0, headroom=60.0)
        recipe = Recipe(grid, (RecipeStep("sog.spin", {"thickness": 30.0}),), "sog")

        print(recipe_hash(recipe, registry=registry) != recipe_hash(recipe))
        print("sog.spin" not in builtin_registry())
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(target), "PATH": "/usr/bin:/bin"},
        cwd=str(PLUGIN_SOURCE.parent.parent),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["True", "True"]
