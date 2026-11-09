"""The order in which the engine takes bodies decides nothing.

A tick resolved in id order let a body drill against the positions of the bodies that had
already moved that minute, and resolved new contacts pair by pair in id order; on Plain
(data/plain-crossroads), a battle symmetric under the 180° rotation, the side whose formation
ids sorted first then won every bot game. So every body moves against the field as it stood at
the start of the minute (Sim._movement), where paths meet is settled in time
(drill.resolve_moves), a body takes part in one new clash a minute and who strikes first in a
mutual clash is a draw keyed by where the bodies stand (combat.melee_phase, Sim.event_rng).
Renaming the armies is therefore invisible to the engine: Plain with the two colours swapped
(ids, side names, names) plays the same game with the colours swapped.

The ground decides nothing either. A router whose 100 m lattice is anchored at the raster's
corner and breaks ties by the order it meets nodes gave the two armies different first marches,
and the eastern army won every game. So every lookup and the lattice are anchored at the
field's centre (world._sym_index, World._nodes), the fastest route is drawn by keys the
rotation keeps (world._canonical_path), draws and event order are keyed by the offset from the
centre with its sign turned (Sim.place_key), positions are set on a lattice about the centre
every minute (Sim._snap), and two bodies alike in every respect that go in at each other from
each other's image make an even clash (combat._even_clash). Plain turned by 180° about its
centre (ground, features, deployment; every body keeps its id and side, so each army stands
where the other stood) is then the turned game bit for bit, and a march and its turned march
take turned routes."""

from __future__ import annotations

import heapq
import math
from pathlib import Path

import pytest
import symmetry_kit as kit
from test_engine_kit import body, make_sim

from kriegsspiel import drill
from kriegsspiel.combat import CONTACT_M
from kriegsspiel.movement import BASE_SPEED
from kriegsspiel.play import play_game
from kriegsspiel.sim import Sim
from kriegsspiel.types import Ref, RefKind, Task, TaskKind, UnitState
from kriegsspiel.world import World

ROOT = Path(__file__).resolve().parents[2]
PLAIN = ROOT / "data" / "plain-crossroads"
OTHER = {"red": "blue", "blue": "red"}


def swapped_pack(dst: Path) -> Path:
    """Plain with the colours swapped (symmetry_kit.swapped_pack)."""
    return kit.swapped_pack(PLAIN, dst)


def outcome(scenario: Path, seed: int) -> dict:
    res = play_game(
        {"red": "bot:strong", "blue": "bot:strong"},
        mode="stub",
        seed=seed,
        log=None,
        speed=None,
        scenario=scenario,
        out=None,
    )
    o = res.verdict.ordinal or {}
    share = {}
    for side in ("red", "blue"):
        us = [u for u in res.sim.forces.units.values() if u.side == side]
        share[side] = sum(u.casualties for u in us) / sum(u.casualties + u.men for u in us)
    return {
        "winner": o.get("winner"),
        "how": o.get("how"),
        "clock": o.get("clock"),
        "share": share,
        "ticks": res.sim.now,
    }


def mirrored(a: dict, b: dict) -> bool:
    """b is a with the colours swapped: same verdict by swapped colour, same minute, the
    casualty shares exchanged."""
    win = OTHER.get(a["winner"], a["winner"])
    return (
        b["winner"] == win
        and b["how"] == a["how"]
        and b["clock"] == a["clock"]
        and b["ticks"] == a["ticks"]
        and all(
            math.isclose(b["share"][OTHER[s]], a["share"][s], abs_tol=1e-9) for s in ("red", "blue")
        )
    )


@pytest.fixture(scope="module")
def swapped(tmp_path_factory) -> Path:
    return swapped_pack(tmp_path_factory.mktemp("plain") / "plain-swapped")


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_plain_with_the_colours_swapped_is_the_mirrored_game(swapped, seed):
    a = outcome(PLAIN, seed)
    b = outcome(swapped, seed)
    assert a["winner"] in ("red", "blue", "draw", "undecided"), a
    assert mirrored(a, b), (a, b)


