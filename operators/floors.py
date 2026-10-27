"""Where the legs land. Legs and columns cast a ray down and stand on the
first surface below them (geonodes/cross_sections/common.floor_below), taken
from one collection (interop contract v2.1 R3, amended by R3.1 on 2026-10-14):

1. the Floors collection the user names in the Scene panel overrides
   everything;
2. else every object whose `wh_floor` is true -- always a floor (Floorplan's
   slabs and mezzanine decks, Racks' walkway decks, the user's own marked
   meshes) -- together with the automatic candidates: every mesh with faces
   of its own, except the lines' items and placeholders, anything carrying
   another add-on's record (`wh_system`, `wh_ports`, `wh_load`,
   `wh_obstacles`), anything in the `Warehouse Loads` collection, and
   anything whose `wh_floor` is false (never a floor: a table, a machine top);
3. with the Scene panel's "Marked only" on (default off), only the objects
   whose `wh_floor` is true. Before R3.1 one mark anywhere switched the whole
   scene to this; now it is the user's explicit choice.

Cases 2 and 3 live in an unlinked helper collection whose membership the
depsgraph handler keeps in sync, so a plane dropped under a raised line
catches its legs without any setup. Mark as floor (Floor / Not a floor /
Auto) writes `wh_floor` only on the user's own meshes, stamped with our own
key next to it so only those can be changed back here; a mark another add-on
made is shown, never touched."""
from __future__ import annotations

import bpy

AUTO_FLOORS_NAME = "Conveyor Floors (auto)"
FLOOR_KEY = "wh_floor"  # the shared marker (contract v2.1 R3 / R3.1): true = always a floor, false = never one
MARK_KEY = "conveyor_floor_mark"  # our stamp beside a wh_floor we wrote: only these the Unmark button clears
LOADS_COLLECTION = "Warehouse Loads"
FOREIGN_KEYS = ("wh_system", "wh_ports", "wh_load", "wh_obstacles")


def floor_mark(obj):
    """True (always a floor), False (never one) or None (unmarked: the automatic rule)."""
    try:
        if FLOOR_KEY not in obj:
            return None
        return bool(obj[FLOOR_KEY])
    except Exception:
        return None


def is_marked(obj) -> bool:
    return floor_mark(obj) is True


def is_excluded(obj) -> bool:
    return floor_mark(obj) is False


def marked_by_us(obj) -> bool:
    """A mark (either way) this add-on wrote on the user's own mesh."""
    return floor_mark(obj) is not None and bool(obj.get(MARK_KEY, False))


def is_foreign(obj) -> bool:
    """Another add-on's object: it carries a system, ports, a load or a building's obstacles."""
    try:
        return any(key in obj for key in FOREIGN_KEYS)
    except Exception:
        return False


def marked_floors(scene) -> list:
    return [o for o in scene.objects if is_marked(o)]


def _loads(scene) -> set:
    coll = bpy.data.collections.get(LOADS_COLLECTION)
    return {o.name for o in coll.all_objects} if coll is not None else set()


def excluded_floors(scene) -> list:
    return [o for o in scene.objects if is_excluded(o)]


def _candidates(scene) -> dict:
    """Case 2 (the marked objects with the automatic ones) or case 3 (the
    marked objects only); case 1 is wired in operators/build_line, which hands
    the Floors collection to the tree."""
    marked = {o.name: o for o in marked_floors(scene)}
    if scene.conveyor_settings.floors_marked_only:
        return marked
    from .build_line import all_lines
    from .populate import PLACEHOLDER_COLLECTION_NAME

    placeholders = bpy.data.collections.get(PLACEHOLDER_COLLECTION_NAME)
    skip = {o.name for o in placeholders.objects} if placeholders is not None else set()
    skip |= _loads(scene)
    for line in all_lines(scene):
        item = line.conveyor_line.populate_item
        if item is not None:
            skip.add(item.name)
    found = {o.name: o for o in scene.objects if o.name not in skip and _is_floor_candidate(o)}
    found.update(marked)  # true is always a floor, whatever else it is
    return found


