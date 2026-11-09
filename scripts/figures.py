"""The README's figures: a battle at one minute as a staff map, and the standings chart.

    uv run --group figures python scripts/figures.py standings docs/figures/standings.png
    uv run --group figures python scripts/figures.py standings docs/figures/standings-dark.png \\
        --dark
    uv run --group figures python scripts/figures.py battle LOG 175 docs/figures/battle.png \\
        --box 2300 5900 1900 4100 --title "Mirror, 11:55" --sub "..."

`standings` reads the matrix records (`games/round-1`, `round-2`). `battle` replays a full run
log (the release download; the slim records in `games/` carry no positions) bit for bit and
draws the field at the given minute of play: relief, woods, brooks, roads and houses from the
pack, every body at its true frontage with its facing, strength and arm, the last fourteen
minutes of movement, and each brigade's order in force as an arrow to its objective.

Fonts: TeX Gyre Pagella and IBM Plex Sans and Mono, if installed; otherwise matplotlib's
defaults stand in.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager, transforms
from matplotlib import patheffects as pe
from matplotlib.patches import Polygon, Rectangle
from matplotlib.path import Path as MPath
from records import MATRIX, ROOT

SERIF, SANS, MONO = "TeX Gyre Pagella", "IBM Plex Sans", "IBM Plex Mono"
FONT_FILES = (
    "/usr/share/texmf-dist/fonts/opentype/public/tex-gyre/texgyrepagella-regular.otf",
    "/usr/share/texmf-dist/fonts/opentype/public/tex-gyre/texgyrepagella-italic.otf",
    "/usr/share/texmf-dist/fonts/opentype/public/tex-gyre/texgyrepagella-bold.otf",
    "/usr/share/fonts/TTF/IBMPlexSans-Regular.ttf",
    "/usr/share/fonts/TTF/IBMPlexMono-Regular.ttf",
)

PAPER, INK, INK2 = "#f3eee2", "#2b2620", "#6b6153"
CONTOUR, SHADOW = "#a8906f", "#7d6f5e"
WOOD, WOOD_EDGE, TREE = "#c9d6b6", "#7f9468", "#6e8a57"
WATER, WATER_INK = "#5f8fb8", "#3d6a92"
ROAD_CASE, ROAD = "#8c8070", "#fbf8ef"
HOUSE, HOUSE_EDGE = "#9a5638", "#5d2f1c"
SIDE = {"red": "#b0362c", "blue": "#2a5a8c"}
SIDE_DARK = {"red": "#5e1712", "blue": "#102b48"}
MODEL_NAMES = {
    "astra": "GPT-6 Astra",
    "sol": "GPT-6 Sol",
    "luna": "GPT-6 Luna",
    "opus": "Claude Opus 5.5",
    "fable": "Claude Fable 5.1",
    "sonnet": "Claude Sonnet 5.5",
    "deepseek": "DeepSeek V4.1 Flash",
}
TIERS = (("astra",), ("fable", "sol", "opus", "luna"), ("deepseek", "sonnet"))

WIDTH_PX, DPI = 2400, 200
TRAIL_MIN = 14  # minutes of movement drawn behind each body
ORDER_MAX_AGE_MIN = 60  # an order older than this is not drawn
ARROW_KINDS = ("advance", "attack", "screen", "support", "withdraw")
DEPTH_M = {  # drawn depth of a body by formation; frontage is the engine's
    "line": 22.0,
    "column": 95.0,
    "square": 60.0,
    "limbered": 40.0,
    "unlimbered": 26.0,
    "skirmish": 16.0,
}


def load_fonts() -> None:
    for f in FONT_FILES:
        if Path(f).exists():
            font_manager.fontManager.addfont(f)


# --- standings --------------------------------------------------------------------------------


def standings_figure(out: Path, dark: bool) -> None:
    """The ratings with their intervals, in tiers, exactly as `standings.py` reports them."""
    from standings import load, standings

    st = standings(load(MATRIX))
    rows = {r["model"]: r for r in st["table"]}
    order = st["order"]

    paper = "#1d1b18" if dark else PAPER
    ink = "#ece6d8" if dark else INK
    ink2 = "#a99f8e" if dark else INK2
    grid = "#3a3631" if dark else "#ddd4c2"
    band = "#26231f" if dark else "#ebe4d4"
    dot = "#e7dfcf" if dark else INK

    fig = plt.figure(figsize=(12, 4.6), dpi=DPI)
    fig.patch.set_facecolor(paper)
    ax = fig.add_axes((0.205, 0.13, 0.62, 0.70))
    ax.set_facecolor(paper)
    lo, hi = 1325, 1700
    ax.set_xlim(lo, hi)
    ax.set_ylim(len(order) - 0.4, -0.6)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(left=False, labelleft=False, bottom=False, labelsize=8.5, colors=ink2)
    ax.set_xticks(range(1350, 1701, 50))
    for lab in ax.get_xticklabels():
        lab.set_family(MONO)
    for x in range(1350, 1701, 50):
        ax.axvline(x, color=grid, lw=0.6, zorder=0.3)
    ax.axvline(1500, color=ink2, lw=0.8, ls=(0, (2, 2)), zorder=0.5)

    def fig_y(i: float) -> float:
        return ax.transData.transform((0, i))[1] / fig.bbox.height

    row = {m: i for i, m in enumerate(order)}
    for k, tier in enumerate(TIERS):
        top = min(row[m] for m in tier) - 0.45
        bottom = max(row[m] for m in tier) + 0.45
        if k % 2 == 0:
            ax.add_patch(
                Rectangle((lo, top), hi - lo, bottom - top, fc=band, ec="none", zorder=0.2)
            )
        fig.text(
            0.985,
            fig_y((top + bottom) / 2),
            ("first", "second", "third")[k] + " tier",
            fontsize=9,
            family=SERIF,
            style="italic",
            color=ink2,
            ha="right",
            va="center",
        )
    for i, m in enumerate(order):
        r = rows[m]
        ax.plot(
            r["rating_ci"], (i, i), color=ink2, lw=2.2, solid_capstyle="round", alpha=0.55, zorder=2
        )
        ax.scatter([r["rating"]], [i], s=58, color=dot, edgecolors=paper, linewidths=1.6, zorder=3)
        ax.text(
            r["rating"],
            i - 0.32,
            f"{r['rating']:.0f}",
            fontsize=7.5,
            family=MONO,
            color=ink2,
            ha="center",
            va="bottom",
        )
        y = fig_y(i)
        fig.text(
            0.19,
            y,
            MODEL_NAMES.get(m, m),
            fontsize=11.5,
            family=SERIF,
            color=ink,
            ha="right",
            va="center",
        )
        fig.text(
            0.835, y, f"{100 * r['share']:.0f}%", fontsize=10, family=MONO, color=ink, va="center"
        )
        fig.text(
            0.875,
            y,
            f"{r['W']}-{r['D']}-{r['L']}",
            fontsize=8.5,
            family=MONO,
            color=ink2,
            va="center",
        )
    fig.text(
        0.205,
        0.93,
        f"Ratings after {st['games']} games",
        fontsize=15,
        family=SERIF,
        color=ink,
        va="center",
    )
    fig.text(
        0.205,
        0.875,
        "Bradley-Terry strength on the Elo scale; bars are 95% intervals from resampling the games",
        fontsize=9,
        family=SERIF,
        style="italic",
        color=ink2,
        va="center",
    )
    fig.text(0.835, 0.845, "share", fontsize=8, family=SANS, color=ink2)
    fig.text(0.875, 0.845, "W-D-L", fontsize=8, family=SANS, color=ink2)
    fig.text(0.515, 0.035, "rating", fontsize=8.5, family=SANS, color=ink2, ha="center")
    fig.savefig(out, dpi=DPI, facecolor=paper)


# --- battle -----------------------------------------------------------------------------------


def capture(log: Path, minute: int) -> tuple[dict, list[dict], dict, str]:
    """Replay `log` and keep each body's state for the trail window up to `minute`: returns
    the bodies' fixed facts, the per-minute states, the orders in the log, and the pack."""
    from kriegsspiel import units
    from kriegsspiel.replay import replay_game

    facts: dict[str, dict] = {}
    states: dict[int, list[tuple]] = {}

    def on_step(sim) -> None:
        t = int(sim.now)
        if t < minute - TRAIL_MIN or t > minute:
            return
        rows = []
        for u in sim.forces.units.values():
            if u.id not in facts:
                f = sim.forces.formations.get(u.parent)
                facts[u.id] = {
                    "side": u.side,
                    "form": u.parent,
                    "form_name": f.name if f else u.parent,
                    "arm": str(u.arm.value),
                    "men0": int(sim.rt[u.id].start_men),
                    "guns": int(u.guns),
                }
            rows.append(
                (
                    u.id,
                    float(u.x),
                    float(u.y),
                    float(u.facing_deg),
                    float(units.frontage(u)),
                    int(u.men),
                    str(u.state.value),
                    bool(u.engaged),
                )
            )
        states[t] = rows

    result = replay_game(log, on_step=on_step)
    if not result.ok:
        sys.exit(
            f"{log}: the replay is not bit-identical ({result.reason}); use the code the "
            "game was played with"
        )
    records = [json.loads(line) for line in log.open()]
    header = records[0]
    orders = [
        {
            "t": r["tick"],
            "side": o["side"],
            "form": task["formation"],
            "kind": task["kind"],
            "objective": task.get("objective"),
        }
        for r in records
        if r.get("type", "tick") == "tick"
        for o in r.get("orders", [])
        for task in o.get("tasks", [])
    ]
    return (
        facts,
        [{"t": t, "b": states[t]} for t in sorted(states)],
        {"orders": orders},
        header["scenario"],
    )


