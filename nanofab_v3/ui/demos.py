"""The demos a picker offers, each with the sentence that says what to watch for.

Roadmap M8's sixth item: *"Demo-Picker statt des einen hartcodierten Demos, mit
Erklärtext je Demo"*. Until now the application opened with one lift-off wired
into the window, which meant the only recipe anybody saw was the only recipe
anybody could see.

A `Demo` is a recipe plus prose, and the prose is the point. A demo that runs and
produces a shape teaches nothing on its own — what teaches is knowing what the
shape was supposed to show and what would have happened otherwise, which is why
every entry carries `watch_for` as well as a description.

**Qt-free**, like `scene`, `session`, `wafer` and `presets`: these are recipes and
sentences, and a headless test runs every one of them. The picker is a menu in
`ui.window` and decides nothing.

The recipes are written against the material library, not against numbers typed
here. If a rate is wrong the demo shows the wrong thing, which is the correct
failure — a demo that hard-coded its own physics would keep working while the
library it is supposed to illustrate drifted away from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from nanofab_v3.materials import (
    ALUMINA,
    CHROME,
    METAL,
    PARTICLE,
    RESIST,
    SILICON,
    TITANIA,
)
from nanofab_v3.model.grid import Grid
from nanofab_v3.processes.substrate import cross_section_grid
from nanofab_v3.runtime.run import RecipeStep


@dataclass(frozen=True)
class Demo:
    """One runnable recipe, and what somebody is supposed to see in it.

    Attributes:
        key: Stable id, what a menu action carries.
        title: The menu entry.
        summary: One line, for the menu's tooltip.
        watch_for: What to look at while it runs, and what it would look like if
            the mechanism it demonstrates were absent. The reason a demo is worth
            more than a screenshot.
        grid: The domain it needs.
        steps: The chain, in order.
    """

    key: str
    title: str
    summary: str
    watch_for: str
    grid: Grid
    steps: tuple[RecipeStep, ...] = ()

    def describe(self) -> str:
        """Title, summary and what to watch for — what the run log gets."""
        return f"{self.title} — {self.summary}\n{self.watch_for}"


def _step(step_id: str, **params: object) -> RecipeStep:
    return RecipeStep(step_id, dict(params))


def lift_off() -> Demo:
    """S1, which is what the application has always opened with."""
    return Demo(
        key="lift_off",
        title="Naive lift-off",
        summary="resist, a window, evaporated metal, and a solvent",
        watch_for=(
            "The metal in the window and the metal on the resist never touch, because "
            "an evaporation is a point source and a vertical wall is edge-on to it. "
            "That is the whole reason lift-off works, and `deposit.sputter` on the same "
            "stack breaks it."
        ),
        grid=cross_section_grid(width=300.0, thickness=40.0, headroom=200.0),
        steps=(
            _step("substrate.select", material=str(SILICON), surface=40.0),
            _step("resist.spin_coat", material=str(RESIST), thickness=90.0),
            _step(
                "litho.expose_ideal",
                material=str(RESIST),
                pattern="window",
                center=150.0,
                width=100.0,
            ),
            _step("develop.ideal", material=str(RESIST)),
            _step("deposit.evaporate", material=str(METAL), thickness=20.0),
            _step("strip.lift_off", material=str(RESIST)),
        ),
    )


def chrome_hard_mask_grating() -> Demo:
    """A fused-silica grating patterned through a chromium hard mask."""
    return Demo(
        key="chrome_grating",
        title="Fused-silica grating through a chromium hard mask",
        summary="the photomask process: pattern the chromium, then let it hold the line",
        watch_for=(
            "Why the chromium is there at all. The fluorine etch takes resist about 30 "
            "times faster than chromium, so a resist mask would be gone long before the "
            "grating was deep — and the flanks stay steep because that chemistry has a "
            "vertical rate and no lateral one. Compare the chromium etch itself, which "
            "is a wet bath and undercuts its resist by as much as it etches down."
        ),
        grid=cross_section_grid(width=1200.0, thickness=300.0, headroom=400.0, spacing=2.0),
        steps=(
            _step(
                "substrate.select",
                preset="wafer_fs_100",
                surface=300.0,
                domain_width=1200.0,
                headroom=400.0,
                spacing=2.0,
            ),
            # 480 s at the table's 0.0833 nm/s is 40 nm of chromium.
            _step("deposit.sputter_rate", material=str(CHROME), duration=480.0),
            _step("resist.spin_coat", material=str(RESIST), spin_speed=1000.0),
            _step(
                "litho.expose_ideal",
                material=str(RESIST),
                pattern="grating",
                period=300.0,
                duty=0.5,
            ),
            _step("develop.ideal", material=str(RESIST)),
            # Chlorine takes the chromium and leaves the glass at exactly zero.
            _step("etch.rie_chlorine", duration=60.0),
            # Oxygen takes the resist and leaves both the chromium and the glass.
            _step("etch.rie_oxygen", duration=150.0),
            # Fluorine cuts 200 nm of grating; the chromium loses about 8.
            _step("etch.icp_fluorine", duration=240.0),
            # And the mask comes off in a bath that attacks nothing else.
            _step("etch.wet_cr", duration=4.0),
        ),
    )


def titania_grating_on_an_etch_stop() -> Demo:
    """A TiO2 grating that stops on a thin alumina layer."""
    return Demo(
        key="titania_stop",
        title="TiO2 grating on an Al2O3 etch stop",
        summary="a thin layer that decides where the etch ends",
        watch_for=(
            "The floor of the grating is flat and sits exactly on the alumina, although "
            "nothing in the recipe says when to stop: the etch runs long on purpose. "
            "Alumina survives a fluorine plasma because AlF3 is not volatile, and the "
            "25:1 that follows is what turns a timed etch into a self-limiting one. "
            "Take the alumina out and the same recipe cuts into the substrate."
        ),
        grid=cross_section_grid(width=1200.0, thickness=300.0, headroom=600.0, spacing=2.0),
        steps=(
            _step(
                "substrate.select",
                preset="wafer_fs_100",
                surface=300.0,
                domain_width=1200.0,
                headroom=600.0,
                spacing=2.0,
            ),
            _step("deposit.ald", material=str(ALUMINA), thickness=30.0),
            _step("deposit.conformal_offset", material=str(TITANIA), thickness=120.0),
            # 400 nm of resist, typed rather than spun: the fluorine etch takes
            # resist twice as fast as titania, so a 150 nm coat would be gone
            # before the film was through and this demo would be about mask
            # selectivity instead of about the etch stop. (Which is what the
            # chromium demo is for.)
            _step("resist.spin_coat", material=str(RESIST), thickness=400.0),
            _step(
                "litho.expose_ideal",
                material=str(RESIST),
                pattern="grating",
                period=300.0,
                duty=0.5,
            ),
            _step("develop.ideal", material=str(RESIST)),
            # 350 s is 175 nm of titania against a 120 nm film: deliberately long,
            # because the point is that the alumina ends the etch and not the clock.
            _step("etch.icp_fluorine", duration=350.0),
            _step("etch.rie_oxygen", duration=400.0),
        ),
    )


def black_silicon() -> Demo:
    """Micromasking, the mechanism S5 already proves, as a surface rather than a defect."""
    return Demo(
        key="black_silicon",
        title="Black silicon by micromasking",
        summary="debris that masks its own pillars",
        watch_for=(
            "Nothing here says 'make pillars'. Particles land, the etch cannot remove "
            "what they cover, and a forest is what is left over — which is exactly the "
            "S5 mechanism at a scale where it stops being a defect and becomes a "
            "surface. Run `clean.particles` before the etch instead of after and the "
            "surface comes out flat."
        ),
        grid=cross_section_grid(width=600.0, thickness=200.0, headroom=200.0),
        steps=(
            _step("substrate.select", material=str(SILICON), surface=200.0),
            _step("particle.seed", material=str(PARTICLE), count=12, radius=14.0,
                  radius_spread=0.3),
            _step("etch.icp_fluorine", duration=90.0),
            # After, not before: a particle the etch has undercut is still there,
            # and what it masked is still masked.
            _step("clean.particles", material=str(PARTICLE)),
        ),
    )


DEMOS: tuple[Demo, ...] = (
    lift_off(),
    chrome_hard_mask_grating(),
    titania_grating_on_an_etch_stop(),
    black_silicon(),
)
"""Every demo the picker offers, in the order it offers them.

Lift-off first because it is the one the application has always opened with and
the one the acceptance scenarios are written around; the three the roadmap names
after it, in increasing order of how much of the model they lean on.
"""

DEMOS_BY_KEY: Mapping[str, Demo] = {demo.key: demo for demo in DEMOS}


def demo(key: str) -> Demo:
    """One demo by key."""
    try:
        return DEMOS_BY_KEY[key]
    except KeyError:
        raise ValueError(f"no demo {key!r}; there are {sorted(DEMOS_BY_KEY)}") from None
