"""Mirror (data/mirror-fords) turned by 180° about the village is the turned game, bit for bit.

The engine is symmetric under the 180° rotation of the field (test_symmetry.py), so a pack laid
out exactly symmetric plays exactly symmetric games: Mirror's raster, features and deployment
are each other's image (test_pack_mirror.py), and the turned pack (every body keeping its id
and side, so each army stands where the other stood) must give the turned game at every minute.
Because the pack is its own image with the colours exchanged, each game is also its own mirror:
every Red body stands at the image of its Blue namesake, minute by minute.

Mirror found a defect the flat Plain could not: the doctrine bot's guns pick the highest ground
near the village, and Mirror's two ridges are equally high images of each other, so the choice
fell to the bearing's index (bot._commanding) and both armies' guns went to the same ridge. The
choice compares distances to the millimetre and takes the bearing's index last; the control
below puts the old key back.

A second defect parted seeds 4 and 5: late in the day at a ford a hussar regiment ended its
move on the ford's route node exactly at contact distance from a dragoon regiment that had
halted against the cuirassiers on the same node, and the meeting time of a path and of its
image differed in the last bits (drill._first_meeting on in-minute traces, which Sim._snap
did not snap), so at exactly 60 m one image met and the other did not. Every point of a path
stands on Sim._snap's lattice (movement.follow_route), resolve_moves works on offsets from the
centre, and a halt is set on the lattice (drill._cut). The control below takes the lattice
steps out again and a game parts: seed 4 on the first layout of the ground, seed 15 on the
present one (without the lattice seeds 1-14 and 16-24 stay turned)."""

from __future__ import annotations

from pathlib import Path

import pytest
import symmetry_kit as kit
from test_symmetry import turned

from kriegsspiel import bot as botmod
from kriegsspiel import geometry as geo

ROOT = Path(__file__).resolve().parents[2]
MIRROR = ROOT / "data" / "mirror-fords"
CENTRE = (4000.0, 3000.0)


@pytest.fixture(scope="module")
def rotated(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("mirror") / "mirror-rotated"
    assert kit.rotate_pack(MIRROR, d) == CENTRE
    return d


def own_mirror(rows: list) -> str | None:
    """None if, at every minute of one game, each Red body is the image of its Blue namesake
    (the pack with the colours exchanged is the turned pack); else the first difference."""
    cx, cy = CENTRE
    for t, us in rows:
        for uid, a in us.items():
            if uid.startswith("R-"):
                b = us["B-" + uid[2:]]
                want = (2.0 * cx - a[0], 2.0 * cy - a[1], (a[2] + 180.0) % 360.0, *a[3:])
                if b != want:
                    return f"minute {t}: {uid} {a}, its namesake {b}"
    return None


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 15])
def test_mirror_turned_by_180_degrees_is_the_turned_game(rotated, seed):
    ra, a_rows = kit.trace_game(MIRROR, seed)
    rb, b_rows = kit.trace_game(rotated, seed)
    assert turned(a_rows, b_rows, CENTRE) is None
    oa, ob = ra.verdict.ordinal, rb.verdict.ordinal
    assert (ob["winner"], ob["how"], ob["clock"]) == (oa["winner"], oa["how"], oa["clock"])
    # nothing tells the armies apart: each game is its own mirror, and a mirror's verdict is a
    # draw (both broken in the same minute, or the village contested to the end)
    assert own_mirror(a_rows) is None
    assert oa["winner"] == "draw"
    m = oa["margin"]
    assert m["red"] == m["blue"]


def test_the_check_sees_off_lattice_steps_within_the_minute(rotated, monkeypatch):
    """Positive control: with the steps within the minute off the lattice again (snap_m the
    identity in movement and geometry), seed 15 parts (minute 135, a
    grenadier battalion's facing in the village; turned with the lattice on, above)."""
    from kriegsspiel import movement

    monkeypatch.setattr(movement, "snap_m", lambda v: v)
    monkeypatch.setattr(geo, "snap_m", lambda v: v)
    _, a_rows = kit.trace_game(MIRROR, 15)
    _, b_rows = kit.trace_game(rotated, 15)
    assert turned(a_rows, b_rows, CENTRE) is not None


def _old_commanding(self, p, enemy_c):
    """bot._commanding with ties of height and enemy distance broken by the bearing's index."""
    best = None
    for r in botmod.GUN_RADII:
        for k in range(botmod.GUN_BEARINGS if r > 0 else 1):
            q = geo.offset(p, k * 360.0 / botmod.GUN_BEARINGS, r) if r > 0 else p
            if not self.world.in_bounds(q[0], q[1]) or not self.world.passable(q[0], q[1], "art"):
                continue
            key = (round(self.world.elev(q[0], q[1]), 1), -geo.dist(q, enemy_c), -r, k)
            if best is None or key > best[0]:
                best = (key, (float(q[0]), float(q[1])))
    return best[1] if best else p


def test_the_guns_go_to_their_own_ridge():
    """Each army's reserve guns are sent to the high ground on its own side of the village,
    and the old key sent both to the same ridge (positive control)."""
    from kriegsspiel.build import build

    def targets() -> dict[str, tuple]:
        sim = build(MIRROR, 1, "stub")
        out = {}
        for side in ("red", "blue"):
            b = botmod.BotCommander(sim, side, "strong")
            b.plan(0)
            (out[side],) = set(b.guns.values())  # both batteries to one place
        return out

    new = targets()
    assert new["red"][0] < CENTRE[0] < new["blue"][0]  # each on its own bank
    assert new["blue"] == pytest.approx(
        (2 * CENTRE[0] - new["red"][0], 2 * CENTRE[1] - new["red"][1])
    )
    mp = pytest.MonkeyPatch()
    mp.setattr(botmod.BotCommander, "_commanding", _old_commanding)
    try:
        old = targets()
    finally:
        mp.undo()
    assert old["red"] == old["blue"]
