"""The published game records, shared by the scripts that read them: `games/<set>/<pack>/<game>
.json.gz`, one gzipped JSON per game (format: `scripts/slim_games.py`)."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAMES = ROOT / "games"
MATRIX = [GAMES / "round-1", GAMES / "round-2"]  # the round robin, the default set
PACKS = {"plain-crossroads": "Plain", "mirror-fords": "Mirror", "arms-medlar": "Arms"}


def records(dirs: list[Path]) -> Iterator[tuple[Path, dict]]:
    """(set directory, record) for every game under `dirs`, each set's games in path order."""
    for d in dirs:
        for f in sorted(d.rglob("*.json.gz")):
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                yield d, json.load(fh)


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"
