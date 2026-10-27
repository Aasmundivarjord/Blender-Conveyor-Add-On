"""Creates a new conveyor line: a CURVES spine object at the 3D cursor with
one default straight. The object's own location/rotation IS the line's
start pose -- move or rotate the object (G / R) to place the whole line.
X/Y rotation and scale are locked because the frame math assumes the
object only yaws: a tilted object would reintroduce roll."""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from ..config import loader, units
from ..props.line_settings import suspended_rebuild
from .build_line import build_line

LINE_NAME = "Conveyor Line"


def default_width_preset(conveyor_type: str) -> str:
    """The width a new line of that type starts with: ISO 500 when the type
    offers it, else its first catalogue width, else Custom."""
    ctype = loader.get_conveyor_types().get(conveyor_type)
    if ctype is None:
        return 'iso_500'
    widths = loader.get_width_presets()
    ids = [w.id for group in ctype.width_groups for w in widths.get(group, [])]
    return 'iso_500' if 'iso_500' in ids else (ids[0] if ids else 'CUSTOM')


def create_line(context, location, heading_rad: float = 0.0, role: str | None = None, like=None,
                conveyor_type: str | None = None, fill=None) -> bpy.types.Object:
    """`role`: 'MERGE' (goods flow end -> start, into the junction the origin
    sits on) or 'DIVERTER' (a branch leaving it) decides the dock before the
    first build; None lets the pose decide (operators/detect_junctions).
    `like`: another line whose conveyor type and width the new one takes.
    `conveyor_type`: a catalogue type id (a builder's `preset`, contract §6)
    with its default width. `fill(settings)`: puts the pieces in instead of
    one default straight, before the first build (a line along points, R21)."""
    catalog = loader.get_segment_catalog()
    curves = bpy.data.hair_curves.new(LINE_NAME)
    obj = bpy.data.objects.new(LINE_NAME, curves)
    context.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (0.0, 0.0, heading_rad)
    obj.lock_rotation = (True, True, False)
    obj.lock_scale = (True, True, True)

    settings = obj.conveyor_line
    with suspended_rebuild():
        settings.is_conveyor_line = True
        from .flows import BUFFERS_MIGRATED_KEY, MIGRATED_KEY

        settings[MIGRATED_KEY] = True  # a new line starts on the simple-flow sliders (Population 50 %), nothing to migrate
        settings[BUFFERS_MIGRATED_KEY] = True  # and its buffers on Output % (2.24)
        settings.conveyor_type = 'gravity_roller'
        settings.width_preset = 'iso_500'
        if like is not None and like.conveyor_line.is_conveyor_line:
            settings.conveyor_type = like.conveyor_line.conveyor_type
            try:
                settings.width_preset = like.conveyor_line.width_preset
            except TypeError:
                settings.width_preset = 'CUSTOM'
            settings.custom_width_mm = like.conveyor_line.custom_width_mm
        if conveyor_type and conveyor_type in loader.get_line_types():
            settings.conveyor_type = conveyor_type
            try:
                settings.width_preset = default_width_preset(conveyor_type)
            except TypeError:
                settings.width_preset = 'CUSTOM'
        if fill is not None:
            fill(settings)
        else:
            seg = settings.segments.add()
            seg.kind = 'STRAIGHT'
            seg.length_mm = catalog.straight_default_mm
        settings.active_segment_index = 0
        from .build_line import effective_roller_pitch_mm

        settings.roller_pitch_mm = effective_roller_pitch_mm(settings)
        if role is not None:
            from .detect_junctions import ROLE_KEY

            settings.reverse = role == 'MERGE'
            settings[ROLE_KEY] = role
    build_line(context, obj)
    return obj


# A line started from a 3D cursor on the floor (a new scene's cursor sits at the origin) stands at
# a typical bed height instead of lying on the ground with no legs; any other cursor height is kept.
NEW_LINE_BED_HEIGHT_MM = 800.0


def off_the_floor(scene, location: Vector) -> Vector:
    """`location`, raised to the typical bed height above Floor Level when it is on (or below) the floor."""
    floor = float(scene.conveyor_settings.floor_z)
    if location.z <= floor + units.mm_to_bu(50.0, scene):
        location = location.copy()
        location.z = floor + units.mm_to_bu(NEW_LINE_BED_HEIGHT_MM, scene)
    return location


