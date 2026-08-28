"""The command line and the self-test path (plan §11, §14) — milestone M5.

Plan §14's DoD for M5 is *"packaged exe runs S1-S4"*, and an exe carries no
pytest. So the scenarios are shipped code (`nanofab_v3.acceptance`, asserted
in `tests/test_scenarios.py`) and `nanofab_v3.cli` is the door to them. What is
tested here is the door: exit codes, the report file, what `--version` says, and
that the self-test's registry is the *builtin* one so a third-party plugin
cannot turn S1 red.

The frozen build itself is not tested here — building it takes a minute and a
half and 115 MB, which is a release step rather than a suite one. What was
measured on it is written up in `memory.md` and plan §21.5.
"""

from __future__ import annotations

import io

import pytest

from nanofab_v3 import __version__, acceptance
from nanofab_v3.cli import build_parser, describe_build, main, selftest
from nanofab_v3.processes import ProcessRegistry, builtin_registry


def test_the_selftest_runs_every_scenario_and_exits_zero() -> None:
    """The DoD, at the seam the exe uses. ~7 s of solver."""
    out = io.StringIO()

    code = selftest(stream=out)

    printed = out.getvalue()
    assert code == 0
    assert __version__ in printed
    for scenario in acceptance.scenarios():
        assert scenario.name in printed
    assert f"{len(acceptance.scenarios())} scenarios passed" in printed


def test_naming_scenarios_runs_only_those() -> None:
    out = io.StringIO()

    code = selftest(["s1", "S5"], stream=out)

    assert code == 0
    assert "2 of 2 scenarios passed" in out.getvalue()
    assert "S4" not in out.getvalue()


def test_a_name_that_matches_nothing_is_its_own_exit_code() -> None:
    """Not 0 (it did not pass) and not 1 (nothing failed) — the user mistyped."""
    out = io.StringIO()

    assert selftest(["S9"], stream=out) == 2
    assert "no scenario matched" in out.getvalue()


def test_the_report_file_holds_what_was_printed(tmp_path) -> None:
    """For a build that would rather read a file than watch a console."""
    report = tmp_path / "reports" / "selftest.txt"
    out = io.StringIO()

    selftest(["S5"], report=report, stream=out)

    written = report.read_text(encoding="utf-8")
    assert "S5" in written
    assert "1 of 1 scenarios passed" in written


def test_describe_build_answers_the_three_questions_a_stranger_has() -> None:
    """Which build, does it have the steps, did the plugin load."""
    out = io.StringIO()

    assert describe_build(stream=out) == 0

    printed = out.getvalue()
    assert __version__ in printed
    assert f"registered processes: {len(builtin_registry())}" in printed
    assert "step digests:" in printed
    assert "plugins" in printed


def test_the_digest_mode_is_reported_because_a_frozen_build_differs() -> None:
    """Plan §21.1's fallback, made visible.

    A source install digests each step's wrapper; a frozen build has no source
    and falls back to the contract alone, marking itself `nosrc:` so the two
    never trade cache entries under a key claiming they are the same code.
    Measured on the exe: it reports "contract only (no source)".
    """
    out = io.StringIO()
    describe_build(stream=out)

    assert "step digests: wrapper source" in out.getvalue()


def test_the_selftest_runs_on_the_builtins_and_not_on_the_plugins() -> None:
    """A third-party plugin that failed to load must not be able to fail S1.

    `run_all` defaults to `builtin_registry()` deliberately: a self-test says
    whether *this build's model* works. Whether the plugins loaded is a separate
    question, and `--version` is where it is answered.
    """
    empty = ProcessRegistry()

    results = acceptance.run_all(["S5"], registry=empty)

    assert not results[0].ok  # an empty registry cannot run it...
    assert "KeyError" in results[0].failures[0]

    # ... and the default is the builtins, not whatever discovery found.
    assert acceptance.run_all(["S5"])[0].ok


def test_the_parser_matches_what_the_docstring_promises() -> None:
    parser = build_parser()

    assert parser.parse_args([]).selftest is None
    assert parser.parse_args(["--selftest"]).selftest == []
    assert parser.parse_args(["--selftest", "S1", "S2"]).selftest == ["S1", "S2"]
    assert parser.parse_args(["--version"]).version is True


def test_main_dispatches_without_needing_a_display(capsys) -> None:
    """Everything the exe can do that is not "show a window" goes through here."""
    assert main(["--version"]) == 0
    assert main(["--list-scenarios"]) == 0
    listed = capsys.readouterr().out

    assert all(scenario.name in listed for scenario in acceptance.scenarios())


@pytest.mark.parametrize("names", [["S2", "S2c"], ["S5", "S5c"]])
def test_every_scenario_ships_with_its_control(names) -> None:
    """A scenario without its control cannot tell a working model from a lucky one.

    S2 and S5 carry theirs into the exe; S1's, S3's and S4's live in
    `tests/test_scenarios.py`, which is the honest split — a self-test is not a
    test suite, and `nanofab_v3.acceptance` says so in as many words.
    """
    out = io.StringIO()

    assert selftest(names, stream=out) == 0
    assert "2 of 2 scenarios passed" in out.getvalue()