def _is_floor_candidate(obj) -> bool:
    """A mesh with faces of its own. Not: procedural systems whose base mesh is empty
    (a Racks system is an empty mesh with a Geometry Nodes modifier: realizing it in every
    line's floor raycast cost 0.5 s PER LINE per evaluation, 2.3 s per frame step with five
    lines), anything another warehouse add-on marks as its own
    (a system, its ports, a load, a building's obstacles), and the placeholder items. A
    mezzanine deck is a real mesh with faces and still counts; a procedural deck is marked
    as a floor, or goes in the Floors collection of the Scene panel by hand."""
    if obj.type != 'MESH' or obj.name.startswith("Placeholder"):
        return False
    if is_foreign(obj) or is_excluded(obj):
        return False
    return len(obj.data.polygons) > 0


def sync_auto_floors(scene) -> bpy.types.Collection:
    """Returns the helper collection, its objects matching the scene's floors."""
    coll = bpy.data.collections.get(AUTO_FLOORS_NAME)
    if coll is None:
        coll = bpy.data.collections.new(AUTO_FLOORS_NAME)
        coll.use_fake_user = True
    from .sync_stats import note_write

    wanted = _candidates(scene)
    have = {o.name: o for o in coll.objects}
    for name, obj in have.items():
        if name not in wanted:
            coll.objects.unlink(obj)
            note_write()
    for name, obj in wanted.items():
        if name not in have:
            coll.objects.link(obj)
            note_write()
    return coll


MARK_ITEMS = [
    ('FLOOR', "Floor", "Always a floor: legs and columns land on it (the shared marker wh_floor = true)"),
    ('NOT_FLOOR', "Not a floor", "Never a floor, even with faces right under a line: a table, a machine top (wh_floor = false)"),
    ('AUTO', "Auto", "The automatic rule: a mesh with faces under a line is a floor (no wh_floor)"),
]


class CONVEYOR_OT_mark_floor(bpy.types.Operator):
    bl_idname = "conveyor.mark_floor"
    bl_label = "Mark as Floor"
    bl_description = ("Floor, Not a floor or Auto for the selected meshes (the shared marker wh_floor, as the Floorplan "
                      "add-on's slabs carry). Your own objects only: another add-on's systems, loads, buildings and "
                      "marks are left alone")
    bl_options = {'REGISTER', 'UNDO'}

    mark: bpy.props.EnumProperty(name="Floor", items=MARK_ITEMS, default='FLOOR', options={'SKIP_SAVE'})

    def execute(self, context):
        from .build_line import all_lines, build_line

        targets = [o for o in context.view_layer.objects if o.select_get()]  # (context.selected_objects needs a screen)
        active = context.active_object
        if active is not None and active not in targets:
            targets.append(active)
        done, foreign, theirs = [], [], []
        for obj in targets:
            if obj.type != 'MESH' or (obj.type == 'CURVES' and obj.conveyor_line.is_conveyor_line):
                continue
            if is_foreign(obj):
                foreign.append(obj.name)
                continue
            if floor_mark(obj) is not None and not marked_by_us(obj):
                theirs.append(obj.name)  # marked by another add-on's hand: shown, never changed here
                continue
            want = {'FLOOR': True, 'NOT_FLOOR': False}.get(self.mark)
            if floor_mark(obj) == want:
                continue
            if want is None:
                del obj[FLOOR_KEY]
                del obj[MARK_KEY]
            else:
                obj[FLOOR_KEY] = want
                obj[MARK_KEY] = True
            done.append(obj.name)
        if not done:
            if foreign:
                self.report({'WARNING'}, f"{', '.join(foreign)}: another add-on's object; its floors are marked there")
            elif theirs:
                self.report({'WARNING'}, f"{', '.join(theirs)}: marked by another add-on; it stays")
            else:
                self.report({'INFO'}, "Nothing to change: select a mesh of your own")
            return {'CANCELLED'}
        scene = context.scene
        sync_auto_floors(scene)
        if scene.conveyor_settings.floor_collection is None:
            for line in all_lines(scene):
                build_line(context, line)  # the legs find their new floors
        what = {'FLOOR': "always a floor", 'NOT_FLOOR': "never a floor", 'AUTO': "the automatic rule"}[self.mark]
        self.report({'INFO'}, f"{', '.join(done)}: {what}" + (f" ({', '.join(foreign)} left alone)" if foreign else ""))
        return {'FINISHED'}


classes = (CONVEYOR_OT_mark_floor,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
