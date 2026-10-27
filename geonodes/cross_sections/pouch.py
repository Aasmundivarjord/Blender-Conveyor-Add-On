"""Pouch sorter line tree: an overhead rail with trolleys carrying hanging
pouches (pocket sorter: Ferag Skyfall, Dürkopp Adler, Knapp, TGW). The
spine is the rail's TOP edge, so the line object's height is the rail
height; portal frames reach the floor from it. Trolleys hang under the
rail at the pouch pitch and ride with the line (arc + seconds x Speed,
wrapped over whole pitches), each with a hook down to a hanger bar and the
pouch below it. The goods stream (Conveyor - Populate) is spaced to the
pouch pitch and dropped into the pouches by the line's inputs
(model/pouch.py, operators/build_line._push_inputs, operators/stream.py).

The look (2.26.1, "it looks like a low-poly model"): an aluminium I-section
rail with rounded edges; moulded plastic trolleys coupled into a train,
their rubber wheels running on the rail's bottom flange; round hooks; a
moulded rim at each pouch's mouth and a smooth bag that fills out toward
its rounded bottom; portals on bevelled square-tube posts like the
conveyor stands, with knee braces under the beam."""
from __future__ import annotations

import math

import bpy

from ..builder_common import NodeGraph, get_or_create_tree, mark_tree_built
from ..frame import frame_rotation
from ..populate import add_populate_inputs
from . import common

NODE_GROUP_NAME = "Conveyor - Line (Pouch)"
TREE_VERSION = 9  # 2.26.1: the detailed look (I-section rail, plastic trolleys with wheels, smooth pouches, bevelled posts); Transfer k Except (a corner's straight-through goods); 2.25.2: generic stage label (angled-roller decks); 2.24: FIFO buffer inputs (Buffer k Stop ... Rank, Switch Time); 2.22: simple flow route inputs (split edges, transfer rules)

TROLLEY_L, TROLLEY_W, TROLLEY_H = 0.10, 0.075, 0.04  # the trolley under the rail (model/pouch.TROLLEY_H_M: the hook starts below it)
TROLLEY_ROUND = 0.009  # moulded plastic: generously rounded
WHEEL_R, WHEEL_W = 0.011, 0.01  # its four wheels, on the rail's bottom flange either side of the web
FLANGE_T = 0.014  # the rail's top and bottom flanges (an I-section: the trolleys run on the bottom one)
WEB_SHARE = 0.45  # the web's width, a share of the rail's
RAIL_ROUND = 0.005  # the aluminium section's rounded edges
HOOK_R = 0.006  # the round hook
BAR_T = 0.016  # the pouch's moulded hanger bar
RIM_T = 0.008  # the rim around the pouch's mouth
BRACE_L = 0.16  # a portal's knee braces: this far down the post and along the beam


