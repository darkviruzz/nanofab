"""`python -m nanofab_v3` — the application, and its `--selftest` (plan §14).

One entry point with a command line, so that everything the packaged exe can do
is reachable the same way from a source checkout. `python -m nanofab_v3.ui` is
still there and still starts the window directly; this is the door the exe uses,
and the only one with a `--selftest`.
"""

from __future__ import annotations

import sys

from nanofab_v3.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
