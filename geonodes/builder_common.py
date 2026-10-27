"""Shared helpers for hand-building Geometry Nodes trees via the Python API.

The `NodeGraph` wrapper cuts the nodes.new()/links.new()/interface boilerplate
so the builders read like a description of the graph. Trees are versioned
PER TREE (each builder owns a TREE_VERSION constant) and stamped as built
only after construction succeeded -- both are v1 lessons:
  - a global schema version once forced an unrelated rebuild of the shared
    roller tree, orphaning every modifier's cached inputs (legs and rails
    silently vanished);
  - stamping before the builder ran left a half-built tree marked current
    after a mid-build exception, silently reused all session.

Blender 5.3 API facts this file leans on (re-verify on a new build):
  - several node "modes" (Resample Curve, Set Curve Normal, Transform...)
    are NodeSocketMenu INPUT sockets taking the label string ("Length",
    "Free"), not Python enum properties;
  - a modifier's exposed input values live under
    ``modifier.properties.inputs[socket.identifier]["value"]``.
"""
from __future__ import annotations

import math
from typing import Optional

import bpy

_COLUMN_WIDTH = 260
_ROW_GAP = 40  # between stacked nodes (their height is estimated from the socket count)
_STAGE_GAP = 180  # extra room between stages (frames)
_STAGE_HEIGHT = 2400  # a stage's nodes wrap into a new column inside its frame past this height
_SOCKET_PX = 22
_HEADER_PX = 36

# Stage frames cycle through these muted hues (node editor dark theme).
_STAGE_COLORS = ((0.24, 0.27, 0.33), (0.22, 0.31, 0.29), (0.31, 0.27, 0.22), (0.30, 0.24, 0.31), (0.25, 0.30, 0.24), (0.32, 0.25, 0.25))

LOW_DETAIL_SIDES = 12
HIGH_DETAIL_SIDES = 32

# Every visible edge gets a small rounded bevel so renders catch light on
# it (user request, 2026-09-23). Blender 5.3 has no bevel node and Curves
# objects accept no Bevel modifier, so bevels are BUILT: swept parts use a
# filleted profile (Fillet Curve, Poly, BEVEL_SEGMENTS arcs) and boxes /
# cylinder caps get `bevel_caps`: extrude-and-shrink steps along a quarter
# circle. Radii are per part (see callers); segments are global.
BEVEL_SEGMENTS = 3

_VERSION_KEY = "conveyor_tree_version"


_graphs: dict = {}  # tree pointer -> the NodeGraph building it (for _feed's group-input redirect)


def _feed(socket_input, value) -> None:
    """Feeds a node input either a constant or another socket's output."""
    if isinstance(value, bpy.types.NodeSocket):
        graph = _graphs.get(value.id_data.as_pointer())
        if graph is not None:
            value = graph._redirect(value)
        socket_input.id_data.links.new(value, socket_input)
    elif value is not None:
        socket_input.default_value = value