def build(rebuild: bool = False) -> bpy.types.NodeTree:
    tree, needs_build = get_or_create_tree(NODE_GROUP_NAME, TREE_VERSION, rebuild=rebuild)
    if not needs_build:
        return tree
    g = NodeGraph(tree)

    common.declare_frame_inputs(g)
    g.input("Pouch Width", 'NodeSocketFloat', default=0.4, min_value=0.05, subtype='DISTANCE')
    g.input("Pouch Height", 'NodeSocketFloat', default=0.6, min_value=0.05, subtype='DISTANCE')
    g.input("Pouch Depth", 'NodeSocketFloat', default=0.12, min_value=0.01, subtype='DISTANCE')
    g.input("Pouch Pitch", 'NodeSocketFloat', default=0.25, min_value=0.05, subtype='DISTANCE')
    g.input("Hook Length", 'NodeSocketFloat', default=0.1, min_value=0.02, subtype='DISTANCE')
    g.input("Portal Rise", 'NodeSocketFloat', default=0.25, min_value=0.05, subtype='DISTANCE')
    add_populate_inputs(g)
    g.output("Geometry", 'NodeSocketGeometry')

    gi = g.node('NodeGroupInput')
    parts = common.split_spine(g, gi.outputs["Geometry"])

    # The rail: an aluminium I-section on the centreline, its top at the
    # surface (the spine), straight through switches (junction runs are
    # rail runs): top flange, web, and the bottom flange the trolleys run on.
    g.stage("Rail", "the overhead rail: an I-section with rounded edges swept along the centreline, its top at the spine")
    rail_w, rail_h, top = gi.outputs["Rail Thickness"], gi.outputs["Rail Height"], gi.outputs["Rail Top Drop"]

    def band(width, height, centre_drop, radius):
        profile = g.transform(g.filleted_rectangle(width, height, radius), translation=g.combine_xyz(y=g.math('MULTIPLY', centre_drop, -1.0)))
        return g.curve_to_mesh(parts.rail_runs, profile, fill_caps=True)

    web_h = g.math('SUBTRACT', rail_h, 2.0 * FLANGE_T - 0.004)  # into both flanges: no seam
    rail = g.set_material(g.join(band(rail_w, FLANGE_T, g.math('ADD', top, FLANGE_T / 2.0), RAIL_ROUND),
                                 band(g.math('MULTIPLY', rail_w, WEB_SHARE), web_h, g.math('ADD', top, g.math('DIVIDE', rail_h, 2.0)), 0.002),
                                 band(rail_w, FLANGE_T, g.math('SUBTRACT', g.math('ADD', top, rail_h), FLANGE_T / 2.0), RAIL_ROUND)),
                          gi.outputs["Frame Material"])

    portals = _build_portals(g, gi, parts)
    carriers = _build_carriers(g, gi, parts)

    common.finish(g, gi, parts, rail, portals, carriers, surface="pouch")
    g.guide("A pouch sorter line: the spine is the overhead rail on its portal frames; trolleys with hanging pouches ride along it "
            "at the pouch pitch and the goods ride inside the pouches, one each.")
    mark_tree_built(tree, TREE_VERSION)
    return tree