def test_the_check_sees_an_id_order_engine(swapped, monkeypatch):
    """Positive control: with the old movement phase (each body drills in id order against
    the bodies already moved, resolve_moves applied body by body) the swapped game is not the
    mirror image, so the test above would fail on the defect it guards."""

    def sequential(self: Sim) -> None:
        for u in self.forces.units.values():
            drill.drill(self, u)

    monkeypatch.setattr(Sim, "_movement", sequential)
    a, b = outcome(PLAIN, 1), outcome(swapped, 1)
    assert not mirrored(a, b), (a, b)


def _charge(south: str, north: str) -> tuple[float, float, float]:
    """Two equal cuirassier regiments charge each other head on across a flat field: where
    they meet (the midpoint's y and their distance) as they ask for the clash."""
    a = body(south, "blue", "cuirassier", 2000.0, 1300.0, UnitState.LINE, facing=0.0, men=450)
    b = body(north, "red", "cuirassier", 2000.0, 2700.0, UnitState.LINE, facing=180.0, men=450)
    s = make_sim([a, b])
    met: list[tuple[float, float, float]] = []
    orig = s.request_melee

    def spy(x, y, gait):
        met.append(((x.y + y.y) / 2.0, math.hypot(x.x - y.x, x.y - y.y), x.y))
        orig(x, y, gait)

    s.request_melee = spy
    s.submit_tasks("blue", [Task(TaskKind.CHARGE, south, Ref(RefKind.ENEMY, north))])
    s.submit_tasks("red", [Task(TaskKind.CHARGE, north, Ref(RefKind.ENEMY, south))])
    for _ in range(20):
        s.step()
        if met:
            break
    assert met
    return met[0]


def test_two_charges_meet_where_their_speeds_put_them_whatever_the_ids():
    mid, gap, _ = _charge("a", "z")
    assert mid == pytest.approx(2000.0, abs=0.01)  # each covered half the closing ground
    assert gap == pytest.approx(CONTACT_M, abs=0.01)  # at contact, not inside it
    mid2, gap2, _ = _charge("z", "a")  # the same charge with the ids the other way round
    assert (mid2, gap2) == pytest.approx((mid, gap), abs=1e-9)


# --------------------------------------------------------------------------------------------
# The 180° rotation of the field


@pytest.fixture(scope="module")
def rotated(tmp_path_factory) -> tuple[Path, tuple[float, float]]:
    d = tmp_path_factory.mktemp("plain") / "plain-rotated"
    return d, kit.rotate_pack(PLAIN, d)


def turned(a_rows: list, b_rows: list, centre: tuple[float, float]) -> str | None:
    """None if game b is game a turned by 180° about `centre` at every minute, bit for bit
    (each body at the exact image of its place, facing the opposite way, in the same state,
    with the same men and morale); else the first difference."""
    cx, cy = centre
    if len(a_rows) != len(b_rows):
        return f"lengths {len(a_rows)} and {len(b_rows)}"
    for (ta, ua), (tb, ub) in zip(a_rows, b_rows, strict=True):
        assert ta == tb
        for uid, a in ua.items():
            want = (2.0 * cx - a[0], 2.0 * cy - a[1], (a[2] + 180.0) % 360.0, *a[3:])
            if ub[uid] != want:
                return f"minute {ta}: {uid} {ub[uid]} is not {want}"
    return None


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_plain_turned_by_180_degrees_is_the_turned_game(rotated, seed):
    d, centre = rotated
    ra, a_rows = kit.trace_game(PLAIN, seed)
    rb, b_rows = kit.trace_game(d, seed)
    assert turned(a_rows, b_rows, centre) is None
    oa, ob = ra.verdict.ordinal, rb.verdict.ordinal
    assert (ob["winner"], ob["how"], ob["clock"]) == (oa["winner"], oa["how"], oa["clock"])


