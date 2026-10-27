"""Dev-only helpers for inspecting Geometry Nodes output in a live session.

`Object.to_mesh()` refuses CURVES objects outright ("Object does not have
geometry data") and never realizes instances; `evaluated_geometry()` returns
the evaluated GeometrySet with its mesh, curves, pointcloud and instances
separately, so probes read from that."""
from __future__ import annotations

import bpy
from mathutils import Vector


def evaluated(obj: bpy.types.Object):
    dg = bpy.context.evaluated_depsgraph_get()
    return obj.evaluated_get(dg).evaluated_geometry()


def mesh_bounds(mesh) -> dict:
    if mesh is None or len(mesh.vertices) == 0:
        return {"verts": 0}
    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]
    return {
        "verts": len(mesh.vertices),
        "faces": len(mesh.polygons),
        "x": (round(min(xs), 4), round(max(xs), 4)),
        "y": (round(min(ys), 4), round(max(ys), 4)),
        "z": (round(min(zs), 4), round(max(zs), 4)),
    }


def instance_transforms(obj: bpy.types.Object) -> list[dict]:
    """Per-instance world-space frame probes: where the instance's local
    up/right/forward end up. Use these, never Euler readouts, to check roll."""
    dg = bpy.context.evaluated_depsgraph_get()
    out = []
    for inst in dg.object_instances:
        if not inst.is_instance or inst.parent is None or inst.parent.original != obj:
            continue
        m = inst.matrix_world.to_3x3()
        out.append({
            "pos": tuple(round(c, 4) for c in inst.matrix_world.translation),
            "right": tuple(round(c, 4) for c in (m @ Vector((1, 0, 0))).normalized()),
            "forward": tuple(round(c, 4) for c in (m @ Vector((0, 1, 0))).normalized()),
            "up": tuple(round(c, 4) for c in (m @ Vector((0, 0, 1))).normalized()),
            "name": inst.object.name,
        })
    return out