class CONVEYOR_OT_new_line(bpy.types.Operator):
    bl_idname = "conveyor.new_line"
    bl_label = "New Line at 3D Cursor"
    bl_description = ("Create a new conveyor line starting at the 3D cursor, travelling along +Y (a cursor on the floor "
                      "starts it at a typical 0.8 m bed height). With the cursor on another line it starts square off "
                      "that line as a 90° merge: rotate it (R) to change the angle")
    bl_options = {'REGISTER', 'UNDO'}

    # The add operator of the interop contract (§6, v2.1 R11): bpy.ops.conveyor.new_line(kind="line",
    # preset=<conveyor type id>, location=(x, y, z), heading_deg=...) places the line at that pose
    # (0 = +Y, counter-clockwise) and leaves it active. Without a location or heading it starts at the
    # 3D cursor, as from the button. An unknown kind cancels; an unknown preset falls back to the default.
    # R21: points="<JSON list of world [x, y, z]>" (2 or more, metres) lays the line along
    # them -- exactly from the first to the last, a standard curve at every corner, an incline where
    # the height changes (model/route.py) -- and location / heading_deg are ignored. A path it cannot
    # follow cancels with a WARNING and leaves nothing behind. `by` (the caller's add-on id) is
    # recorded on the line (LAYOUT_KEY) for the panel.
    kind: bpy.props.StringProperty(default="line", options={'SKIP_SAVE', 'HIDDEN'})
    preset: bpy.props.StringProperty(default="", options={'SKIP_SAVE', 'HIDDEN'})
    location: bpy.props.FloatVectorProperty(size=3, subtype='TRANSLATION', options={'SKIP_SAVE', 'HIDDEN'})
    heading_deg: bpy.props.FloatProperty(default=0.0, options={'SKIP_SAVE', 'HIDDEN'})
    points: bpy.props.StringProperty(default="", options={'SKIP_SAVE', 'HIDDEN'})
    by: bpy.props.StringProperty(default="", options={'SKIP_SAVE', 'HIDDEN'})

    def invoke(self, context, event):
        """The user's click on New Line at Cursor: the line, then build mode (the plain arrow keys add
        pieces until Enter or Esc, operators/build_mode). Only then: a call that passes a pose, points, a
        kind, a preset or a caller id -- another add-on's, R6 / R21 -- runs exactly as an EXEC does."""
        result = self.execute(context)
        scripted = any(self.properties.is_property_set(p) for p in ("kind", "preset", "location", "heading_deg", "points", "by"))
        return result if scripted else then_build(context, result)

    def execute(self, context):
        from .detect_junctions import attach_heading_at
        from .ports import _reach, port_at

        if self.kind and self.kind != "line":
            self.report({'WARNING'}, f"Unknown kind '{self.kind}': this add-on makes 'line'")
            return {'CANCELLED'}
        preset = self.preset
        if preset and preset not in loader.get_line_types():
            self.report({'WARNING'}, f"Unknown preset '{preset}': using the default conveyor type")
            preset = ""
        if self.points.strip():
            return self._along_points(context, preset)
        if self.properties.is_property_set("location") or self.properties.is_property_set("heading_deg"):
            obj = create_line(context, Vector(self.location), math.radians(self.heading_deg), conveyor_type=preset or None)
            _activate(context, obj)
            return {'FINISHED'}
        location = context.scene.cursor.location.copy()
        role = None
        port = port_at(context.scene, location, _reach(context))
        if port is not None:
            # The cursor on a rack's port (Racks' "Cursor to Port"): the line
            # starts on it -- forward out of an "out" port, reversed (ending
            # there) at an "in" port -- and docks on its first build.
            _system, p, pos, heading, _handover = port
            location = Vector((pos.x, pos.y, location.z if p.get("z_free") else pos.z))  # R16: a z_free port keeps the cursor's height
            role = 'MERGE' if p.get("role") == "in" else None
            heading = heading + (math.pi if role == 'MERGE' else 0.0)
        else:
            heading = attach_heading_at(context, location)
            if heading is None:
                location = off_the_floor(context.scene, location)
        obj = create_line(context, location, heading if heading is not None else 0.0, role=role, conveyor_type=preset or None)
        _activate(context, obj)
        return {'FINISHED'}


    def _along_points(self, context, preset: str):
        """R21: plan first (nothing is created when the path cannot be followed), then one build."""
        import json

        from ..model import route as route_model
        from ..model.public_api import LAYOUT_KEY
        from ..props.line_settings import EXACT_ANGLE_KEY
        from .._wh import records as wh_records

        try:
            raw = json.loads(self.points)
            points = [(float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0) for p in raw]
        except (TypeError, ValueError, IndexError, KeyError):
            self.report({'WARNING'}, "points must be a JSON list of world [x, y, z] in metres")
            return {'CANCELLED'}
        scene = context.scene
        type_id = preset or 'gravity_roller'
        ctype = loader.get_conveyor_types().get(type_id)
        try:
            route = route_model.plan_route(points, _new_width_m(type_id, scene), _corner_radii(scene),
                                           _new_nose_radius_m(type_id, scene), loader.incline_limit_deg(type_id),
                                           ctype.label if ctype is not None else "This conveyor")
        except route_model.RouteError as e:
            self.report({'WARNING'}, str(e))
            return {'CANCELLED'}

        def fill(settings):
            for piece in route.pieces:
                seg = settings.segments.add()
                if piece.kind == "CURVE":
                    seg.kind = 'CURVE'
                    seg.curve_angle_deg = max(1, int(round(piece.angle_deg)))
                    if abs(piece.angle_deg - round(piece.angle_deg)) > 1e-6:
                        seg[EXACT_ANGLE_KEY] = float(piece.angle_deg)
                    seg.curve_direction = piece.direction
                    seg.curve_radius = piece.radius_id
                else:
                    seg.kind = 'STRAIGHT'
                    seg["length_mm"] = units.bu_to_mm(piece.length_m, scene)  # exact: the 150 mm snap is for hand edits
                    seg["rise_mm"] = units.bu_to_mm(piece.rise_m, scene)

        obj = create_line(context, Vector(route.start), route.heading, conveyor_type=preset or None, fill=fill)
        wh_records.write_record(obj, LAYOUT_KEY, {"version": 2, "by": str(self.by or "").strip() or "unknown", "points": len(points)})
        _activate(context, obj)
        return {'FINISHED'}


