"""The loader refuses a start position off the map or on ground the body cannot stand on, for
every pack. Without the check a tuning variant of Kolín put four dragoon bodies at y < 0 and
the game ran with them never taking part; only Kolín's own test looked."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
from test_engine_kit import PACKS as TEST_PACKS
from test_engine_kit import ROOT, TESTFIELD

from kriegsspiel.scenario import load
from kriegsspiel.types import Cover

PACKS = sorted(
    p for d in (ROOT / "data", TEST_PACKS) for p in d.iterdir() if (p / "deployment.json").exists()
)


def _pack(tmp_path, **units):
    d = tmp_path / "pack"
    shutil.copytree(TESTFIELD, d, ignore=shutil.ignore_patterns("make.py"))
    dep = json.loads((d / "deployment.json").read_text())
    for uid, upd in units.items():
        dep["units"][uid].update(upd)
    (d / "deployment.json").write_text(json.dumps(dep))
    return d


@pytest.mark.parametrize("pack", PACKS, ids=lambda p: p.name)
def test_every_pack_loads_with_its_bodies_on_passable_ground(pack):
    load(pack)  # the rule itself is the check


def test_the_unmodified_field_loads(tmp_path):
    load(_pack(tmp_path))


@pytest.mark.parametrize("x, y", [(970.0, -40.0), (970.0, 1e6), (-5.0, 450.0)])
def test_a_body_off_the_map_is_refused_by_name(tmp_path, x, y):
    with pytest.raises(ValueError, match=r"B-inf1-2 .*off the map"):
        load(_pack(tmp_path, **{"B-inf1-2": {"x": x, "y": y}}))


def test_a_body_on_water_is_refused_by_name(tmp_path):
    t = np.load(TESTFIELD / "terrain.npz")
    cell = float(t["cell_m"])
    i, j = (int(v[0]) for v in np.nonzero(t["cover"] == Cover.WATER))
    world, *_ = load(_pack(tmp_path))
    x, y = world.ox + (j + 0.5) * cell, world.oy + (i + 0.5) * cell
    assert not world.passable(x, y, "inf")  # the control: this cell is water, unbridged
    with pytest.raises(ValueError, match=r"B-inf1-2 .*impassable"):
        load(_pack(tmp_path / "w", **{"B-inf1-2": {"x": x, "y": y}}))


def test_an_arrival_at_an_entry_off_the_map_is_refused(tmp_path):
    d = _pack(tmp_path, **{"B-inf1-1": {"arrives_at": "13:30", "entry": "Far gate"}})
    feats = json.loads((d / "features.json").read_text())
    feats.append(
        {
            "name": "Far gate",
            "kind": "entry",
            "geometry": {"type": "point", "coords": [[25.0, -300.0]]},
            "aliases": [],
        }
    )
    (d / "features.json").write_text(json.dumps(feats))
    with pytest.raises(ValueError, match=r"B-inf1-1 .*off the map"):
        load(d)