class Sheet:
    """A map sheet over the box (x0, x1, y0, y1) in metres."""

    def __init__(self, box: tuple[float, float, float, float]):
        self.x0, self.x1, self.y0, self.y1 = box
        aspect = (self.y1 - self.y0) / (self.x1 - self.x0)
        self.fig = plt.figure(figsize=(WIDTH_PX / DPI, WIDTH_PX * aspect / DPI), dpi=DPI)
        self.ax = self.fig.add_axes((0, 0, 1, 1))
        self.ax.set_xlim(self.x0, self.x1)
        self.ax.set_ylim(self.y0, self.y1)
        self.ax.set_aspect("equal")
        self.ax.axis("off")
        self.fig.patch.set_facecolor(PAPER)
        self.m_per_px = (self.x1 - self.x0) / WIDTH_PX
        self.halo = [pe.withStroke(linewidth=2.6, foreground=PAPER)]

    def px(self, n: float) -> float:
        """`n` pixels of the output, in metres."""
        return n * self.m_per_px

    def inside(self, x: float, y: float) -> bool:
        return self.x0 < x < self.x1 and self.y0 < y < self.y1

    def label(self, x, y, text, size=8.5, style="normal", color=INK2, weight="normal", rot=0.0):
        if self.inside(x, y):
            self.ax.text(
                x,
                y,
                text,
                fontsize=size,
                family=SERIF,
                style=style,
                color=color,
                weight=weight,
                ha="center",
                va="center",
                rotation=rot,
                path_effects=self.halo,
                zorder=6,
            )


