"""
Frames and headings (contract v2): Z up, metres, scene unit scale 1.0. A heading is the yaw of
a travel direction about +Z in degrees, 0 = +Y, counter-clockwise positive (+X = -90,
-X = +90, -Y = 180). Systems and lines only translate and yaw, so a pose is (location, yaw).
"""

import math


def heading_deg(dx, dy):
    """Heading of a travel direction in the XY plane."""
    return math.degrees(math.atan2(-dx, dy))


def heading_vector(heading):
    """Unit XY direction of a heading."""
    a = math.radians(heading)
    return -math.sin(a), math.cos(a)


def normalize_heading(heading):
    """The same heading in (-180, 180]."""
    h = (heading + 180.0) % 360.0 - 180.0
    return 180.0 if h == -180.0 else h


def heading_diff_deg(a, b):
    """Smallest absolute difference between two headings."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def rotate_xy(x, y, yaw_deg):
    a = math.radians(yaw_deg)
    c, s = math.cos(a), math.sin(a)
    return x * c - y * s, x * s + y * c


def to_world(point, location, yaw_deg):
    """A local point (x, y) or (x, y, z) at the pose (location, yaw) -> world, same length."""
    rx, ry = rotate_xy(point[0], point[1], yaw_deg)
    out = [location[0] + rx, location[1] + ry]
    if len(point) > 2:
        out.append((location[2] if len(location) > 2 else 0.0) + point[2])
    return tuple(out)


def to_local(point, location, yaw_deg):
    """Inverse of to_world."""
    rx, ry = rotate_xy(point[0] - location[0], point[1] - location[1], -yaw_deg)
    out = [rx, ry]
    if len(point) > 2:
        out.append(point[2] - (location[2] if len(location) > 2 else 0.0))
    return tuple(out)


def polygon_world(poly, location, yaw_deg):
    """A local plan polygon [[x, y], ...] at the pose -> world [(x, y), ...]."""
    return [to_world((p[0], p[1]), location, yaw_deg) for p in poly]


def polygon_local(poly, location, yaw_deg):
    return [to_local((p[0], p[1]), location, yaw_deg) for p in poly]
