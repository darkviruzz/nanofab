"""Entry-point discovery: third-party processes through the builtins' own seam.

Plan §5.4 and §11: *"processes register through a registry fed by entry points
(in-tree builtins use the same mechanism)"* and *"registry + entry points from day
1"*. M3 built the seam and M4 recorded that the second half was not true yet —
`builtin_registry()` is a hard-coded list and nothing read
`importlib.metadata`. This module is that half, and it adds no second way in: a
plugin's step goes through `ProcessRegistry.register`, which already refuses a
duplicate `step_id` and lints for a process-global RNG (§5.2). The two rules a
plugin can break are enforced at the door it comes through.

## What an entry point may resolve to

```toml
[project.entry-points."nanofab_v3.processes"]
spin_on_glass = "nanofab_plugin_example:SPIN_ON_GLASS"   # one step
everything    = "nanofab_plugin_example:register"        # a callable
```

Either a `ProcessStep` — the ordinary case, one step per entry point, no
boilerplate — or a callable taking the registry, for a package that registers
several or has setup to do. The two are told apart by `isinstance(obj,
ProcessStep)`, which is unambiguous because the protocol is `runtime_checkable`
and a plain function has no `step_id`.

## A broken plugin does not stop the application

Discovery returns a `DiscoveryReport` rather than raising. A plugin whose import
fails, whose object is the wrong shape, or whose `step_id` collides with a
builtin is **recorded and skipped**, and everything else still loads. The failure
mode this avoids is the one that matters for a delivered application: one stale
third-party package and the process list is empty, with a traceback where the
step list should be.

## What a frozen build sees

`importlib.metadata.entry_points()` in a PyInstaller build reads the metadata
that was frozen in, so an exe finds exactly the plugins that were installed when
it was built and no others (plan §11: "plugins usable in source installs; frozen
app extension = rebuild"). That is a statement about packaging, not a special
case in this code — and it is the same boundary `registry.implementation_digest`
crosses when it marks a source-less step `nosrc:`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
from typing import Callable

from nanofab_v3.processes.contract import ProcessStep
from nanofab_v3.processes.registry import ProcessRegistry, builtin_registry

ENTRY_POINT_GROUP = "nanofab_v3.processes"
"""The entry-point group a plugin declares its processes under."""


@dataclass(frozen=True)
class PluginFailure:
    """One entry point that could not be loaded, and why.

    Attributes:
        name: The entry point's name.
        source: Which distribution declared it, when that is known.
        reason: What went wrong, as text — an import error, a wrong shape, a
            duplicate `step_id`.
    """

    name: str
    source: str
    reason: str

    def describe(self) -> str:
        """One line for the run log."""
        where = f" (from {self.source})" if self.source else ""
        return f"plugin {self.name!r}{where} was skipped: {self.reason}"


@dataclass(frozen=True)
class DiscoveryReport:
    """What discovery found, loaded and refused.

    Attributes:
        loaded: `step_id`s that came from entry points, in the order registered.
        failures: The entry points that were skipped, with reasons.
    """

    loaded: tuple[str, ...] = ()
    failures: tuple[PluginFailure, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether every entry point that was found could be loaded."""
        return not self.failures

    def describe(self) -> tuple[str, ...]:
        """Lines for the run log — what loaded, then what did not."""
        lines = []
        if self.loaded:
            lines.append(f"plugins: registered {', '.join(self.loaded)}")
        lines.extend(failure.describe() for failure in self.failures)
        return tuple(lines)


def _entry_points(group: str) -> tuple[metadata.EntryPoint, ...]:
    """Every entry point in `group`, across every installed distribution."""
    return tuple(metadata.entry_points(group=group))


def discover_plugins(
    registry: ProcessRegistry,
    *,
    group: str = ENTRY_POINT_GROUP,
    entry_points: Callable[[str], tuple[metadata.EntryPoint, ...]] | None = None,
) -> DiscoveryReport:
    """Load every plugin in `group` into `registry`; report what did not load.

    Mutates the registry, exactly as `builtin_registry` does when it fills one:
    registration is a startup activity and there is one door. Never raises for a
    plugin's sake — see the module docstring for why an application that cannot
    start because of a stale third-party package is the failure worth avoiding.

    `entry_points` is the seam a test replaces to describe an environment that
    does not exist on the machine running it. Nothing else should pass it.
    """
    find = entry_points or _entry_points
    loaded: list[str] = []
    failures: list[PluginFailure] = []

    for point in find(group):
        source = getattr(getattr(point, "dist", None), "name", "") or ""
        try:
            obj = point.load()
        except Exception as error:  # noqa: BLE001 - any import failure is one plugin's
            failures.append(PluginFailure(point.name, source, f"{type(error).__name__}: {error}"))
            continue

        before = set(registry.steps)
        try:
            if isinstance(obj, ProcessStep):
                registry.register(obj)
            elif callable(obj):
                obj(registry)
            else:
                raise TypeError(
                    f"{obj!r} is neither a ProcessStep nor a callable taking a registry"
                )
        except Exception as error:  # noqa: BLE001 - a bad plugin is skipped, not fatal
            failures.append(PluginFailure(point.name, source, f"{type(error).__name__}: {error}"))
            continue
        loaded.extend(sorted(set(registry.steps) - before))

    return DiscoveryReport(tuple(loaded), tuple(failures))


def application_registry(
    *, plugins: bool = True, group: str = ENTRY_POINT_GROUP
) -> tuple[ProcessRegistry, DiscoveryReport]:
    """The registry an application runs on: the builtins, then the plugins.

    Separate from `builtin_registry()` on purpose, and the separation is not
    cosmetic. `builtin_registry()` has to be a fixed set — the recipe hashes and
    implementation digests the replay cache is keyed on (plan §21.1) are computed
    against a registry, and a test whose registry depended on what happened to be
    installed would be a test with a different answer on every machine. So the
    tests take the builtins and the *application* takes this.
    """
    registry = builtin_registry()
    if not plugins:
        return registry, DiscoveryReport()
    return registry, discover_plugins(registry, group=group)
