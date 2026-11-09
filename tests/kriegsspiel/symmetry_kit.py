"""Plain's two symmetry transforms and a traced bot game: the colours swapped (`swapped_pack`),
the field rotated by 180 degrees about the centre of its raster (`rotate_pack`). Used by
test_symmetry.py and scripts/symmetry_diff.py."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np

from kriegsspiel.play import play_game


def swapped_pack(src: Path, dst: Path) -> Path:
    """The pack with the colours swapped: on Plain the western army is now Blue, with the ids
    B-..., which sort first; the eastern army is Red, R-.... The ground, the deployment and
    the order of battle are the same bytes otherwise."""
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("tools"))
    pairs = [
        (r"\bred\b", r"\bblue\b", "red", "blue"),
        (r"\bRed\b", r"\bBlue\b", "Red", "Blue"),
        (r'"R-', r'"B-', '"R-', '"B-'),
        (r'"R"', r'"B"', '"R"', '"B"'),
    ]
    for p in dst.iterdir():
        if p.suffix not in (".json", ".md"):
            continue
        t = p.read_text()
        for a, b, sa, sb in pairs:
            t = re.sub(a, "\x00", t)
            t = re.sub(b, sa, t)
            t = t.replace("\x00", sb)
        p.write_text(t)
    return dst


def swap_id(uid: str) -> str:
    """A body's id in the swapped pack."""
    return {"R": "B", "B": "R"}.get(uid[:1], uid[:1]) + uid[1:]


def rotate_pack(src: Path, dst: Path) -> tuple[float, float]:
    """Copy the pack at `src` to `dst` rotated by 180 degrees about the centre of its raster:
    the terrain arrays reversed on both axes, every feature coordinate, body, headquarters
    and facing turned. Ids, sides, names and texts are kept, so each army now stands where the
    other stood. Returns the centre."""
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("tools"))
    z = dict(np.load(src / "terrain.npz"))
    ox, oy = (float(v) for v in z.get("origin", (0.0, 0.0)))
    cell = float(z["cell_m"])
    ny, nx = z["elev"].shape
    cx, cy = ox + nx * cell / 2.0, oy + ny * cell / 2.0
    for k in ("elev", "cover"):
        z[k] = np.ascontiguousarray(z[k][::-1, ::-1])
    np.savez(dst / "terrain.npz", **z)

    def rot(p):
        return [2.0 * cx - float(p[0]), 2.0 * cy - float(p[1])]

    feats = json.loads((src / "features.json").read_text())
    for f in feats:
        f["geometry"]["coords"] = [rot(p) for p in f["geometry"]["coords"]]
    (dst / "features.json").write_text(json.dumps(feats, indent=1))
    dep = json.loads((src / "deployment.json").read_text())
    for u in dep["units"].values():
        u["x"], u["y"] = rot((u["x"], u["y"]))
        if "facing_deg" in u:
            u["facing_deg"] = (float(u["facing_deg"]) + 180.0) % 360.0
    if "hq" in dep:
        dep["hq"] = {k: rot(v) for k, v in dep["hq"].items()}
    (dst / "deployment.json").write_text(json.dumps(dep, indent=1))
    return cx, cy


def trace_game(scenario: Path, seed: int):
    """A bot:strong self-play game in stub mode and, per minute, every body's
    (x, y, facing, state, men, morale)."""
    rows: list[tuple[int, dict]] = []

    def on_step(sim) -> None:
        rows.append(
            (
                sim.now,
                {
                    u.id: (u.x, u.y, u.facing_deg, u.state.value, u.men, u.morale)
                    for u in sim.forces.units.values()
                },
            )
        )

    res = play_game(
        {"red": "bot:strong", "blue": "bot:strong"},
        mode="stub",
        seed=seed,
        log=None,
        speed=None,
        scenario=scenario,
        out=None,
        on_step=on_step,
    )
    return res, rows
