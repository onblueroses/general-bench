"""Plane geometry in metres: x east, y north; bearings are compass degrees (0 north, 90 east)."""

from __future__ import annotations

import math
from collections.abc import Sequence

from .types import Feature, GeometryKind

Point = tuple[float, float]

# The lattices that positions and facings stand on, so that a game and its image under the
# 180° rotation of the field play alike. They are powers of two, so a point on the position
# lattice about the field's centre and its image under the rotation are both exactly
# representable, and a facing on the facing lattice turned by 180° is exact. Sim._snap sets
# every body on them each minute; movement within the minute (movement.follow_route) steps
# on them too.
SNAP_M = 2.0**-16  # about 15 micrometres
SNAP_DEG = 2.0**-16  # about 1.5e-5 degrees


def snap_m(v: float) -> float:
    """A length, or an offset from the centre, on the position lattice. Python rounds half to
    even, which commutes with the sign: snap_m(-v) == -snap_m(v) exactly."""
    return round(v / SNAP_M) * SNAP_M


def snap_point(p: Point, centre: Point) -> Point:
    """The point of the position lattice about `centre` nearest p."""
    return (centre[0] + snap_m(p[0] - centre[0]), centre[1] + snap_m(p[1] - centre[1]))


def snap_deg(f: float) -> float:
    """A facing on the facing lattice, in [0, 360)."""
    return (round(f / SNAP_DEG) * SNAP_DEG) % 360.0


def lattice_bearing(dx: float, dy: float) -> float:
    """The compass bearing of the vector (dx, dy) on the facing lattice, such that the reversed
    vector gives exactly the bearing plus 180°: atan2 is taken on the half-plane east of north
    (north itself included) and the other half is turned, so a march and its image under the
    180° rotation wheel by exactly the same angles."""
    flip = dx < 0.0 or (dx == 0.0 and dy < 0.0)
    if flip:
        dx, dy = -dx, -dy
    b = snap_deg(math.degrees(math.atan2(dx, dy)))
    return (b + 180.0) % 360.0 if flip else b


def dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def bearing(a: Point, b: Point) -> float:
    """Compass bearing from a to b in [0, 360), on the facing lattice (`lattice_bearing`): the
    bearing from b to a is exactly this plus 180°, and between two bodies on the position
    lattice it is the same for a pair and for its image under the 180° rotation plus 180°,
    so an arc, flank or rear test at its limit falls the same way in the rotated game."""
    return lattice_bearing(b[0] - a[0], b[1] - a[1])


def angle_diff(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings, in [0, 180]."""
    d = (a - b) % 360.0
    return min(d, 360.0 - d)


def offset(p: Point, bearing_deg: float, d: float) -> Point:
    """The point d metres from p on the bearing. The sine and cosine are taken on the half
    circle [0, 180) and the step turned for the other half, and the step is set on the
    position lattice, so the offset on a bearing plus 180° is exactly the reversed step and a
    point and its image under the 180° rotation step to exact images."""
    b = bearing_deg % 360.0
    flip = b >= 180.0
    if flip:
        b -= 180.0
    r = math.radians(b)
    dx, dy = d * math.sin(r), d * math.cos(r)
    if flip:
        dx, dy = -dx, -dy
    return (p[0] + snap_m(dx), p[1] + snap_m(dy))


def toward(a: Point, b: Point, d: float) -> Point:
    """The point d metres from a toward b (b itself if closer)."""
    total = dist(a, b)
    if total <= d or total == 0.0:
        return b
    f = d / total
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def aspect(target: Point, target_facing: float, source: Point) -> str:
    """Which face of the target the source is on: 'front', 'flank' or 'rear'."""
    d = angle_diff(bearing(target, source), target_facing)
    if d <= 45.0:
        return "front"
    if d <= 135.0:
        return "flank"
    return "rear"


def seg_dist(p: Point, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 == 0.0:
        return dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def polyline_dist(p: Point, pts: Sequence[Point]) -> float:
    if len(pts) == 1:
        return dist(p, pts[0])
    return min(seg_dist(p, pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def polyline_length(pts: Sequence[Point]) -> float:
    return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def nearest_on_polyline(p: Point, pts: Sequence[Point]) -> Point:
    if len(pts) == 1:
        return pts[0]
    best, best_d = pts[0], math.inf
    for i in range(len(pts) - 1):
        (ax, ay), (bx, by) = pts[i], pts[i + 1]
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2))
        q = (ax + t * dx, ay + t * dy)
        d = dist(p, q)
        if d < best_d:
            best, best_d = q, d
    return best


def segments_cross(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Whether segment ab properly crosses segment cd (touching at an end does not count)."""

    def orient(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    return o1 * o2 < 0.0 and o3 * o4 < 0.0


def point_in_polygon(p: Point, ring: Sequence[Point]) -> bool:
    x, y = p
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def polygon_dist(p: Point, ring: Sequence[Point]) -> float:
    """0 inside, distance to the boundary outside."""
    if point_in_polygon(p, ring):
        return 0.0
    closed = [*ring, ring[0]]
    return polyline_dist(p, closed)


def centroid(pts: Sequence[Point]) -> Point:
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)


def ring_centroid(coords: Sequence[Point]) -> Point:
    """The centroid of a polygon's vertices, its closing repeat of the first left out."""
    ring = coords[:-1] if len(coords) > 1 and coords[0] == coords[-1] else coords
    return centroid(ring)


def feature_dist(p: Point, f: Feature) -> float:
    """Distance from p to a feature: to its point, its line, or its area (0 inside)."""
    if f.geometry_kind == GeometryKind.POINT:
        return dist(p, f.coords[0])
    if f.geometry_kind == GeometryKind.POLYLINE:
        return polyline_dist(p, f.coords)
    return polygon_dist(p, f.coords)


POINTS8 = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")


def bearing_word(b: float) -> str:
    """The nearest of the eight compass points to a bearing."""
    return POINTS8[int(((b + 22.5) % 360.0) // 45.0)]


def dist_words(d: float) -> str:
    """A distance as a staff officer gives it: to the 50 m under a kilometre, else in km."""
    if d < 1000.0:
        return f"{max(50, round(d / 50.0) * 50):,.0f} m"
    return f"{d / 1000.0:.1f} km"