def _build_portals(g: NodeGraph, gi, parts):
    """Goalpost frames every Support Spacing (a stand flush with each end of
    every run, the rest spaced evenly, like the floor stands): two posts
    beside the pouches down to the floor or the mezzanine below, a beam
    over the rail and a hanger from the beam down to the rail top -- the
    rail hangs from above, nothing crosses the pouches' path."""
    g.stage("Portals", "goalpost frames at Support Spacing: posts beside the pouches, a beam over the rail, a hanger down to it")
    size = gi.outputs["Support Size"]
    rise = gi.outputs["Portal Rise"]
    steel = gi.outputs["Frame Material"]
    points = common.support_stations(g, gi, parts.runs)
    # The drop to the floor, frozen on the points (a field is evaluated on
    # the geometry it feeds; see build_legs).
    _, _, point_z = g.separate_xyz(g.position())
    drop_field = g.math('MAXIMUM', g.math('SUBTRACT', point_z, common.floor_below(g, gi)), 0.05)
    store = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='POINT')
    g.link(points, store.inputs["Geometry"])
    store.inputs["Name"].default_value = "portal_drop"
    g.link(drop_field, store.inputs["Value"])
    points = store.outputs["Geometry"]
    drop = g.named_attribute("portal_drop")
    half_span = g.math('ADD', g.math('DIVIDE', gi.outputs["Pouch Width"], 2.0), g.math('ADD', g.math('DIVIDE', size, 2.0), 0.15))
    post_len = g.math('ADD', drop, rise)
    pieces = []
    foot = g.set_material(g.rounded_box(g.math('MULTIPLY', size, 2.4), g.math('MULTIPLY', size, 2.4), 0.012, common.LEG_BEVEL), steel)
    # Knee braces between each post and the beam, at 45 degrees, above the rail (clear of the pouches).
    brace = g.set_material(g.rounded_box(BRACE_L * math.sqrt(2.0), g.math('MULTIPLY', size, 0.6), g.math('MULTIPLY', size, 0.6), common.LEG_BEVEL), steel)
    inner = g.math('SUBTRACT', half_span, g.math('DIVIDE', size, 2.0))  # the posts' inner faces
    under_beam = g.math('SUBTRACT', rise, g.math('DIVIDE', size, 2.0))
    post_points = []
    for sign in (1.0, -1.0):
        lateral = g.rotate_vector(g.combine_xyz(x=g.math('MULTIPLY', half_span, sign)), parts.heading_only)
        lx, ly, _ = g.separate_xyz(lateral)
        # Bevelled square tube from the beam down to the floor, like the conveyor stands' posts.
        post_points.append(g.set_position(points, offset=g.combine_xyz(x=lx, y=ly, z=rise)))
        foot_points = g.set_position(points, offset=g.combine_xyz(x=lx, y=ly, z=g.math('ADD', g.math('MULTIPLY', drop, -1.0), 0.006)))
        pieces.append(g.instance_on_points(foot_points, foot, rotation=parts.heading_only))
        at = g.rotate_vector(g.combine_xyz(x=g.math('MULTIPLY', g.math('SUBTRACT', inner, BRACE_L / 2.0), sign)), parts.heading_only)
        bx, by, _ = g.separate_xyz(at)
        brace_points = g.set_position(points, offset=g.combine_xyz(x=bx, y=by, z=g.math('SUBTRACT', under_beam, BRACE_L / 2.0)))
        tilt = g.rotate_rotation(parts.heading_only, g.euler_to_rotation(g.combine_xyz(y=sign * math.pi / 4.0)))
        pieces.append(g.instance_on_points(brace_points, brace, rotation=tilt))
    pieces.append(common.swept_posts(g, post_points, post_len, size, steel, parts.heading_only))
    beam = g.set_material(g.rounded_box(g.math('ADD', g.math('MULTIPLY', half_span, 2.0), size), size, size, common.LEG_BEVEL), steel)
    pieces.append(g.instance_on_points(g.set_position(points, offset=g.combine_xyz(z=rise)), beam, rotation=parts.heading_only))
    hanger_h = g.math('SUBTRACT', rise, g.math('DIVIDE', size, 2.0))
    hanger = g.set_material(g.rounded_box(g.math('MULTIPLY', size, 0.6), g.math('MULTIPLY', size, 0.6), hanger_h, common.LEG_BEVEL), steel)
    pieces.append(g.instance_on_points(g.set_position(points, offset=g.combine_xyz(z=g.math('DIVIDE', hanger_h, 2.0))), hanger,
                                       rotation=parts.heading_only))
    floor_parts = g.join(*pieces)
    # Hung from the ceiling (user, 2026-10-13: "hang in the roof or stand on
    # the ground"): a short beam over the rail, two drop rods from its ends up
    # to the ceiling -- the first surface above, else the Ceiling level --
    # each with a plate, and the same hanger down to the rail.
    _, _, point_z = g.separate_xyz(g.position())
    up_field = g.math('MAXIMUM', g.math('SUBTRACT', g.math('SUBTRACT', common.ceiling_above(g, gi), point_z), rise), 0.05)
    store_up = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='POINT')
    g.link(points, store_up.inputs["Geometry"])
    store_up.inputs["Name"].default_value = "ceiling_up"
    g.link(up_field, store_up.inputs["Value"])
    cpoints = store_up.outputs["Geometry"]
    up = g.named_attribute("ceiling_up")
    c_half = g.math('ADD', g.math('DIVIDE', size, 2.0), 0.12)
    cbeam = g.set_material(g.rounded_box(g.math('ADD', g.math('MULTIPLY', c_half, 2.0), size), size, size, common.LEG_BEVEL), steel)
    cpieces = [g.instance_on_points(g.set_position(cpoints, offset=g.combine_xyz(z=rise)), cbeam, rotation=parts.heading_only)]
    rod = g.set_material(g.shade_smooth(g.cylinder(12, 0.008, 1.0)), steel)  # a 16 mm threaded rod
    plate = g.set_material(g.rounded_box(0.12, 0.12, 0.012, common.LEG_BEVEL), steel)
    for sign in (1.0, -1.0):
        lateral = g.rotate_vector(g.combine_xyz(x=g.math('MULTIPLY', c_half, sign)), parts.heading_only)
        lx, ly, _ = g.separate_xyz(lateral)
        rod_points = g.set_position(cpoints, offset=g.combine_xyz(x=lx, y=ly, z=g.math('ADD', rise, g.math('DIVIDE', up, 2.0))))
        cpieces.append(g.instance_on_points(rod_points, rod, rotation=parts.heading_only, scale=g.combine_xyz(x=1.0, y=1.0, z=up)))
        plate_points = g.set_position(cpoints, offset=g.combine_xyz(x=lx, y=ly, z=g.math('SUBTRACT', g.math('ADD', rise, up), 0.006)))
        cpieces.append(g.instance_on_points(plate_points, plate, rotation=parts.heading_only))
    cpieces.append(g.instance_on_points(g.set_position(cpoints, offset=g.combine_xyz(z=g.math('DIVIDE', hanger_h, 2.0))), hanger,
                                        rotation=parts.heading_only))
    return g.switch('GEOMETRY', gi.outputs["Ceiling Mount"], floor_parts, g.join(*cpieces))


