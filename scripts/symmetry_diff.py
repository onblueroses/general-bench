"""Play a pack and its transform (bot:strong both sides, stub mode) and print the first minute
at which the transformed game is not the transform of the game, with the bodies that differ.
A tool for finding the next asymmetry in the engine; tests/kriegsspiel/test_symmetry.py holds
the checks.

    uv run python scripts/symmetry_diff.py [SEED] [rotate|swap] [PACK]

rotate: the field turned by 180 degrees about its raster's centre (ids and sides kept), so
each body must stand at the image of where it stood. swap: Plain with the colours swapped
(ids R-/B- exchanged), so the body with the swapped id must stand where it stood.
"""

from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "kriegsspiel"))

from symmetry_kit import rotate_pack, swap_id, swapped_pack, trace_game  # noqa: E402 - needs the path above


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    mode = sys.argv[2] if len(sys.argv) > 2 else "rotate"
    pack = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "data" / "plain-crossroads"
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "transformed"
        if mode == "rotate":
            cx, cy = rotate_pack(pack, dst)

            def image(uid, a):
                return uid, 2 * cx - a[0], 2 * cy - a[1], a[2] + 180.0
        else:
            swapped_pack(pack, dst)

            def image(uid, a):
                return swap_id(uid), a[0], a[1], a[2]

        ra, a_rows = trace_game(pack, seed)
        rb, b_rows = trace_game(dst, seed)
    print("game       ", ra.verdict.ordinal)
    print("transformed", rb.verdict.ordinal)
    for (ta, ua), (_tb, ub) in zip(a_rows, b_rows, strict=False):
        bad = []
        for uid, a in ua.items():
            vid, x, y, f = image(uid, a)
            b = ub[vid]
            dpos = math.hypot(b[0] - x, b[1] - y)
            dfac = abs((b[2] - f + 540.0) % 360.0 - 180.0)
            if dpos > 1e-6 or dfac > 1e-6 or a[3:5] != b[3:5] or abs(a[5] - b[5]) > 1e-9:
                bad.append((uid, vid, round(dpos, 4), round(dfac, 4), a, b))
        if bad:
            print("first divergence at tick", ta, "bodies:", len(bad))
            for x in bad[:10]:
                print(" ", x)
            return
    print("the transformed game is the transform of the game over", len(a_rows), "ticks")


if __name__ == "__main__":
    main()
