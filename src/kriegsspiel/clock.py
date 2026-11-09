"""Clock strings ("14:30") and sim minutes."""

from __future__ import annotations


def clock(start: str, minutes: float) -> str:
    """The clock `minutes` (whole minutes counted) after `start`."""
    h, m = (int(v) for v in start.split(":"))
    t = h * 60 + m + int(minutes)
    return f"{(t // 60) % 24:02d}:{t % 60:02d}"


def at_minute(start: str, at: str | float) -> int | float:
    """Minutes after `start` of a clock string ("14:30"), or `at` itself if it is a number."""
    if isinstance(at, int | float):
        return at
    h0, m0 = (int(v) for v in start.split(":"))
    h, m = (int(v) for v in str(at).split(":"))
    return (h * 60 + m) - (h0 * 60 + m0)
