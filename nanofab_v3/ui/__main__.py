"""`python -m nanofab_v3.ui` — start the application (plan §10).

The one entry point that needs a display. Everything it shows is derived from a
`Session`, which needs none, so a headless check runs the same code path without
this module.
"""

from __future__ import annotations

import sys

from nanofab_v3.ui.window import run

if __name__ == "__main__":
    raise SystemExit(run(sys.argv))