def blur(a: np.ndarray, r: int) -> np.ndarray:
    k = np.exp(-0.5 * (np.arange(-3 * r, 3 * r + 1) / r) ** 2)
    k /= k.sum()
    p = np.pad(a, 3 * r, mode="edge")
    p = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 0, p)
    p = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 1, p)
    return p[3 * r : -3 * r, 3 * r : -3 * r]


def upright(deg: float) -> float:
    """A text angle that never reads upside down."""
    return deg - 180 if deg > 90 else deg + 180 if deg < -90 else deg


def draw_ground(s: Sheet, pack: Path) -> list[dict]:
    z = np.load(pack / "terrain.npz")
    elev, cover = blur(z["elev"].astype(float), 2), z["cover"]
    cell = float(z["cell_m"])
    ox, oy = (float(v) for v in z["origin"])
    h, w = elev.shape
    extent = (ox, ox + cell * w, oy, oy + cell * h)
    xs, ys = ox + cell * (np.arange(w) + 0.5), oy + cell * (np.arange(h) + 0.5)
    features = json.loads((pack / "features.json").read_text())
    ax = s.ax

    # relief: a hillshade lit from the north-west, laid into the paper
    gy, gx = np.gradient(elev * 6.0, cell)  # the fields are gentle: exaggerate the relief
    az, alt = math.radians(315), math.radians(42)
    slope, aspect = np.arctan(np.hypot(gx, gy)), np.arctan2(-gx, gy)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    shade = (shade - shade.min()) / max(1e-9, float(np.ptp(shade)))
    dark = np.clip(0.62 - shade, 0, 1)[..., None] * 0.55
    lit = np.clip(shade - 0.7, 0, 1)[..., None] * 0.35
    paper = np.array(matplotlib.colors.to_rgb(PAPER))
    rgb = paper * (1 - dark) + np.array(matplotlib.colors.to_rgb(SHADOW)) * dark
    rgb = rgb * (1 - lit) + lit
    ax.imshow(rgb, extent=extent, origin="lower", interpolation="bicubic", zorder=0)
    levels = np.arange(math.ceil(float(np.percentile(elev, 30))) + 2.5, elev.max(), 2.5)
    for index, lw, alpha in ((False, 0.3, 0.45), (True, 0.7, 0.7)):
        lv = [v for v in levels if (v % 10 == 0) == index]
        if lv:
            ax.contour(
                xs, ys, elev, levels=lv, colors=CONTOUR, linewidths=lw, alpha=alpha, zorder=1
            )

    rng = np.random.default_rng(7)  # tree and house placement only
    for f in features:
        g = f["geometry"]
        c = np.array(g["coords"])
        if f["kind"] == "wood" and g["type"] == "polygon":
            ax.add_patch(Polygon(c, closed=True, fc=WOOD, ec=WOOD_EDGE, lw=0.9, zorder=2))
            gx_, gy_ = (
                np.arange(c[:, 0].min(), c[:, 0].max(), 38.0),
                np.arange(c[:, 1].min(), c[:, 1].max(), 33.0),
            )
            trees = np.array(
                [
                    (x + rng.uniform(-12, 12) + 17 * (i % 2), y + rng.uniform(-10, 10))
                    for i, y in enumerate(gy_)
                    for x in gx_
                ]
            )
            trees = trees[MPath(c).contains_points(trees)]
            ax.scatter(
                trees[:, 0],
                trees[:, 1],
                s=7,
                facecolors="none",
                edgecolors=TREE,
                linewidths=0.55,
                zorder=2.1,
            )
        elif f["kind"] == "stream":
            ax.plot(c[:, 0], c[:, 1], color=PAPER, lw=4.2, solid_capstyle="round", zorder=3)
            ax.plot(c[:, 0], c[:, 1], color=WATER, lw=2.0, solid_capstyle="round", zorder=3.1)
        elif f["kind"] == "road":
            for color, lw, zo in ((ROAD_CASE, 3.4, 3.2), (ROAD, 2.1, 3.3)):
                ax.plot(
                    c[:, 0],
                    c[:, 1],
                    color=color,
                    lw=lw,
                    solid_capstyle="round",
                    solid_joinstyle="round",
                    zorder=zo,
                )
        elif f["kind"] in ("farm", "mill"):
            ((cx, cy),) = c
            for dx, dy, bw, bh in ((0, 0, 22, 14), (20, -16, 12, 10)):
                ax.add_patch(
                    Rectangle(
                        (cx + dx - bw / 2, cy + dy - bh / 2),
                        bw,
                        bh,
                        fc=HOUSE,
                        ec=HOUSE_EDGE,
                        lw=0.3,
                        zorder=3.5,
                    )
                )
    for r, c in zip(*np.nonzero(cover == 3), strict=True):  # village cells: a few houses each
        if rng.random() < 0.72:
            cx, cy = xs[c], ys[r]
            bw, bh = rng.uniform(9, 15), rng.uniform(7, 11)
            turn = transforms.Affine2D().rotate_deg_around(
                cx, cy, rng.choice([0, 90]) + rng.uniform(-6, 6)
            )
            ax.add_patch(
                Rectangle(
                    (cx - bw / 2, cy - bh / 2),
                    bw,
                    bh,
                    fc=HOUSE,
                    ec=HOUSE_EDGE,
                    lw=0.3,
                    alpha=0.55,
                    zorder=3.5,
                    transform=turn + ax.transData,
                )
            )
    return features