def _corner_astar(self, s, g, cost, profile):
    """The corner-anchored router (positive control): A* with its heuristic on
    lattice indices, the first route found among equally fast ones, ties by node number."""
    cnx, dirs = self.cnx, self._DIRS
    h_rate, cm = 1.0 / max(BASE_SPEED[profile]), self.coarse_m
    gi, gj = g
    start, goal = s[0] * cnx + s[1], gi * cnx + gj
    best, came, heap, closed = {start: 0.0}, {}, [(0.0, start)], set()
    while heap:
        _f, cur = heapq.heappop(heap)
        if cur in closed:
            continue
        if cur == goal:
            break
        closed.add(cur)
        ci, cj = divmod(cur, cnx)
        for d in range(8):
            c = cost[ci, cj, d]
            if c == math.inf:
                continue
            di, dj = dirs[d]
            n = (ci + di) * cnx + cj + dj
            if best[cur] + c < best.get(n, math.inf) - 1e-12:
                best[n], came[n] = best[cur] + c, cur
                heapq.heappush(
                    heap, (best[n] + math.hypot(ci + di - gi, cj + dj - gj) * cm * h_rate, n)
                )
    if goal not in best:
        return None
    cells = [goal]
    while cells[-1] != start:
        cells.append(came[cells[-1]])
    return best[goal], [divmod(c, cnx) for c in reversed(cells)]


def test_the_check_sees_a_router_anchored_at_the_corner(rotated, monkeypatch):
    """Positive control: with the routing lattice anchored at the raster's corner, the turned
    game is not the turned game, so the test above would fail on the defect it guards."""
    init = World.__init__

    def corner_init(self, terrain, features):
        init(self, terrain, features)
        self.cox, self.coy = self.ox, self.oy
        self.cny, self.cnx = math.ceil(self.ny / self.k), math.ceil(self.nx / self.k)

    monkeypatch.setattr(World, "__init__", corner_init)
    d, centre = rotated
    _, a_rows = kit.trace_game(PLAIN, 1)
    _, b_rows = kit.trace_game(d, 1)
    assert turned(a_rows, b_rows, centre) is not None


MARCHES = [
    ((500.0, 3435.0), (4000.0, 3000.0)),  # first line to the crossroads
    ((100.0, 3085.0), (3900.0, 3260.0)),  # the reserve along the high road
    ((2585.8, 4414.2), (5000.0, 1000.0)),  # farm to farm, across both roads
    ((1234.5, 987.5), (6543.25, 5012.75)),
    ((4000.0, 120.0), (3990.0, 5890.0)),  # along the drove road through the village
    ((300.0, 2500.0), (7000.0, 3600.0)),
    ((3000.0, 2000.0), (5000.0, 4000.0)),
]  # a diagonal across the village
PROFILES = ["inf_column", "inf_line", "cav_walk", "art_foot", "courier_road", "train"]


def _lattice_routes_turn(w: World) -> bool:
    """Whether every lattice route of MARCHES, for every profile, has the turned route as its
    image (the A* itself, before the straight-line shortcut can hide a tie)."""
    for prof in PROFILES:
        cost = w._coarse(prof)
        for a, b in MARCHES:
            ra = (2.0 * w.cx - a[0], 2.0 * w.cy - a[1])
            rb = (2.0 * w.cx - b[0], 2.0 * w.cy - b[1])
            m, cells = w._astar(w.coarse_ij(a), w.coarse_ij(b), cost, prof)
            m2, cells2 = w._astar(w.coarse_ij(ra), w.coarse_ij(rb), cost, prof)
            if m2 != m or cells2 != [(w.cny - 1 - i, w.cnx - 1 - j) for i, j in cells]:
                return False
    return True


