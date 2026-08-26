"""The application's command line — and the `--selftest` plan §14's DoD needs.

`python -m nanofab_v3` starts the application; the frozen exe (`nanofab_v3.spec`)
runs this same `main`. Everything the exe can do that is not "show a window" is
here, because the exe is the thing that has to be checkable on a machine that is
not this one.

    nanofab_v3                        start the application
    nanofab_v3 --selftest             run S1-S5, print a line each, exit 0 or 1
    nanofab_v3 --selftest S1 S5       run some of them
    nanofab_v3 --selftest --report r  ... and write the result to a file
    nanofab_v3 --version              print the version and what is registered

`--selftest` is the decision `nanofab_v3.acceptance` records in full: the DoD is
a *checkable claim*, so it needs an exit code rather than a menu entry, a human
and a display.

## What `--version` reports, and why it is not just a number

It prints `code_version()`, how many processes are registered, how many
materials loaded and from where, and what entry-point discovery loaded or
refused. On somebody else's machine those are the first questions — "which build
is this", "does it have the steps", "does it have the *materials*", "did the
plugin load" — and a version string alone answers none of them. It is also the
one place a `DiscoveryReport`'s or a `LibraryReport`'s failures are visible
without opening the application, which matters because neither ever raises.

The material count is there because of how its absence fails. The library is data
files inside the package (roadmap E14) and a build that did not collect them
starts fine and dies at the first rate lookup; `materials: 0` on the version line
says so in one word.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from nanofab_v3 import __version__
from nanofab_v3.acceptance import ScenarioResult, run_all, scenarios
from nanofab_v3.io.manifest import code_version
from nanofab_v3.materials import application_library
from nanofab_v3.processes.plugins import application_registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nanofab_v3",
        description="NanoFab structure model v2 — the application and its self-test.",
    )
    parser.add_argument(
        "--selftest",
        nargs="*",
        metavar="SCENARIO",
        default=None,
        help="run the acceptance scenarios (all of them, or the named ones) and exit",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="write the self-test result to this file as well as printing it",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="print the scenarios --selftest would run",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the version, the registered processes and the plugin report",
    )
    return parser


def selftest(
    names: Sequence[str] | None = None,
    *,
    report: Path | None = None,
    stream=None,
) -> int:
    """Run the acceptance scenarios; return 0 when every one passed.

    Prints a line per scenario as it finishes rather than a block at the end: at
    a couple of seconds each, a self-test that says nothing for twenty seconds
    looks hung on a machine nobody has run it on before.
    """
    out = stream if stream is not None else sys.stdout
    print(f"NanoFab structure model {__version__} — acceptance scenarios", file=out)

    lines: list[str] = []

    def show(result: ScenarioResult) -> None:
        print(result.describe(), file=out, flush=True)
        lines.append(result.describe())
        for failure in result.failures:
            print(f"       {failure}", file=out, flush=True)
            lines.append(f"       {failure}")

    results = run_all(names or None, progress=show)
    if not results:
        print(f"no scenario matched {list(names or [])}", file=out)
        return 2

    passed = sum(1 for result in results if result.ok)
    total = sum(result.seconds for result in results)
    summary = f"{passed} of {len(results)} scenarios passed in {total:.1f} s"
    print(summary, file=out)
    lines.append(summary)

    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"report written to {report}", file=out)
    return 0 if passed == len(results) else 1


def describe_build(stream=None) -> int:
    """Print what this build is and what it can run — see the module docstring."""
    out = stream if stream is not None else sys.stdout
    registry, discovery = application_registry()
    print(f"NanoFab structure model {__version__}", file=out)
    print(f"cache code version: {code_version()}", file=out)
    print(f"registered processes: {len(registry)}", file=out)
    # Which axis the *recipe* half of the cache key is on (plan §21.1). A frozen
    # build has no source for `inspect.getsource`, so its digests fall back to
    # the contract alone and say `nosrc:` — which is what keeps an exe and a
    # source install from trading cache entries under a key claiming they are
    # the same code. Printed because on somebody else's machine "why did my
    # cache not hit" is otherwise unanswerable.
    if len(registry):
        sample = registry.digest(sorted(registry.steps)[0])
        mode = "wrapper source" if sample.startswith("src:") else "contract only (no source)"
        print(f"step digests: {mode}", file=out)
    _, library_report = application_library()
    for line in library_report.describe():
        print(line, file=out)
    for root in library_report.roots:
        print(f"materials root: {root}", file=out)
    for line in discovery.describe() or ("plugins: none found",):
        print(line, file=out)
    if getattr(sys, "frozen", False):
        print("frozen build (PyInstaller)", file=out)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """The one entry point: the exe's, `python -m nanofab_v3`'s, and a test's."""
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    if args.version:
        return describe_build()
    if args.list_scenarios:
        for scenario in scenarios():
            print(f"{scenario.name:<4} {scenario.title}")
        return 0
    if args.selftest is not None:
        return selftest(args.selftest, report=args.report)

    from nanofab_v3.ui.window import run

    return run(sys.argv[:1])