def draw_place_names(s: Sheet, features: list[dict]) -> None:
    for f in features:
        k, n = f["kind"], f["name"]
        c = np.array(f["geometry"]["coords"])
        mid = c[len(c) // 2]
        if k == "village":
            s.label(c[0, 0] - 330, c[0, 1] + 330, n.upper(), size=10.5, color=INK, weight="bold")
        elif k in ("farm", "mill"):
            s.label(c[0, 0], c[0, 1] - 55, n, size=7.6, style="italic")
        elif k == "ford":
            s.label(c[0, 0] + 60, c[0, 1] + 70, n, size=7.6, style="italic", color=WATER_INK)
        elif k == "wood":
            m = c.mean(axis=0)
            s.label(m[0], m[1], n, size=8.2, style="italic", color="#4f6638")
        elif k == "ridge":
            rot = upright(math.degrees(math.atan2(c[-1, 1] - c[0, 1], c[-1, 0] - c[0, 0])))
            s.label(mid[0] + 140, mid[1], n.upper(), size=7.4, color="#7a6248", rot=rot)
        elif k == "stream":
            m = c[int(len(c) * 0.72)]
            s.label(m[0] + 70, m[1], n, size=7.6, style="italic", color=WATER_INK)
        elif k == "road":
            p, q = c[max(0, len(c) // 2 - 1)], c[min(len(c) - 1, len(c) // 2 + 1)]
            rot = upright(math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])))
            s.label(mid[0], mid[1] + 38, n, size=6.6, style="italic", rot=rot)