def _new_width_m(type_id: str, scene) -> float:
    """The width a new line of that type starts with (create_line's defaults)."""
    from .build_line import resolve_width_mm

    class _Defaults:  # the settings create_line gives a new line, read the same way
        conveyor_type = type_id
        width_preset = default_width_preset(type_id)
        custom_width_mm = 500.0
        pouch_size = ""
        pouch_width_mm, pouch_height_mm, pouch_depth_mm = 400.0, 600.0, 120.0

    from ..props.line_settings import CONVEYOR_LineSettings

    props = CONVEYOR_LineSettings.bl_rna.properties
    _Defaults.pouch_size = props["pouch_size"].default
    _Defaults.custom_width_mm = props["custom_width_mm"].default
    _Defaults.pouch_width_mm = props["pouch_width_mm"].default
    _Defaults.pouch_height_mm = props["pouch_height_mm"].default
    _Defaults.pouch_depth_mm = props["pouch_depth_mm"].default
    return units.mm_to_bu(resolve_width_mm(_Defaults), scene)


def _corner_radii(scene) -> list:
    """The catalogue's default inside radius first, then the smaller ones of its system."""
    catalog = loader.get_segment_catalog()
    default = catalog.curve_radius_by_id(catalog.curve_default_radius_id)
    smaller = sorted((r for r in catalog.curve_radii if r.system == default.system and r.radius_mm < default.radius_mm),
                     key=lambda r: -r.radius_mm)
    return [(r.id, units.mm_to_bu(r.radius_mm, scene)) for r in [default] + smaller]


def _new_nose_radius_m(type_id: str, scene) -> float:
    """The nose-over radius a new line builds with (Nose-over is on by default)."""
    from ..props.line_settings import CONVEYOR_LineSettings

    if not CONVEYOR_LineSettings.bl_rna.properties["nose_over"].default:
        return 0.0
    ctype = loader.get_conveyor_types().get(type_id)
    cross = ctype.cross_section if ctype is not None else "roller"
    return units.mm_to_bu(loader.get_segment_catalog().nose_over_radius_for(cross), scene)


def _activate(context, obj) -> None:
    for o in list(context.view_layer.objects.selected):  # (context.selected_objects needs a screen: not from scripts / timers)
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def then_build(context, result):
    """After the user's click made a line (New Line at Cursor, from End, at a Junction): build mode on it, the
    plain arrow keys extend it (operators/build_mode). Only from the 3D view -- the panel, a gizmo -- never
    from a script, which calls EXEC and never gets here."""
    if 'FINISHED' in result and context.window is not None and context.area is not None and context.area.type == 'VIEW_3D':
        bpy.ops.conveyor.build_mode('INVOKE_DEFAULT')
    return result


class CONVEYOR_OT_new_line_from_end(bpy.types.Operator):
    bl_idname = "conveyor.new_line_from_end"
    bl_label = "New Line from End"
    bl_description = ("Start a new, separate line exactly where the active line ends (e.g. after a right-angle transfer), "
                      "of the same type and width")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj) and obj.type == 'CURVES' and obj.conveyor_line.is_conveyor_line

    def invoke(self, context, event):
        return then_build(context, self.execute(context))

    def execute(self, context):
        import math

        from mathutils import Vector

        src = context.active_object
        ex, ey, ez, heading_deg = src.conveyor_line.end_pose
        world = src.matrix_world @ Vector((ex, ey, ez))
        heading = src.rotation_euler.z + math.radians(heading_deg)
        # The takeaway keeps the line's type and width (an 800 RAT got a 500 mm takeaway).
        obj = create_line(context, world, heading, like=src)
        for o in list(context.view_layer.objects.selected):
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


