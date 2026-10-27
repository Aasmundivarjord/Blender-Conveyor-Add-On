"""The warehouse around the promo's conveyors: a concrete floor with saw-cut joints, a cut-away diorama
(slab, back wall with windows and wall columns, a low side wall), a forklift, a pallet jack, people in
hi-vis vests and small-parts shelving. Simple bevelled boxes (goods.Parts), so they read in an
orthographic shot without stealing the show. Not shipped. Imported by tools/commercial/shots.py."""
import math
import bpy
from mathutils import Matrix, Vector

import goods as gd

JOINT = 6.0  # m between saw-cut joints


def concrete(name="Concrete floor", base=(0.58, 0.58, 0.57), joint=JOINT, line=0.03):
    """Polished concrete: mottled grey, a little sheen, dark saw-cut joints every `joint` m (object space)."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    tc = nt.nodes.new("ShaderNodeTexCoord")
    xyz = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], xyz.inputs[0])

    def math_node(op, a, b=None):
        m = nt.nodes.new("ShaderNodeMath")
        m.operation = op
        for k, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                m.inputs[k].default_value = v
            else:
                nt.links.new(v, m.inputs[k])
        return m.outputs[0]

    def near_joint(axis):  # 1 within line/2 of a joint across this axis
        d = math_node('ABSOLUTE', math_node('SUBTRACT', math_node('FRACT', math_node('DIVIDE', xyz.outputs[axis], joint)), 0.5))
        return math_node('GREATER_THAN', math_node('MULTIPLY', d, joint), joint / 2.0 - line / 2.0)

    joints = math_node('MAXIMUM', near_joint(0), near_joint(1))
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.35
    noise.inputs["Detail"].default_value = 6.0
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    mottle = nt.nodes.new("ShaderNodeMapRange")
    mottle.inputs["To Min"].default_value = 0.9
    mottle.inputs["To Max"].default_value = 1.06
    nt.links.new(noise.outputs["Fac"], mottle.inputs["Value"])
    tint = nt.nodes.new("ShaderNodeMix")
    tint.data_type = 'RGBA'
    tint.blend_type = 'MULTIPLY'
    tint.inputs["Factor"].default_value = 1.0
    tint.inputs["A"].default_value = (*base, 1.0)
    nt.links.new(mottle.outputs["Result"], tint.inputs["B"])
    cut = nt.nodes.new("ShaderNodeMix")
    cut.data_type = 'RGBA'
    nt.links.new(joints, cut.inputs["Factor"])
    nt.links.new(tint.outputs["Result"], cut.inputs["A"])
    cut.inputs["B"].default_value = (base[0] * 0.55, base[1] * 0.55, base[2] * 0.55, 1.0)
    nt.links.new(cut.outputs["Result"], bsdf.inputs["Base Color"])
    rough = nt.nodes.new("ShaderNodeMapRange")
    rough.inputs["To Min"].default_value = 0.42
    rough.inputs["To Max"].default_value = 0.62
    nt.links.new(noise.outputs["Fac"], rough.inputs["Value"])
    nt.links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])
    return mat


def concrete_floor(floor_obj):
    """The studio floor becomes a concrete warehouse floor."""
    floor_obj.data.materials.clear()
    floor_obj.data.materials.append(concrete())


def _place(o, loc=(0.0, 0.0, 0.0), rot_z_deg=0.0):
    o.location = loc
    o.rotation_euler.z = math.radians(rot_z_deg)
    return o


def diorama(x0, y0, x1, y1, wall_h=5.0, side_h=1.2, thick=0.4):
    """A cut-away building: a concrete slab island, a back wall (north, +Y) of ribbed panels with a window
    band and wall columns, and a low west wall (cut, so it never hides what is inside)."""
    p = gd.Parts()
    slab = concrete()
    panel = gd.material("Wall panel", (0.80, 0.81, 0.83), roughness=0.6, metallic=0.2)
    rib = gd.material("Wall rib", (0.70, 0.71, 0.73), roughness=0.5, metallic=0.3)
    glass = gd.material("Window", (0.32, 0.42, 0.52), roughness=0.08, metallic=0.4)
    steel = gd.material("Column", (0.16, 0.30, 0.52), roughness=0.45, metallic=0.4)
    guard = gd.material("Column guard", (0.95, 0.72, 0.08), roughness=0.5)
    edge = gd.material("Slab edge", (0.45, 0.45, 0.45), roughness=0.8)
    p.box(((x0 + x1) / 2, (y0 + y1) / 2, -thick / 2 + 0.001), (x1 - x0, y1 - y0, thick), edge, bevel=0.02)
    p.box(((x0 + x1) / 2, y1 + 0.15, wall_h / 2), (x1 - x0, 0.3, wall_h), panel, bevel=0.01)  # back wall
    for x in [x0 + 0.5 + k * 1.0 for k in range(int(x1 - x0))]:
        p.box((x, y1 - 0.01, wall_h / 2), (0.06, 0.03, wall_h), rib, bevel=0.0)
    p.box(((x0 + x1) / 2, y1 - 0.02, wall_h - 1.1), (x1 - x0 - 1.0, 0.04, 0.9), glass, bevel=0.01)  # the window band
    for x in [x0 + 0.3 + k * 6.0 for k in range(int((x1 - x0) / 6.0) + 1)]:
        if x > x1 - 0.2:
            break
        p.box((x, y1 - 0.25, wall_h / 2), (0.3, 0.3, wall_h), steel, bevel=0.01)  # wall columns
        p.box((x, y1 - 0.4, 0.5), (0.5, 0.25, 1.0), guard, bevel=0.02)
    p.box((x0 - 0.15, (y0 + y1) / 2, side_h / 2), (0.3, y1 - y0, side_h), panel, bevel=0.01)  # the low west wall
    o = p.build("Warehouse")
    o.location = (0.0, 0.0, 0.0)
    # the slab's top is the floor (z = 0): a plane on it carries the concrete and its joints
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=((x0 + x1) / 2, (y0 + y1) / 2, 0.002))
    top = bpy.context.view_layer.objects.active
    top.name, top.scale = "Warehouse floor", (x1 - x0, y1 - y0, 1.0)
    top.data.materials.append(slab)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return o


def forklift(name, loc, rot_z_deg=0.0, fork_h=0.2, load=None):
    """A counterbalance forklift: body and counterweight, overhead guard, mast, forks, wheels;
    `load` (an object) is set on the forks."""
    p = gd.Parts()
    body = gd.material("Forklift body", (0.95, 0.62, 0.06), roughness=0.45)
    dark = gd.material("Forklift dark", (0.08, 0.08, 0.09), roughness=0.6)
    steel = gd.material("Forklift mast", (0.22, 0.23, 0.25), roughness=0.4, metallic=0.6)
    seat = gd.material("Forklift seat", (0.05, 0.05, 0.05), roughness=0.8)
    p.box((0.0, -0.25, 0.55), (1.05, 1.5, 0.7), body, bevel=0.06)  # chassis, forks at +Y
    p.box((0.0, -0.95, 0.75), (1.1, 0.45, 0.9), body, bevel=0.08)  # counterweight
    p.box((0.0, -0.45, 1.05), (0.5, 0.45, 0.12), seat, bevel=0.03)
    for sx in (-1, 1):
        for y in (0.15, -0.95):
            p.box((sx * 0.38, y, 2.05 / 2 + 0.05), (0.05, 0.05, 2.1), dark, bevel=0.01)  # the overhead guard's posts
    p.box((0.0, -0.4, 2.12), (0.85, 1.25, 0.05), dark, bevel=0.01)
    for sx in (-1, 1):
        p.box((sx * 0.3, 0.62, 1.15), (0.08, 0.1, 2.3), steel, bevel=0.01)  # mast
        p.box((sx * 0.25, 1.25, fork_h), (0.1, 1.15, 0.04), steel, bevel=0.005)  # forks
        for y in (0.35, -0.85):
            p.box((sx * 0.48, y, 0.3), (0.22, 0.6, 0.6), dark, bevel=0.1)  # wheels
    p.box((0.0, 0.7, fork_h + 0.5), (0.8, 0.06, 1.0), steel, bevel=0.01)  # the fork carriage
    o = p.build(name)
    _place(o, loc, rot_z_deg)
    if load is not None:
        m = Matrix.Translation(Vector(loc)) @ Matrix.Rotation(math.radians(rot_z_deg), 4, 'Z')
        c = bpy.data.objects.new(f"{name} load", load.data)
        bpy.context.scene.collection.objects.link(c)
        c.location = m @ Vector((0.0, 1.3, fork_h + 0.02))
        c.rotation_euler.z = math.radians(rot_z_deg + 90.0)
    return o


def pallet_jack(name, loc, rot_z_deg=0.0):
    p = gd.Parts()
    red = gd.material("Jack", (0.75, 0.10, 0.08), roughness=0.5)
    dark = gd.material("Forklift dark", (0.08, 0.08, 0.09), roughness=0.6)
    for sx in (-1, 1):
        p.box((sx * 0.2, 0.55, 0.05), (0.16, 1.15, 0.08), red, bevel=0.01)
    p.box((0.0, -0.1, 0.25), (0.55, 0.2, 0.45), red, bevel=0.03)
    p.box((0.0, -0.45, 0.7), (0.05, 0.05, 1.0), dark, bevel=0.01)
    p.box((0.0, -0.58, 1.18), (0.4, 0.06, 0.06), dark, bevel=0.02)
    return _place(p.build(name), loc, rot_z_deg)


def person(name, loc, rot_z_deg=0.0, vest=(0.85, 0.95, 0.15), shirt=(0.20, 0.24, 0.30)):
    """A stylised figure (1.75 m) in a hi-vis vest, facing +Y."""
    p = gd.Parts()
    trousers = gd.material("Person trousers", (0.12, 0.13, 0.16), roughness=0.8)
    top = gd.material(f"Person shirt {shirt}", shirt, roughness=0.8)
    hv = gd.material("Person vest", vest, roughness=0.6)
    skin = gd.material("Person skin", (0.72, 0.55, 0.42), roughness=0.7)
    for sx in (-1, 1):
        p.box((sx * 0.1, 0.0, 0.42), (0.14, 0.16, 0.84), trousers, bevel=0.05)
        p.box((sx * 0.27, 0.02, 1.12), (0.1, 0.12, 0.62), top, bevel=0.04)  # arms
    p.box((0.0, 0.0, 1.17), (0.42, 0.24, 0.66), hv, bevel=0.08)  # torso in the vest
    p.box((0.0, 0.0, 1.6), (0.21, 0.22, 0.25), skin, bevel=0.09)  # head
    return _place(p.build(name), loc, rot_z_deg)


def shelving(name, loc, rot_z_deg=0.0, bays=2, bin_=None):
    """Small-parts shelving (grey uprights, four shelves) with blue bins (the bin's mesh, linked)."""
    p = gd.Parts()
    grey = gd.material("Shelving", (0.55, 0.57, 0.60), roughness=0.5, metallic=0.4)
    w, d, h = 1.0, 0.6, 2.2
    for i in range(bays + 1):
        for sy in (-1, 1):
            p.box((i * w - bays * w / 2, sy * d / 2, h / 2), (0.04, 0.04, h), grey, bevel=0.005)
    levels = (0.15, 0.7, 1.25, 1.8)
    for z in levels:
        p.box((0.0, 0.0, z), (bays * w, d, 0.03), grey, bevel=0.005)
    o = _place(p.build(name), loc, rot_z_deg)
    if bin_ is not None:
        m = Matrix.Translation(Vector(loc)) @ Matrix.Rotation(math.radians(rot_z_deg), 4, 'Z')
        for z in levels:
            for k in range(bays * 2):
                c = bpy.data.objects.new(f"{name} bin", bin_.data)
                bpy.context.scene.collection.objects.link(c)
                c.location = m @ Vector((-bays * w / 2 + 0.25 + k * 0.5, 0.0, z + 0.015))
                c.rotation_euler.z = math.radians(rot_z_deg + 90.0)
                c.scale = (0.8, 0.8, 0.8)
    return o


def zebra(name, x0, y0, x1, y1, bar=0.4, along_x=False):
    """A pedestrian crossing: white bars across a walkway."""
    p = gd.Parts()
    white = gd.material("Floor marking white", (0.92, 0.92, 0.90), roughness=0.6)
    if along_x:
        x = x0
        while x + bar <= x1:
            p.box((x + bar / 2, (y0 + y1) / 2, 0.004), (bar, y1 - y0, 0.004), white, bevel=0.0)
            x += 2 * bar
    else:
        y = y0
        while y + bar <= y1:
            p.box(((x0 + x1) / 2, y + bar / 2, 0.004), (x1 - x0, bar, 0.004), white, bevel=0.0)
            y += 2 * bar
    o = p.build(name)
    o.location = (0.0, 0.0, 0.0)
    return o