def body_corners(x: float, y: float, facing: float, width: float, depth: float) -> np.ndarray:
    """Front-left, front-right, rear-right, rear-left of a body facing `facing` (compass)."""
    a = math.radians(facing)
    fwd, right = np.array([math.sin(a), math.cos(a)]), np.array([math.cos(a), -math.sin(a)])
    return np.array(
        [
            (x, y) + right * sx * width / 2 + fwd * sy * depth / 2
            for sx, sy in ((-1, 1), (1, 1), (1, -1), (-1, -1))
        ]
    )


def draw_bodies(s: Sheet, facts: dict, frames: list[dict], minute: int) -> list[tuple]:
    ax = s.ax
    trails: dict[str, list] = {}
    for f in frames:
        for b in f["b"]:
            trails.setdefault(b[0], []).append(b[1:3])
    for uid, pts in trails.items():
        p = np.array(pts)
        if len(p) > 3 and facts[uid]["arm"] != "train" and np.hypot(*(p[-1] - p[0])) > 40:
            ax.plot(
                p[:, 0],
                p[:, 1],
                color=SIDE[facts[uid]["side"]],
                lw=0.8,
                alpha=0.22,
                solid_capstyle="round",
                zorder=4,
            )

    now = next(f["b"] for f in frames if f["t"] == minute)
    for uid, x, y, facing, front, men, state, engaged in now:
        fact = facts[uid]
        if state == "destroyed" or fact["arm"] == "train" or men <= 0:
            continue
        col, edge = SIDE[fact["side"]], SIDE_DARK[fact["side"]]
        strength = max(0.15, men / max(1, fact["men0"]))
        if state == "routed":  # a scatter of strokes, more for more men
            r = np.random.default_rng(sum(map(ord, uid)))
            for _ in range(max(4, int(12 * strength))):
                dx, dy = r.normal(0, 35, 2)
                a = math.radians(r.uniform(0, 180))
                ax.plot(
                    [x + dx - 9 * math.cos(a), x + dx + 9 * math.cos(a)],
                    [y + dy - 9 * math.sin(a), y + dy + 9 * math.sin(a)],
                    color=col,
                    lw=1.1,
                    alpha=0.75,
                    solid_capstyle="round",
                    zorder=5,
                )
            continue
        if fact["arm"] == "artillery":
            width, depth = max(front, s.px(12)), max(18.0, s.px(6))
        else:
            depth = DEPTH_M.get(state, 30.0) * (1.35 if fact["arm"] == "cavalry" else 1.0)
            width, depth = max(front, s.px(14)), max(depth, s.px(7))
        q = body_corners(x, y, facing, width, depth)
        if state == "square":
            ax.add_patch(Polygon(q, closed=True, fc="none", ec=edge, lw=1.6, zorder=5))
            continue
        ax.add_patch(
            Polygon(q, closed=True, fc=col, alpha=0.32 + 0.6 * strength, ec="none", zorder=5)
        )
        if strength < 0.97:  # men lost: a pale band from the rear, up to 60% of the depth
            depth_vec = (q[0] + q[1]) / 2 - (q[3] + q[2]) / 2
            k = min(0.6, 1 - strength)
            band = np.array([q[3], q[2], q[2] + depth_vec * k, q[3] + depth_vec * k])
            ax.add_patch(Polygon(band, closed=True, fc=PAPER, alpha=0.55, ec="none", zorder=5.05))
        ax.add_patch(Polygon(q, closed=True, fc="none", ec=edge, lw=0.45, zorder=5.1))
        ax.plot(
            q[:2, 0],
            q[:2, 1],
            color=edge,
            lw=1.9 if engaged else 1.4,
            solid_capstyle="butt",
            zorder=5.2,
        )  # the front
        if fact["arm"] == "cavalry":
            ax.plot(q[[3, 1], 0], q[[3, 1], 1], color=PAPER, lw=0.9, alpha=0.9, zorder=5.15)
        elif fact["arm"] == "artillery":
            guns = min(8, max(1, fact["guns"]))
            a = math.radians(facing)
            for i in range(guns):
                p = q[0] + (q[1] - q[0]) * (i + 0.5) / guns
                ax.plot(
                    [p[0], p[0] + math.sin(a) * s.px(6)],
                    [p[1], p[1] + math.cos(a) * s.px(6)],
                    color=edge,
                    lw=1.0,
                    zorder=5.2,
                )
            if state == "limbered":
                ax.scatter([x], [y], s=4, color=PAPER, zorder=5.3)
    return now


