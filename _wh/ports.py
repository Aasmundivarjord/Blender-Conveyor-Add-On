"""
Ports in world space and a system snapping onto a conveyor end (contract R20). Lifted from the
Racks add-on 0.23.0 (interop.py) so Racks, Shuttle lifts and Floorplan dock rows snap the same
way: the mirror of a conveyor line docking at a port (same tolerances as the Conveyor's capture).
"""

import math

from .frames import heading_diff_deg, rotate_xy
from .levels import level_at

SNAP_PLAN_TOL_M = 0.60          # the Conveyor's capture radius
SNAP_Z_TOL_M = 0.25
SNAP_HEADING_TOL_DEG = 20.0
LINE_END_PARTNER = {"in": "line_out", "out": "line_in"}   # a system port's role -> the line end it joins


def port_point(port):
    """A port's representative local point: a point port's position, a face port's midpoint."""
    if port.get("kind") == "face":
        (x0, y0, z0), (x1, y1, z1) = port["face"]
        return ((x0 + x1) * 0.5, (y0 + y1) * 0.5, (z0 + z1) * 0.5)
    return tuple(port["position"])


def port_world(port, location, yaw_deg):
    """((x, y, z), heading deg) of a system's local port at the system pose (location, yaw)."""
    px, py, pz = port_point(port)
    rx, ry = rotate_xy(px, py, yaw_deg)
    return (location[0] + rx, location[1] + ry, location[2] + pz), float(port.get("heading_deg", 0.0)) + yaw_deg


def with_levels(ports, location, yaw_deg, levels):
    """R10: a copy of `ports` where every port carries the level of its own point (an incline's
    two ends may sit on different floors). `levels` in world coordinates (levels.levels_world)."""
    out = []
    for port in ports:
        pos, _h = port_world(port, location, yaw_deg)
        p = dict(port)
        p["level"] = level_at(pos, levels)
        out.append(p)
    return out


def snap_pose(system_port, line_pos, line_heading_deg, keep_z):
    """Where a system goes so that `system_port` (local) sits ON a line end at `line_pos` (world)
    with the goods' heading continuous; its z stays `keep_z`. Returns ((x, y, z), yaw deg)."""
    yaw = float(line_heading_deg) - float(system_port.get("heading_deg", 0.0))
    px, py, _pz = port_point(system_port)
    rx, ry = rotate_xy(px, py, yaw)
    yaw = (yaw + 180.0) % 360.0 - 180.0
    return (line_pos[0] - rx, line_pos[1] - ry, keep_z), yaw


def snap_candidates(system_ports_world, line_ends):
    """Best (system port id, line end) pair to snap, or None. `system_ports_world` =
    [(port, (x, y, z), heading deg)] of the system's free point ports at its current pose;
    `line_ends` = [{"id": "line_in" | "line_out", "position": world (x, y, z), "heading_deg":
    world heading, "taken": bool, ...}]. Roles pair in <-> line_out and out <-> line_in (io
    either way), within the snap tolerances; nearest wins."""
    best = None
    for port, pos, heading in system_ports_world:
        role = port.get("role")
        wanted = {LINE_END_PARTNER[role]} if role in LINE_END_PARTNER else set(LINE_END_PARTNER.values())
        for end in line_ends:
            if end.get("taken") or end.get("id") not in wanted:
                continue
            ex, ey, ez = end["position"]
            plan = math.hypot(ex - pos[0], ey - pos[1])
            if plan > SNAP_PLAN_TOL_M or abs(ez - pos[2]) > SNAP_Z_TOL_M:
                continue
            h = heading if role != "io" or end["id"] == "line_in" else \
                port.get("heading_in_deg", heading + 180.0) - port.get("heading_deg", 0.0) + heading
            turn = heading_diff_deg(h, float(end["heading_deg"]))
            if turn > SNAP_HEADING_TOL_DEG:
                continue
            score = plan + turn / 100.0
            if best is None or score < best[0]:
                best = (score, port["id"], end)
    return (best[1], best[2]) if best else None