def _build_carriers(g: NodeGraph, gi, parts):
    """Trolleys under the rail at the pouch pitch, riding with the line:
    index x pitch + seconds x Speed, wrapped over a WHOLE number of pitches
    (the goods stream wraps the same way, so pouch k keeps item k); a
    trolley whose arc lies beyond the run is in the return loop and is not
    drawn. Each carries a hook down to a hanger bar and the pouch below."""
    g.stage("Pouches", "trolleys at the pouch pitch riding with the line, each with a hook, a hanger bar and the pouch hanging below")
    pitch = gi.outputs["Pouch Pitch"]
    speed = gi.outputs["Speed"]
    rail_h = gi.outputs["Rail Height"]
    hook = gi.outputs["Hook Length"]
    pw, ph, pd = gi.outputs["Pouch Width"], gi.outputs["Pouch Height"], gi.outputs["Pouch Depth"]
    steel = gi.outputs["Frame Material"]
    spline_len = g.node('GeometryNodeSplineLength').outputs["Length"]
    n = g.math('MAXIMUM', g.math('CEIL', g.math('DIVIDE', spline_len, pitch)), 1.0)
    wrap = g.math('MULTIPLY', n, pitch)
    resampled = g.resample_count(parts.runs, n)
    index = g.node('GeometryNodeSplineParameter').outputs["Index"]
    raw = g.math('ADD', g.math('MULTIPLY', index, pitch), g.math('MULTIPLY', g.scene_seconds(), speed))
    wrapped = g.math('MODULO', g.math('ADD', g.math('MODULO', raw, wrap), wrap), wrap)
    store_len = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='POINT')
    g.link(resampled, store_len.inputs["Geometry"])
    store_len.inputs["Name"].default_value = "pouch_len"
    g.link(wrapped, store_len.inputs["Value"])
    store_run = g.node('GeometryNodeStoreNamedAttribute', data_type='INT', domain='POINT')
    g.link(store_len.outputs["Geometry"], store_run.inputs["Geometry"])
    store_run.inputs["Name"].default_value = "run_idx"
    g.link(g.node('GeometryNodeCurveOfPoint').outputs["Curve Index"], store_run.inputs["Value"])
    store_total = g.node('GeometryNodeStoreNamedAttribute', data_type='FLOAT', domain='POINT')
    g.link(store_run.outputs["Geometry"], store_total.inputs["Geometry"])
    store_total.inputs["Name"].default_value = "run_len"
    g.link(spline_len, store_total.inputs["Value"])
    points = g.curve_to_points_evaluated(store_total.outputs["Geometry"])
    pouch_len = g.named_attribute("pouch_len")
    run_idx = g.named_attribute("run_idx", 'INT')
    in_loop = g.compare('FLOAT', 'GREATER_THAN', pouch_len, g.named_attribute("run_len"))
    drop = g.node('GeometryNodeDeleteGeometry', domain='POINT')
    g.link(points, drop.inputs["Geometry"])
    g.link(in_loop, drop.inputs["Selection"])
    points = drop.outputs["Geometry"]

    def sample(name):
        node = g.node('GeometryNodeSampleCurve', mode='LENGTH', data_type='FLOAT')
        node.use_all_curves = False
        g.link(parts.runs, node.inputs["Curves"])
        g.link(g.named_attribute(name), node.inputs["Value"])
        g.link(pouch_len, node.inputs["Length"])
        g.link(run_idx, node.inputs["Curve Index"])
        return node

    s_heading = sample("heading")
    s_incline = sample("incline")
    frame = frame_rotation(g, s_heading.outputs["Value"], s_incline.outputs["Value"])  # the trolley follows the rail
    plumb = g.euler_to_rotation(g.combine_xyz(z=s_heading.outputs["Value"]))  # the pouch hangs plumb
    placed = g.set_position(points, position=s_heading.outputs["Position"])
    plastic = gi.outputs["Link Material"]
    pieces = []
    # The trolley, built around the spine point (the rail top) and turned
    # with the rail: a moulded body under the rail, a cheek either side up
    # past the bottom flange, and two rubber wheels a side rolling on it.
    rail_w = gi.outputs["Rail Thickness"]
    rail_bottom = g.math('ADD', gi.outputs["Rail Top Drop"], rail_h)
    body_h = TROLLEY_H - 0.006
    body = g.transform(g.rounded_box(TROLLEY_W, TROLLEY_L, body_h, TROLLEY_ROUND),
                       translation=g.combine_xyz(z=g.math('MULTIPLY', g.math('ADD', rail_bottom, 0.003 + body_h / 2.0), -1.0)))
    wheel_z = g.math('MULTIPLY', g.math('SUBTRACT', rail_bottom, FLANGE_T + WHEEL_R), -1.0)  # resting on the bottom flange
    web_half = g.math('MULTIPLY', rail_w, WEB_SHARE / 2.0)
    wheel_x = g.math('ADD', web_half, 0.002 + WHEEL_W / 2.0)
    cheek_x = g.math('ADD', g.math('DIVIDE', rail_w, 2.0), 0.008)
    cheek_top = g.math('ADD', wheel_z, 0.004)
    cheek_bottom = g.math('MULTIPLY', g.math('ADD', rail_bottom, 0.012), -1.0)
    cheek_h = g.math('SUBTRACT', cheek_top, cheek_bottom)
    stub_len = g.math('SUBTRACT', cheek_x, wheel_x)
    shell, wheels = [body], []
    for sx in (1.0, -1.0):
        shell.append(g.transform(g.rounded_box(0.005, TROLLEY_L * 0.55, cheek_h, 0.002),
                                 translation=g.combine_xyz(x=g.math('MULTIPLY', cheek_x, sx), z=g.math('ADD', cheek_bottom, g.math('DIVIDE', cheek_h, 2.0)))))
        for sy in (1.0, -1.0):
            at = g.combine_xyz(x=g.math('MULTIPLY', wheel_x, sx), y=sy * TROLLEY_L * 0.2, z=wheel_z)
            wheels.append(g.transform(common.spinning_cylinder(g, g.math('ADD', 12.0, 0.0), g.math('ADD', WHEEL_R, 0.0), g.math('ADD', WHEEL_W, 0.0), speed,
                                                               gi.outputs["Belt Material"]), translation=at))
            stub = g.transform(g.shade_smooth(g.cylinder(8, 0.0035, stub_len)), rotation=g.combine_xyz(y=math.pi / 2.0))
            shell.append(g.transform(stub, translation=g.combine_xyz(x=g.math('MULTIPLY', g.math('ADD', wheel_x, g.math('DIVIDE', stub_len, 2.0)), sx),
                                                                      y=sy * TROLLEY_L * 0.2, z=wheel_z)))
    trolley = g.join(g.set_material(g.join(*shell), plastic), *wheels)
    pieces.append(g.instance_on_points(placed, trolley, rotation=frame))
    # The coupling to the next trolley: the trolleys run as one train (none
    # past the last trolley of a run: the next one is in the return loop).
    link_len = g.math('ADD', g.math('SUBTRACT', pitch, TROLLEY_L), 0.03)
    link = g.transform(g.rounded_box(0.02, link_len, 0.012, 0.004),
                       translation=g.combine_xyz(y=g.math('DIVIDE', pitch, 2.0),
                                                 z=g.math('MULTIPLY', g.math('ADD', rail_bottom, 0.003 + body_h / 2.0), -1.0)))
    has_next = g.compare('FLOAT', 'LESS_EQUAL', g.math('ADD', pouch_len, pitch), g.named_attribute("run_len"))
    pieces.append(g.instance_on_points(placed, g.set_material(link, steel), rotation=frame, selection=has_next))
    under = g.math('ADD', rail_h, TROLLEY_H)  # the trolley's underside below the spine
    z_hook = g.math('MULTIPLY', g.math('ADD', under, g.math('DIVIDE', hook, 2.0)), -1.0)
    hook_mesh = g.set_material(g.shade_smooth(g.cylinder(12, HOOK_R, hook)), steel)
    pieces.append(g.instance_on_points(g.set_position(placed, offset=g.combine_xyz(z=z_hook)), hook_mesh, rotation=plumb))
    z_bar = g.math('MULTIPLY', g.math('ADD', under, hook), -1.0)
    bar = g.set_material(g.rounded_box(g.math('ADD', pw, 0.03), BAR_T * 1.4, BAR_T, 0.006), plastic)
    pieces.append(g.instance_on_points(g.set_position(placed, offset=g.combine_xyz(z=z_bar)), bar, rotation=plumb))
    z_pouch = g.math('SUBTRACT', z_bar, g.math('ADD', g.math('DIVIDE', ph, 2.0), BAR_T / 2.0))
    # The pouch: a bag hanging from its bar, open at the top (the goods drop
    # in; user, 2026-10-13), held open by a moulded rim, its sides filling
    # out toward a rounded bottom: a subdivided box, shaded smooth.
    cube = g.node('GeometryNodeMeshCube')
    cube.inputs["Size"].default_value = (1.0, 1.0, 1.0)
    for axis, count in (("X", 7), ("Y", 3), ("Z", 10)):
        cube.inputs[f"Vertices {axis}"].default_value = count
    _nx, _ny, normal_z = g.separate_xyz(g.normal())
    open_top = g.node('GeometryNodeDeleteGeometry', domain='FACE')
    g.link(cube.outputs["Mesh"], open_top.inputs["Geometry"])
    g.link(g.compare('FLOAT', 'GREATER_THAN', normal_z, 0.5), open_top.inputs["Selection"])
    bx, by, bz = g.separate_xyz(g.position())
    up = g.math('ADD', bz, 0.5)  # 0 at the bottom, 1 at the mouth
    fill = g.math('ADD', 0.6, g.math('MULTIPLY', 0.4, g.math('POWER', g.math('SUBTRACT', 1.0, up), 0.5)))  # full at the bottom, 0.6 at the mouth
    bulge = g.math('ADD', 0.82, g.math('MULTIPLY', 0.18, g.math('COSINE', g.math('MULTIPLY', bx, math.pi))))  # the faces belly out mid-width
    corner = g.math('MAXIMUM', g.math('SUBTRACT', 1.0, g.math('DIVIDE', up, 0.18)), 0.0)
    pinch = g.math('SUBTRACT', 1.0, g.math('MULTIPLY', 0.14, g.math('MULTIPLY', corner, corner)))  # the bottom corners round off
    bag = g.set_position(open_top.outputs["Geometry"],
                         position=g.combine_xyz(x=g.math('MULTIPLY', bx, pinch), y=g.math('MULTIPLY', by, g.math('MULTIPLY', fill, bulge)), z=bz))
    pouch = g.set_material(g.shade_smooth(g.transform(bag, scale=g.combine_xyz(x=pw, y=pd, z=ph))), plastic)
    pieces.append(g.instance_on_points(g.set_position(placed, offset=g.combine_xyz(z=z_pouch)), pouch, rotation=plumb))
    mouth = g.node('GeometryNodeFilletCurve')
    g.link(g.rectangle(pw, g.math('MULTIPLY', pd, 0.6)), mouth.inputs["Curve"])
    mouth.inputs["Mode"].default_value = "Poly"
    mouth.inputs["Count"].default_value = 4
    mouth.inputs["Radius"].default_value = 0.015
    mouth.inputs["Limit Radius"].default_value = True
    rim = g.set_material(g.curve_to_mesh(mouth.outputs["Curve"], g.filleted_rectangle(RIM_T, RIM_T, 0.003), fill_caps=False), plastic)
    z_rim = g.math('SUBTRACT', z_bar, BAR_T / 2.0 + RIM_T / 2.0)
    pieces.append(g.instance_on_points(g.set_position(placed, offset=g.combine_xyz(z=z_rim)), rim, rotation=plumb))
    return g.join(*pieces)