def draw_orders(
    s: Sheet, facts: dict, now: list[tuple], orders: list[dict], features: list[dict], minute: int
) -> None:
    """Each formation's latest order with a place, if recent: a tapered arrow from the
    formation's formed bodies to the objective, labelled with the brigade and the task."""
    places = {f["name"]: np.array(f["geometry"]["coords"]).mean(axis=0) for f in features}
    latest = {o["form"]: o for o in orders if o["t"] <= minute}
    centre: dict[str, list] = {}
    for uid, x, y, *_, state, _engaged in now:
        if state not in ("destroyed", "routed"):
            centre.setdefault(facts[uid]["form"], []).append((x, y))
    names = {f["form"]: f["form_name"] for f in facts.values()}
    placed: list[np.ndarray] = []
    for form, o in latest.items():
        obj = o["objective"] or {}
        target = obj.get("point") or (
            places.get(obj.get("name")) if obj.get("kind") == "feature" else None
        )
        if (
            o["kind"] not in ARROW_KINDS
            or form not in centre
            or target is None
            or minute - o["t"] > ORDER_MAX_AGE_MIN
        ):
            continue
        a, b = np.array(centre[form]).mean(axis=0), np.array(target, float)
        length = float(np.hypot(*(b - a)))
        if length < 220:
            continue
        u = (b - a) / length
        a2, b2 = a + u * 90, b - u * 40
        bend = np.array([-u[1], u[0]]) * min(160, length * 0.12) * (1 if o["side"] == "red" else -1)
        t = np.linspace(0, 1, 40)[:, None]
        curve = (1 - t) ** 2 * a2 + 2 * (1 - t) * t * ((a2 + b2) / 2 + bend) + t**2 * b2
        tangent = np.gradient(curve, axis=0)
        tangent /= np.linalg.norm(tangent, axis=1)[:, None]
        normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
        width = np.linspace(s.px(3.0), s.px(8.5), len(curve))[:, None]
        head = int(len(curve) * 0.82)
        barb = width[head] * 2.3
        shape = np.vstack(
            [
                curve[:head] + normal[:head] * width[:head],
                curve[head] + normal[head] * barb,
                curve[-1],
                curve[head] - normal[head] * barb,
                (curve[:head] - normal[:head] * width[:head])[::-1],
            ]
        )
        col = SIDE[o["side"]]
        s.ax.add_patch(Polygon(shape, closed=True, fc=col, alpha=0.13, ec="none", zorder=4.5))
        s.ax.add_patch(
            Polygon(shape, closed=True, fc="none", ec=col, alpha=0.75, lw=0.7, zorder=4.55)
        )
        mid = curve[len(curve) // 2]
        clear = all(abs(mid[0] - p[0]) > s.px(150) or abs(mid[1] - p[1]) > s.px(16) for p in placed)
        if clear and s.inside(*mid):
            placed.append(mid)
            s.ax.text(
                mid[0],
                mid[1],
                f"{names.get(form, form)} · {o['kind']}",
                fontsize=6.4,
                family=SANS,
                color=SIDE_DARK[o["side"]],
                ha="center",
                va="center",
                path_effects=s.halo,
                zorder=6,
            )


def draw_furniture(s: Sheet, title: str, sub: str) -> None:
    """Neatline, cartouche, scale bar, north arrow and the legend."""
    ax, px = s.ax, s.px
    w, h = s.x1 - s.x0, s.y1 - s.y0
    for inset, lw in ((14, 1.1), (20, 0.4)):
        ax.add_patch(
            Rectangle(
                (s.x0 + px(inset), s.y0 + px(inset)),
                w - px(2 * inset),
                h - px(2 * inset),
                fc="none",
                ec=INK,
                lw=lw,
                zorder=9,
            )
        )
    if title:
        tx, ty = s.x0 + px(46), s.y1 - px(58)
        ax.text(
            tx,
            ty,
            title,
            fontsize=17,
            family=SERIF,
            color=INK,
            va="center",
            zorder=10,
            path_effects=[pe.withStroke(linewidth=4, foreground=PAPER)],
        )
        ax.text(
            tx,
            ty - px(36),
            sub,
            fontsize=9.5,
            family=SERIF,
            style="italic",
            color=INK2,
            va="center",
            zorder=10,
            path_effects=[pe.withStroke(linewidth=3, foreground=PAPER)],
        )
    sx, sy = s.x1 - px(60) - 1000, s.y0 + px(56)
    for i in range(4):
        ax.add_patch(
            Rectangle(
                (sx + i * 250, sy),
                250,
                px(5),
                fc=INK if i % 2 == 0 else PAPER,
                ec=INK,
                lw=0.6,
                zorder=10,
            )
        )
    for x, text in ((sx, "0"), (sx + 1000, "1 km")):
        ax.text(x, sy + px(16), text, fontsize=7, family=SANS, color=INK, ha="center", zorder=10)
    nx = sx - px(60)
    ax.add_patch(
        Polygon(
            [(nx, sy + px(34)), (nx - px(6), sy), (nx, sy + px(8)), (nx + px(6), sy)],
            closed=True,
            fc=INK,
            ec=INK,
            lw=0.5,
            zorder=10,
        )
    )
    ax.text(nx, sy + px(44), "N", fontsize=8, family=SERIF, color=INK, ha="center", zorder=10)

    lx, ly, lw_, lh = s.x0 + px(40), s.y0 + px(40), px(470), px(150)
    ax.add_patch(Rectangle((lx, ly), lw_, lh, fc=PAPER, ec=INK, lw=0.6, alpha=0.94, zorder=11))

    def block(x, y, side, depth, stripe=False, ticks=0):
        q = body_corners(x, y, 0, px(36), px(depth))
        ax.add_patch(Polygon(q, closed=True, fc=SIDE[side], alpha=0.9, ec="none", zorder=12))
        if ticks:
            for k in range(ticks):
                p = q[0] + (q[1] - q[0]) * (k + 0.5) / ticks
                ax.plot(
                    [p[0], p[0]], [p[1], p[1] + px(6)], color=SIDE_DARK[side], lw=1, zorder=12.1
                )
        else:
            ax.plot(q[:2, 0], q[:2, 1], color=SIDE_DARK[side], lw=1.4, zorder=12.1)
        if stripe:
            ax.plot(q[[3, 1], 0], q[[3, 1], 1], color=PAPER, lw=0.9, zorder=12.1)

    def routed(x, y):
        for dx, dy, deg in ((-12, 2, 20), (-2, -3, 120), (9, 3, 60), (16, -2, 160)):
            a = math.radians(deg)
            ax.plot(
                [x + px(dx) - px(5) * math.cos(a), x + px(dx) + px(5) * math.cos(a)],
                [y + px(dy) - px(5) * math.sin(a), y + px(dy) + px(5) * math.sin(a)],
                color=SIDE["blue"],
                lw=1.1,
                zorder=12,
            )

    def arrow(x, y):
        ax.annotate(
            "",
            xy=(x + px(22), y),
            xytext=(x - px(22), y),
            zorder=12,
            arrowprops={
                "arrowstyle": "simple,head_width=0.6,tail_width=0.25",
                "fc": SIDE["red"] + "30",
                "ec": SIDE["red"],
                "lw": 0.6,
            },
        )

    rows = (
        (lambda x, y: block(x, y, "red", 9), "foot in line; dark edge faces the enemy"),
        (
            lambda x, y: block(x, y, "blue", 11, stripe=True),
            "horse (stripe); pale rear band = men lost",
        ),
        (lambda x, y: block(x, y, "red", 6, ticks=6), "battery (gun ticks)"),
        (routed, "routed"),
        (arrow, "the order in force: brigade · task"),
    )
    for i, (draw, text) in enumerate(rows):
        cy = ly + lh - px(24) - i * px(25)
        draw(lx + px(30), cy)
        ax.text(lx + px(62), cy, text, fontsize=7.2, family=SANS, color=INK, va="center", zorder=12)


def battle_figure(log: Path, minute: int, out: Path, box, title: str, sub: str) -> None:
    facts, frames, logged, scenario = capture(log, minute)
    pack = ROOT / scenario
    s = Sheet(box or (0.0, 8000.0, 0.0, 6000.0))
    features = draw_ground(s, pack)
    draw_place_names(s, features)
    now = draw_bodies(s, facts, frames, minute)
    draw_orders(s, facts, now, logged["orders"], features, minute)
    draw_furniture(s, title, sub)
    s.fig.savefig(out, dpi=DPI, facecolor=PAPER)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="figure", required=True)
    st = sub.add_parser("standings", help="the ratings chart from the matrix records")
    st.add_argument("out", type=Path)
    st.add_argument("--dark", action="store_true")
    bt = sub.add_parser("battle", help="one minute of a game as a staff map")
    bt.add_argument("log", type=Path, help="a full run log (run.jsonl)")
    bt.add_argument("minute", type=int, help="minutes after the start")
    bt.add_argument("out", type=Path)
    bt.add_argument(
        "--box",
        type=float,
        nargs=4,
        metavar=("X0", "X1", "Y0", "Y1"),
        help="the area drawn, in metres (default: the whole field)",
    )
    bt.add_argument("--title", default="")
    bt.add_argument("--sub", default="")
    a = ap.parse_args(argv)
    load_fonts()
    if a.figure == "standings":
        standings_figure(a.out, a.dark)
    else:
        battle_figure(a.log, a.minute, a.out, a.box, a.title, a.sub)
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
