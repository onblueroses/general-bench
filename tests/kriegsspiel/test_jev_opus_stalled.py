"""The 23 Prussian orders of the first LLM game (runs/kolin-opus-1) that drew a staff question,
replayed against the Prussian side view at 13:00 (a proxy: in the game each was read against the
picture of its own minute).

On this proxy the game's own staff translated 6 of the 23 without a question; the adjutant
staff (per-clause reading, mention rules, defaults, check before sending) translates 19. Of
the 4 still asked back, 3 name enemy infantry the side cannot see at 13:00 ("I cannot see
..."), which is the right answer for that picture. JEV_MODE=record re-records.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from kriegsspiel.jev import DEFAULT_FIXTURES, JevClient
from kriegsspiel.staff import JevStaff, view_from_json
from kriegsspiel.types import TaskKind

VIEWS = Path(__file__).parent / "fixtures" / "jev" / "views"
MODE = os.environ.get("JEV_MODE", "replay")


def test_stalled_orders_now_translate():
    sv = view_from_json(json.loads((VIEWS / "kolin_1300_prussia.json").read_text()))
    orders = json.loads((VIEWS / "opus_stalled_orders.json").read_text())["orders"]
    assert len(orders) == 23
    staff = JevStaff(JevClient(mode=MODE, fixture_dir=DEFAULT_FIXTURES))
    results = [staff.translate(o["text"], sv) for o in orders]
    clear = [r for r in results if not r.clarifications]
    assert len(clear) == 19
    unseen = [r for r in results if any("I cannot see" in c for c in r.clarifications)]
    assert len(unseen) == 3
    # the three headquarters orders move the army root
    hq = [r for o, r in zip(orders, results, strict=True) if "eadquarters" in o["text"]]
    assert len(hq) == 3
    assert all([t.kind for t in r] == [TaskKind.MOVE_HQ] for r in hq)