class CONVEYOR_OT_new_line_at_junction(bpy.types.Operator):
    """The + outside a free junction face (ui/segment_edit.py): another
    conveyor docked on that face right away -- a feeder into a merge, a
    branch out of a diverter -- leaving at the junction's angle with one
    default straight to extend with the keys."""
    bl_idname = "conveyor.new_line_at_junction"
    bl_label = "New Line at Junction"
    bl_description = ("Start another conveyor on this junction's free face: a feeder into a merge, a branch out of a diverter, "
                      "a branch off a right-angle transfer's side (Goods in turns it into a feeder). A one-sided junction becomes two-sided")
    bl_options = {'REGISTER', 'UNDO'}

    line_name: bpy.props.StringProperty(options={'SKIP_SAVE'})
    index: bpy.props.IntProperty(default=-1, options={'SKIP_SAVE'})
    side: bpy.props.EnumProperty(items=[('LEFT', "Left", ""), ('RIGHT', "Right", ""),
                                        ('START', "Start", "A feeder the transfer carries on from"), ('END', "End", "The far face")],
                                 default='LEFT', options={'SKIP_SAVE'})

    def invoke(self, context, event):
        return then_build(context, self.execute(context))

    def execute(self, context):
        from .detect_junctions import open_junction_face, origin_dock, sync_feeder

        target = context.scene.objects.get(self.line_name)
        if target is None or target.type != 'CURVES' or not target.conveyor_line.is_conveyor_line:
            return {'CANCELLED'}
        segs = target.conveyor_line.segments
        if not (0 <= self.index < len(segs)) or segs[self.index].kind != 'MODULE' or segs[self.index].module_kind not in ('MERGE', 'DIVERTER', 'RAT'):
            self.report({'WARNING'}, "That piece is not a junction any more")
            return {'CANCELLED'}
        seg = segs[self.index]
        if seg.module_kind == 'RAT' and (self.side == 'START' or (self.side == 'END' and seg.module_exit == 'STRAIGHT')):
            # The start / end of a straight transfer: a SEPARATE line of its
            # type and width -- a feeder ending at its start (the RAT carries
            # the goods on) or the takeaway from its end.
            obj = _line_at_rat_end(context, target, self.side)
            for o in list(context.view_layer.objects.selected):
                o.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
            self.report({'INFO'}, f"{obj.name} {'feeds' if self.side == 'START' else 'carries on from'} {target.name}; extend it with the keys")
            return {'FINISHED'}
        kind = 'DIVERTER' if seg.module_kind == 'RAT' else seg.module_kind
        is_merge = kind == 'MERGE'
        centre, heading = open_junction_face(context, target, self.index, self.side, role=kind)
        # A RAT face starts a line like the RAT's own (type, width): the face is that width until another line docks.
        obj = create_line(context, centre, heading, role=kind, like=target if segs[self.index].module_kind == 'RAT' else None)
        if origin_dock(context, obj) is None:
            sync_feeder(context, obj)
        for o in list(context.view_layer.objects.selected):
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        self.report({'INFO'}, f"{obj.name} {'feeds into' if is_merge else 'branches off'} {target.name}; extend it with the keys")
        return {'FINISHED'}


def _line_at_rat_end(context, target, side: str) -> bpy.types.Object:
    """A separate line of `target`'s type and width at its start (ending
    exactly on the origin, so the transfer adopts it: detect_junctions.adopt_tails)
    or starting at its end (the takeaway, a tail continuation)."""
    catalog = loader.get_segment_catalog()
    if side == 'END':
        ex, ey, ez, heading_deg = target.conveyor_line.end_pose
        world = target.matrix_world @ Vector((ex, ey, ez))
        return create_line(context, world, target.rotation_euler.z + math.radians(heading_deg), like=target)
    heading = target.rotation_euler.z
    length = units.mm_to_bu(catalog.straight_default_mm, context.scene)
    origin = target.matrix_world.translation.copy()
    fwd = Vector((-math.sin(heading), math.cos(heading), 0.0))
    return create_line(context, origin - fwd * length, heading, like=target)


classes = (CONVEYOR_OT_new_line, CONVEYOR_OT_new_line_from_end, CONVEYOR_OT_new_line_at_junction)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