class NodeGraph:
    """Thin builder wrapper around a single GeometryNodeTree."""

    def __init__(self, tree: bpy.types.NodeTree):
        self.tree = tree
        self._column = 0
        self._x = 0.0
        self._y = 0.0
        self._frame = None
        self._stages: list = []  # (number, title, note)
        self._stage_gi = None  # the current stage's own Group Input node
        self._group_inputs: list = []
        _graphs[tree.as_pointer()] = self

    # -- interface -------------------------------------------------------

    def input(self, name: str, socket_type: str, default=None, min_value: Optional[float] = None,
              max_value: Optional[float] = None, subtype: Optional[str] = None, hide_value: bool = False):
        socket = self.tree.interface.new_socket(name=name, in_out='INPUT', socket_type=socket_type)
        if subtype is not None:
            socket.subtype = subtype
        if default is not None:
            socket.default_value = default
        if min_value is not None:
            socket.min_value = min_value
        if max_value is not None:
            socket.max_value = max_value
        if hide_value:
            socket.hide_value = True
        return socket

    def output(self, name: str, socket_type: str):
        return self.tree.interface.new_socket(name=name, in_out='OUTPUT', socket_type=socket_type)

    # -- node placement ---------------------------------------------------

    def node(self, type_name: str, label: str = "", **props):
        n = self.tree.nodes.new(type_name)
        for key, value in props.items():
            setattr(n, key, value)
        if label:
            n.label = label
        if self._y > _STAGE_HEIGHT:  # wrap inside the stage: a block of columns, not a mile-long strip
            self._x += _COLUMN_WIDTH
            self._y = 0.0
        n.location = (self._x, -self._y)
        # Stack downwards by the node's likely height so sockets never overlap.
        sockets = sum(1 for sock in (*n.inputs, *n.outputs) if sock.enabled and not sock.hide)
        self._y += _HEADER_PX + _SOCKET_PX * max(sockets, 1) + _ROW_GAP
        if self._frame is not None:
            n.parent = self._frame
        return n

    def column(self) -> None:
        self._column += 1
        self._x += _COLUMN_WIDTH
        self._y = 0.0

    # -- stages: the tree reads left to right as numbered, labelled frames --

    def stage(self, title: str, note: str = "") -> None:
        """Starts the next stage of the build: a new column with room before
        it and a labelled frame ("3 · Rails") that every node made until the
        next stage() is parented to. The frames make a tree with hundreds of
        nodes readable as a flow: spine → rails → fences → legs → surface →
        modules → goods → output (user request 2026-10-05)."""
        self.column()
        self._x += _STAGE_GAP
        number = len(self._stages) + 1
        frame = self.tree.nodes.new('NodeFrame')
        frame.label = f"{number} · {title}"
        frame.label_size = 24
        frame.shrink = True
        frame.use_custom_color = True
        frame.color = _STAGE_COLORS[(number - 1) % len(_STAGE_COLORS)]
        frame.name = f"Stage {number}"
        self._frame = frame
        self._stages.append((number, title, note))
        self._stage_gi = self.node('NodeGroupInput', label=f"Inputs · {title}")
        self._group_inputs.append(self._stage_gi)
        self._y = 360.0  # it shows only the handful of sockets this stage reads (guide() hides the rest)

    def guide(self, intro: str) -> None:
        """The last call of a builder: hides the unused sockets of every
        Group Input node (each stage shows only what it reads) and puts a
        frame at the top left holding a Text datablock that walks the
        reader through the stages (what each one makes, in order)."""
        for node in self.tree.nodes:
            if node.type == 'GROUP_INPUT':
                for sock in node.outputs:
                    sock.hide = not sock.is_linked
        name = f"Guide · {self.tree.name}"
        text = bpy.data.texts.get(name)
        if text is None:
            text = bpy.data.texts.new(name)
        text.clear()
        lines = [self.tree.name, "", intro.strip(), "", "Read left to right, one frame per stage:"]
        for number, title, note in self._stages:
            lines.append(f"  {number}. {title}" + (f" — {note}" if note else ""))
        lines += ["", "Inputs come from the line's Geometry Nodes modifier (the plugin pushes them from the panel);",
                  "the spine's attributes (role, heading, incline, module_kind ...) are written by model/spine.py."]
        text.write("\n".join(lines))
        frame = self.tree.nodes.new('NodeFrame')
        frame.label = "How to read this tree"
        frame.label_size = 24
        frame.shrink = False
        frame.use_custom_color = True
        frame.color = (0.18, 0.18, 0.20)
        frame.text = text
        wrapped = sum(max(1, -(-len(line) // 95)) for line in lines)  # the frame wraps at ~95 characters
        frame.width, frame.height = 820, 90 + 21 * wrapped
        frame.location = (0.0, 240.0 + frame.height)

    def link(self, from_socket, to_socket) -> None:
        self.tree.links.new(self._redirect(from_socket), to_socket)

    def _redirect(self, socket):
        """A Group Input output used inside a stage comes from that stage's
        own Group Input node (same socket), so the tree has short local
        links instead of hundreds of noodles from one node on the far left;
        the unused sockets of every Group Input are hidden at the end."""
        if self._stage_gi is None or socket.node.type != 'GROUP_INPUT' or socket.node == self._stage_gi:
            return socket
        return self._stage_gi.outputs[socket.identifier] if socket.identifier in self._stage_gi.outputs else self._stage_gi.outputs[socket.name]

    def group(self, node_tree: bpy.types.NodeTree, **inputs):
        n = self.node('GeometryNodeGroup')
        n.node_tree = node_tree
        for name, value in inputs.items():
            _feed(n.inputs[name.replace("_", " ")], value)
        return n

    # -- small fluent wrappers --------------------------------------------

    def math(self, operation: str, a, b=None, c=None):
        n = self.node('ShaderNodeMath', operation=operation)
        _feed(n.inputs[0], a)
        if b is not None:
            _feed(n.inputs[1], b)
        if c is not None:
            _feed(n.inputs[2], c)
        return n.outputs["Value"]

    def vmath(self, operation: str, a, b=None):
        n = self.node('ShaderNodeVectorMath', operation=operation)
        _feed(n.inputs[0], a)
        if b is not None:
            _feed(n.inputs["Scale"] if operation == 'SCALE' else n.inputs[1], b)
        if operation in ('DOT_PRODUCT', 'LENGTH', 'DISTANCE'):
            return n.outputs["Value"]
        return n.outputs["Vector"]

    def combine_xyz(self, x=0.0, y=0.0, z=0.0):
        n = self.node('ShaderNodeCombineXYZ')
        _feed(n.inputs["X"], x)
        _feed(n.inputs["Y"], y)
        _feed(n.inputs["Z"], z)
        return n.outputs["Vector"]

    def separate_xyz(self, vector):
        n = self.node('ShaderNodeSeparateXYZ')
        _feed(n.inputs["Vector"], vector)
        return n.outputs["X"], n.outputs["Y"], n.outputs["Z"]

    def switch(self, input_type: str, condition, false_value, true_value):
        n = self.node('GeometryNodeSwitch', input_type=input_type)
        _feed(n.inputs["Switch"], condition)
        _feed(n.inputs["False"], false_value)
        _feed(n.inputs["True"], true_value)
        return n.outputs["Output"]

    def compare(self, data_type: str, operation: str, a, b):
        """Compare node. In 5.3 its A/B sockets are dynamically typed (one
        pair that follows data_type), so set data_type BEFORE feeding."""
        n = self.node('FunctionNodeCompare', data_type=data_type, operation=operation)
        _feed(n.inputs["A"], a)
        _feed(n.inputs["B"], b)
        return n.outputs["Result"]

    def boolean(self, operation: str, a, b=None):
        n = self.node('FunctionNodeBooleanMath', operation=operation)
        _feed(n.inputs[0], a)
        if b is not None:
            _feed(n.inputs[1], b)
        return n.outputs["Boolean"]

    def named_attribute(self, name: str, data_type: str = 'FLOAT'):
        n = self.node('GeometryNodeInputNamedAttribute', data_type=data_type)
        n.inputs["Name"].default_value = name
        return n.outputs["Attribute"]

    def euler_to_rotation(self, euler_vector):
        n = self.node('FunctionNodeEulerToRotation')
        _feed(n.inputs["Euler"], euler_vector)
        return n.outputs["Rotation"]

    def rotate_vector(self, vector, rotation):
        n = self.node('FunctionNodeRotateVector')
        _feed(n.inputs["Vector"], vector)
        _feed(n.inputs["Rotation"], rotation)
        return n.outputs["Vector"]

    def rotate_rotation(self, rotation, rotate_by, space: str = 'LOCAL'):
        n = self.node('FunctionNodeRotateRotation')
        if hasattr(n, "rotation_space"):
            n.rotation_space = space
        _feed(n.inputs["Rotation"], rotation)
        _feed(n.inputs["Rotate By"], rotate_by)
        return n.outputs["Rotation"]

    def transform(self, geometry, translation=None, rotation=None, scale=None):
        n = self.node('GeometryNodeTransform')
        _feed(n.inputs["Geometry"], geometry)
        if translation is not None:
            _feed(n.inputs["Translation"], translation)
        if rotation is not None:
            _feed(n.inputs["Rotation"], rotation)
        if scale is not None:
            _feed(n.inputs["Scale"], scale)
        return n.outputs["Geometry"]

    def set_material(self, geometry, material):
        """`material` is a Material datablock or a material socket (line
        trees take theirs from the object's material slots)."""
        n = self.node('GeometryNodeSetMaterial')
        _feed(n.inputs["Geometry"], geometry)
        _feed(n.inputs["Material"], material)
        return n.outputs["Geometry"]

    def shade_smooth(self, geometry):
        """Only for round parts (rollers, pulleys, sprockets) -- flat-faced
        parts shaded smooth blur their edges instead."""
        n = self.node('GeometryNodeSetShadeSmooth')
        _feed(n.inputs["Mesh"], geometry)
        n.inputs["Shade Smooth"].default_value = True
        return n.outputs["Mesh"]

    def join(self, *geometries):
        n = self.node('GeometryNodeJoinGeometry')
        for g in geometries:
            self.link(g, n.inputs["Geometry"])
        return n.outputs["Geometry"]

    def separate_geometry(self, geometry, selection, domain: str = 'CURVE'):
        n = self.node('GeometryNodeSeparateGeometry', domain=domain)
        _feed(n.inputs["Geometry"], geometry)
        _feed(n.inputs["Selection"], selection)
        return n.outputs["Selection"], n.outputs["Inverted"]

    def resample_length(self, curve, length):
        n = self.node('GeometryNodeResampleCurve')
        _feed(n.inputs["Curve"], curve)
        n.inputs["Mode"].default_value = "Length"
        _feed(n.inputs["Length"], length)
        return n.outputs["Curve"]

    def resample_count(self, curve, count):
        n = self.node('GeometryNodeResampleCurve')
        _feed(n.inputs["Curve"], curve)
        n.inputs["Mode"].default_value = "Count"
        _feed(n.inputs["Count"], count)
        return n.outputs["Curve"]

    def curve_to_points_evaluated(self, curve):
        n = self.node('GeometryNodeCurveToPoints', mode='EVALUATED')
        _feed(n.inputs["Curve"], curve)
        return n.outputs["Points"]

    def set_position(self, geometry, position=None, offset=None, selection=None):
        n = self.node('GeometryNodeSetPosition')
        _feed(n.inputs["Geometry"], geometry)
        if selection is not None:
            _feed(n.inputs["Selection"], selection)
        if position is not None:
            _feed(n.inputs["Position"], position)
        if offset is not None:
            _feed(n.inputs["Offset"], offset)
        return n.outputs["Geometry"]

    def instance_on_points(self, points, instance, rotation=None, scale=None, selection=None,
                           pick_instance=False, instance_index=None):
        n = self.node('GeometryNodeInstanceOnPoints')
        _feed(n.inputs["Points"], points)
        _feed(n.inputs["Instance"], instance)
        if selection is not None:
            _feed(n.inputs["Selection"], selection)
        if rotation is not None:
            _feed(n.inputs["Rotation"], rotation)
        if scale is not None:
            _feed(n.inputs["Scale"], scale)
        if pick_instance:
            n.inputs["Pick Instance"].default_value = True
        if instance_index is not None:
            _feed(n.inputs["Instance Index"], instance_index)
        return n.outputs["Instances"]

    def rectangle(self, width, height):
        n = self.node('GeometryNodeCurvePrimitiveQuadrilateral', mode='RECTANGLE')
        _feed(n.inputs["Width"], width)
        _feed(n.inputs["Height"], height)
        return n.outputs["Curve"]

    def filleted_rectangle(self, width, height, radius: float, count: int = BEVEL_SEGMENTS):
        """Rectangle profile with rounded corners: swept through Curve to
        Mesh it gives a tube whose four long edges are beveled. Limit
        Radius keeps thin profiles (guide rails) from folding over."""
        n = self.node('GeometryNodeFilletCurve')
        _feed(n.inputs["Curve"], self.rectangle(width, height))
        n.inputs["Mode"].default_value = "Poly"
        n.inputs["Count"].default_value = count
        n.inputs["Radius"].default_value = radius
        n.inputs["Limit Radius"].default_value = True
        return n.outputs["Curve"]

    def line(self, start, end):
        n = self.node('GeometryNodeCurvePrimitiveLine', mode='POINTS')
        _feed(n.inputs["Start"], start)
        _feed(n.inputs["End"], end)
        return n.outputs["Curve"]

    def normal(self):
        return self.node('GeometryNodeInputNormal').outputs["Normal"]

    def realize(self, geometry):
        n = self.node('GeometryNodeRealizeInstances')
        _feed(n.inputs["Geometry"], geometry)
        return n.outputs["Geometry"]

    def bevel_caps(self, mesh, selection, radius: float, extents, segments: int = BEVEL_SEGMENTS):
        """Rounds the rim of the faces in `selection` (flat end caps) by
        `segments` extrude-and-shrink steps along a quarter circle of
        `radius`. `extents` lists (axis, full_size) pairs the cap is
        shrunk along; a single (None, diameter) entry shrinks uniformly
        (round caps). Sizes may be sockets."""
        prev_sin, prev_cos = 0.0, 1.0
        for k in range(1, segments + 1):
            theta = math.pi / 2.0 * k / segments
            sin_t, cos_t = math.sin(theta), math.cos(theta)
            ext = self.node('GeometryNodeExtrudeMesh', mode='FACES')
            _feed(ext.inputs["Mesh"], mesh)
            _feed(ext.inputs["Selection"], selection)
            ext.inputs["Offset Scale"].default_value = radius * (sin_t - prev_sin)
            ext.inputs["Individual"].default_value = True
            mesh, selection = ext.outputs["Mesh"], ext.outputs["Top"]
            for axis, size in extents:
                # New size / previous size; both shrink by the arc's sagitta.
                new_size = self.math('SUBTRACT', size, 2.0 * radius * (1.0 - cos_t))
                old_size = self.math('SUBTRACT', size, 2.0 * radius * (1.0 - prev_cos))
                factor = self.math('DIVIDE', new_size, old_size)
                sc = self.node('GeometryNodeScaleElements', domain='FACE')
                _feed(sc.inputs["Geometry"], mesh)
                _feed(sc.inputs["Selection"], selection)
                _feed(sc.inputs["Scale"], factor)
                _feed(sc.inputs["Center"], self.position())
                if axis is None:
                    sc.inputs["Scale Mode"].default_value = "Uniform"
                else:
                    sc.inputs["Scale Mode"].default_value = "Single Axis"
                    sc.inputs["Axis"].default_value = axis
                mesh = sc.outputs["Geometry"]
            prev_sin, prev_cos = sin_t, cos_t
        return mesh

    def rounded_box(self, sx, sy, sz, radius: float = 0.003, segments: int = BEVEL_SEGMENTS):
        """Box centered on the origin with all twelve edges rounded: a
        filleted X-Z profile swept along Y (the four long edges), then both
        end caps rounded with bevel_caps. Sizes may be sockets."""
        half = self.math('SUBTRACT', self.math('MULTIPLY', sy, 0.5), radius)
        path = self.line(self.combine_xyz(y=self.math('MULTIPLY', half, -1.0)), self.combine_xyz(y=half))
        oriented = self.node('GeometryNodeSetCurveNormal')
        _feed(oriented.inputs["Curve"], path)
        oriented.inputs["Mode"].default_value = "Free"
        oriented.inputs["Normal"].default_value = (-1.0, 0.0, 0.0)  # profile X -> -X, profile Y -> +Z (probed on 5.3)
        body = self.curve_to_mesh(oriented.outputs["Curve"], self.filleted_rectangle(sx, sz, radius, segments), fill_caps=True)
        _, ny, _ = self.separate_xyz(self.normal())
        caps = self.compare('FLOAT', 'GREATER_THAN', self.math('ABSOLUTE', ny), 0.5)
        return self.bevel_caps(body, caps, radius, [((1.0, 0.0, 0.0), sx), ((0.0, 0.0, 1.0), sz)], segments)

    def cylinder(self, vertices, radius, depth):
        n = self.node('GeometryNodeMeshCylinder')
        _feed(n.inputs["Vertices"], vertices)
        _feed(n.inputs["Radius"], radius)
        _feed(n.inputs["Depth"], depth)
        return n.outputs["Mesh"]

    def cube(self, size):
        n = self.node('GeometryNodeMeshCube')
        _feed(n.inputs["Size"], size)
        return n.outputs["Mesh"]

    def curve_to_mesh(self, curve, profile, fill_caps: bool = True):
        n = self.node('GeometryNodeCurveToMesh')
        _feed(n.inputs["Curve"], curve)
        _feed(n.inputs["Profile Curve"], profile)
        n.inputs["Fill Caps"].default_value = fill_caps
        return n.outputs["Mesh"]

    def scene_seconds(self):
        return self.node('GeometryNodeInputSceneTime').outputs["Seconds"]

    def position(self):
        return self.node('GeometryNodeInputPosition').outputs["Position"]

    def index(self):
        return self.node('GeometryNodeInputIndex').outputs["Index"]


# -- tree lifecycle -------------------------------------------------------


def get_or_create_tree(name: str, version: int, rebuild: bool = False) -> tuple[bpy.types.NodeTree, bool]:
    """Returns (tree, needs_build). Rebuilds when the tree is new, stale
    (its stamped version differs from `version`) or `rebuild` is forced.
    Never stamps -- see mark_tree_built."""
    tree = bpy.data.node_groups.get(name)
    is_new = tree is None
    is_stale = (not is_new) and tree.get(_VERSION_KEY) != version
    needs_build = is_new or rebuild or is_stale

    if needs_build and not rebuild:
        # The shipped copy, when it is exactly this version (geonodes/library.py).
        from . import library

        shipped = library.append_one(name, version)
        if shipped is not None and shipped.get(_VERSION_KEY) == version:
            return shipped, False
        tree = bpy.data.node_groups.get(name)
        is_new = tree is None
    if is_new:
        tree = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    elif needs_build:
        tree.nodes.clear()
        for item in list(tree.interface.items_tree):
            tree.interface.remove(item)
    return tree, needs_build


def tree_is_stale(name: str, version: int) -> bool:
    tree = bpy.data.node_groups.get(name)
    return tree is None or tree.get(_VERSION_KEY) != version


def mark_tree_built(tree: bpy.types.NodeTree, version: int) -> None:
    """The LAST line of every builder. A raise before it leaves the tree
    stale, so the next build() retries instead of trusting a broken tree."""
    tree[_VERSION_KEY] = version


def find_input_socket(tree: bpy.types.NodeTree, name: str):
    for item in tree.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == name:
            return item
    raise KeyError(f"No input socket named {name!r} on {tree.name!r}")


def input_socket_names(tree: bpy.types.NodeTree) -> list[str]:
    return [i.name for i in tree.interface.items_tree if i.item_type == 'SOCKET' and i.in_out == 'INPUT']


def set_modifier_input(modifier: bpy.types.NodesModifier, tree: bpy.types.NodeTree, socket_name: str, value) -> None:
    socket = find_input_socket(tree, socket_name)
    modifier.properties.inputs[socket.identifier]["value"] = value