def test_a_lattice_route_and_its_turned_route(monkeypatch):
    """The A* draws, of equally fast lattice routes, the one whose image the turned query
    draws. Positive control: the old A* (the first route found, ties by node number) does
    not, on these marches."""
    w = World.load(PLAIN)
    assert (w.cx, w.cy) == (4000.0, 3000.0)
    assert w._nodes()[0][w.cny // 2, w.cnx // 2] == 4000.0  # a node on the crossroads
    assert _lattice_routes_turn(w)
    monkeypatch.setattr(World, "_astar", _corner_astar)
    assert not _lattice_routes_turn(World.load(PLAIN))


@pytest.mark.parametrize("profile", PROFILES)
def test_a_route_and_its_turned_route(profile):
    """A body routed from A to B and one routed from the image of A to the image of B take
    each other's image, of the same length, in the same minutes."""
    w = World.load(PLAIN)

    def rot(p):
        return (2.0 * w.cx - p[0], 2.0 * w.cy - p[1])

    for a, b in MARCHES:
        m, pts = w.path_cost(a, b, profile)
        m2, pts2 = w.path_cost(rot(a), rot(b), profile)
        assert math.isfinite(m) and pts
        assert m2 == pytest.approx(m, rel=1e-12, abs=1e-12)
        assert len(pts2) == len(pts)
        for p, q in zip(pts, pts2, strict=True):
            assert q == pytest.approx(rot(p), abs=1e-9)


@pytest.mark.parametrize("profile", PROFILES)
def test_a_route_and_its_mirrored_route_are_as_fast(profile):
    """Plain is symmetric under the left-right mirror too: the mirrored march is as fast (the
    shortest time is a property of the field; which of two mirror-image routes is drawn is a
    tie the rotation-keeping keys break to the left, world._canonical_path)."""
    w = World.load(PLAIN)
    for a, b in MARCHES:
        m, _ = w.path_cost(a, b, profile)
        m2, _ = w.path_cost((a[0], 2.0 * w.cy - a[1]), (b[0], 2.0 * w.cy - b[1]), profile)
        assert m2 == pytest.approx(m, rel=1e-12)


def _march(turn: bool, kind: str) -> list[tuple[int, float, float, float]]:
    """A body marching across Plain to a point beyond the crossroads, alone with a far enemy;
    with `turn`, the same scene turned by 180°. Its (minute, x, y, facing) every minute."""
    w = World.load(PLAIN)

    def at(p):
        return (2.0 * w.cx - p[0], 2.0 * w.cy - p[1]) if turn else p

    u = body(
        "u",
        "blue",
        kind,
        *at((600.0, 1200.0)),
        UnitState.COLUMN,
        facing=(45.0 + (180.0 if turn else 0.0)) % 360.0,
    )
    far = body("far", "red", "line", *at((7900.0, 5900.0)), UnitState.LINE)
    sim = make_sim([u, far], world=w, hq={"blue": at((300.0, 300.0)), "red": at((7700.0, 5700.0))})
    sim.submit_tasks(
        "blue", [Task(TaskKind.ADVANCE, "blue-b-u", Ref(RefKind.POINT, point=at((5200.0, 4100.0))))]
    )
    out = []
    for _ in range(130):
        sim.step()
        out.append((sim.now, u.x, u.y, u.facing_deg))
    return out


@pytest.mark.parametrize("kind", ["line", "hussar"])
def test_a_march_and_its_turned_march_arrive_in_the_same_minute(kind):
    a, b = _march(False, kind), _march(True, kind)
    cx, cy = 4000.0, 3000.0
    assert [(t, 2.0 * cx - x, 2.0 * cy - y, (f + 180.0) % 360.0) for t, x, y, f in a] == b
    arrive = next(t for t, x, y, _ in a if math.hypot(x - 5200.0, y - 4100.0) <= 31.0)
    assert arrive < 130  # it got there, and its image in the same minute
