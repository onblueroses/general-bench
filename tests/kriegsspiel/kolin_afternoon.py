"""The scripted Kolín afternoon, a test fixture: the historical orders at their historical times
played script against script on the Kolín test pack, with its recorded Jev fixtures.

    res = run_afternoon(mode="replay", log=tmp / "run.jsonl")

The orders are the pack's `script.json`; KOLIN_ORDERS keeps them in code so the export can be
checked (test_engine_scenario_pack.py).
"""

from __future__ import annotations

from pathlib import Path

from test_engine_kit import KOLIN

from kriegsspiel.clock import at_minute
from kriegsspiel.jev import DEFAULT_FIXTURES
from kriegsspiel.play import GameResult, run_script

AFTERNOON_FIXTURES = DEFAULT_FIXTURES / "kolin_afternoon"
AFTERNOON_SEED = 1757

# (clock time, side, order). Sources for the plan: docs/kolin-test-pack.md (KRO, Duffy).
# Manstein's early wheel into the Croats of Chocenice at about 14:30 is the historical
# departure from the King's plan.
KOLIN_ORDERS: list[tuple[str, str, str]] = [
    (
        "13:00",
        "prussia",
        (
            "Hülsen, march east along the Kaiserstrasse past Chocenice and storm Křečhoř, "
            "then hold the village."
        ),
    ),
    (
        "13:00",
        "prussia",
        (
            "Tresckow, follow Hülsen with the left wing infantry along the road and support his "
            "attack on Křečhoř."
        ),
    ),
    (
        "13:00",
        "prussia",
        (
            "Zieten, take the hussars against Nádasdy's horse beyond Kutlíře and drive them off "
            "the flank of the advance."
        ),
    ),
    (
        "13:00",
        "prussia",
        (
            "Bevern, keep the right wing in column on the Kaiserstrasse behind Tresckow and do not "
            "engage the Austrian front."
        ),
    ),
    (
        "13:00",
        "prussia",
        (
            "The heavy artillery will unlimber by the Zlaté Slunce inn and bombard the Křečhoř "
            "heights."
        ),
    ),
    (
        "13:15",
        "prussia",  # the King's answer to Zieten's request for a clearer objective
        (
            "Zieten, ride with the hussars to Kutlíře and charge the Austrian hussars you find "
            "there."
        ),
    ),
    ("14:30", "prussia", "Manstein, wheel right at once and clear the Croats out of Chocenice."),
    (
        "13:00",
        "austria",
        ("The whole army stands fast where it is on the heights; nobody is to descend to pursue."),
    ),
    (
        "13:00",
        "austria",
        (
            "Nádasdy, take your cavalry against the Prussian hussars beyond Kutlíře and keep them "
            "off our right at Křečhoř."
        ),
    ),
    (
        "13:00",
        "austria",
        "Feuerstein, the artillery will bombard the Prussian columns on the Kaiserstrasse.",
    ),
    (
        "15:00",
        "austria",
        "Colloredo, march the reserve at once to Křečhoř and hold the village and the oak wood.",
    ),
]


def kolin_script(side: str, start: str = "13:00") -> list[tuple[int, str]]:
    """A side's KOLIN_ORDERS as a ScriptedCommander script (minute, text)."""
    return [(int(at_minute(start, at)), text) for at, s, text in KOLIN_ORDERS if s == side]


def run_afternoon(mode: str = "replay", log: str | Path | None = None) -> GameResult:
    """The Kolín pack played script against script on the afternoon's seed and fixtures, until
    the umpire ends the battle or the clock reaches 19:30 (the pack names no end)."""
    return run_script(KOLIN, mode, log, AFTERNOON_SEED, fixture_dir=AFTERNOON_FIXTURES)
