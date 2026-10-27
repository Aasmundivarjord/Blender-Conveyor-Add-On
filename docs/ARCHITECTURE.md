# Architecture (v2)

A conveyor line is a chain of catalog segments, not a freeform curve.
Pure Python evaluates the chain into a sampled centerline with exact
heading/incline; that "spine" is written into a `Curves` datablock as
attributes; one Geometry Nodes modifier builds everything from those
attributes.

```
props/line_settings.py   segment list + line settings (mm), live update callbacks
        │  update= -> operators/build_line.build_line(obj)
        ▼
model/segments.py        evaluate_chain(segments, start, width) -> Spine  (pure, unit-tested)
                         segment_frames() -> per-segment (start, end) poses for the gizmo
ui/gizmos.py             elevation arrow at the active straight's end -> rise_mm
model/spine.py           write_spine(Curves, spine, segments): polyline splines + attributes
        ▼
geonodes/cross_sections/{roller,belt,chain}.py   one line tree per type
   ├─ cross_sections/common.py   split spine, rails, guides, legs, cylinders, modules, finish
   ├─ frame.py                   (heading, incline) -> Rotation   [the ONE frame]
   ├─ populate.py                transported items along the full spline
   └─ modules/{rat,merge,diverter}.py  footprint decks + roller beds, instanced per module run
operators/detect_junctions.py    auto-merge: append MERGE + re-lengthen trailing straight
ui/panels.py                     Conveyor tab: Builder, Populate, Scene
config/                          JSON catalog + loader + units
```

## Why a `Curves` object

Legacy `Curve` datablocks in Blender 5.3 expose no custom attributes.
`Curves` (hair-curves type, object type `CURVES`) do, on point and curve
domains, and Geometry Nodes reads them directly. The spine must be
sampled as a POLY curve (the default Catmull-Rom overshoots attributes and
loops back at kinks), but the datablock is deliberately left at the
default type: writing `curve_type` = 1 (POLY) on a `Curves` ID corrupts
memory in Blender 5.3.0 Alpha (hash 29ccd5e2e824, 2026-08-04) and crashes
Blender soon after, even with no modifier and no add-on loaded. Instead,
`split_spine` converts the spine with a Set Spline Type (Poly) node as
the first step of every line tree. `write_spine` also removes a stale
`curve_type` attribute from lines built before this change.

## Spine layout

- Spline 0 (`role` 0): the whole line as one continuous spline. Populate
  samples it by arc length; module placement reads module runs instead.
- Splines 1..N (`role` 1): one per run. A run is a module footprint
  (`run_kind` 1) or a maximal stretch of non-module segments
  (`run_kind` 0). Rails, guides and rollers sweep conveyor runs only;
  legs cover all runs; module groups are instanced at module runs.

Point attributes: `heading`, `incline`, `yaw_offset`, `arc_len`,
`segment_index` (-1 = continuation onto a merge target, -2 = a routed
branch's prefix along its main line), `kind`, `guide_gap` (bitmask 1 =
left guide open, 2 = right). Curve attributes: `role`, `run_kind`, `module_kind`,
`module_exit`, `module_length`, `run_index`.

## Segment editing model (2026-09-23)

- A segment row is "the piece that ends at this point". The Straight /
  Curve L / Curve R / Module buttons extend the line when the last row is
  active and CHANGE the active piece otherwise (operators/segments.py).
- Elevation is not a segment kind: every straight carries `rise_mm`, set
  only by dragging the `GIZMO_GT_arrow_3d` in ui/gizmos.py. A non-zero
  rise builds a `model.segments.Incline` (angle = asin(rise/length)).
  Legacy INCLINE rows and the legacy `curve_angle` enum are migrated by
  `build_line.migrate_legacy_segments` on the first rebuild; the enum
  items stay in place because enum values are stored by index.
- Curve angle is the integer `curve_angle_deg` (5..350); catalog angles
  are quick buttons, anything else is flagged as a custom curve.
- The active segment of the ACTIVE line is highlighted by orange sleeves
  over its frame rails (`Highlight Segment` input, `build_highlight`),
  gated by Is Viewport so it never appears in a final render.
  It is pushed without a rebuild by `build_line.push_highlight` from the
  list-click callback and from the depsgraph handler (selection changes).
- Roller density is the per-line `roller_pitch_mm` (Builder panel, seeded
  to half the catalog pitch but never below diameter + gap). The High/Low
  detail switch and the scene LOD override are gone from the UI; their
  properties remain for old files and `resolve_high_detail` is always True.
- Legs are H-frame stands (posts, top member, brace, foot plates); guide
  rails hang on L-brackets every `Guide Bracket Pitch`, skipped in merge
  openings. Stand height is frozen as a point attribute before the posts
  are offset (fields evaluate on the geometry they are plugged into).
- **Stands are planned in Python (2.14).** `model/legs.plan_stands` takes
  the runs that carry stands (`spine._stand_ranges`: the fence paths and
  the right-angle transfers, a docked transfer end flagged), subtracts
  the blocked intervals (leg-free pieces, spirals, and `zone_intervals`:
  where the line passes over a spiral's footprint widened by a stand and
  `SPIRAL_CLEARANCE_M`), and places floor(L / spacing) + 2 stands per
  supported stretch, flush with both ends. `write_spine` inserts an exact
  sample at every stand (`insert_sample_at`, which interpolates every
  field incl. the goods' yaw) and marks it `stand` = 1 (-1 where one was
  taken out); the trees' `support_stations` keeps only marked samples
  (merged by 1 cm). `build_line` stores the plan for the viewport buttons
  (`piece_starts`, `stand_arcs` / `stand_points`, `stand_removed_*`,
  written only when they change). A stand the user takes out
  (`operators/stands.py`) is kept on its piece as metres from the piece's
  start (the piece's `removed_stands` ID property), so piece edits carry
  it; each build matches spots to the nearest stands within half the
  spacing, closest pairs first. The buttons are `ui/stands.CONVEYOR_GGT_stands`
  (pooled `GIZMO_GT_button_2d`, shown while the Scene setting `edit_stands`
  is on, for the active line only).
- **Supports: Floor / Ceiling** (`support_mount`, every line type; was the
  pouch sorter's `pouch_mount` in 2.13 and is carried over on build):
  `build_legs` switches between the floor H-frames and a ceiling trapeze
  (a cross member under the frame, 16 mm rods beside the rails up to
  `ceiling_above`: the first `Floors` surface hit straight up, else
  `Ceiling Z`, plates at the top); the pouch tree switches its portals
  for its own beam and rods. `Ceiling Mount` / `Ceiling Z` are shared
  frame inputs (`declare_frame_inputs`).
- **Ceiling Z from the building (2.15, round 7 R17).** `operators/ceilings.py`
  reads every `wh_levels` entry in world space (`_wh.levels.levels_world`,
  which keeps `headroom_m` and `label` since warehouse_common 0.4.1) and
  `_wh.levels.ceiling_at` picks the level of the line's origin by the
  level_at rule: ceiling = level z + `headroom_m`, None when that level
  publishes none (then the Scene setting). The host is found again by id,
  z and footprint for the panel's wording. `_push_inputs`
  sets it on every build; the deferred pass (`ceilings.sync`, after the
  obstacle sync) re-pushes it for hung lines through `build_line.push_input`
  and stores `ceiling_z_m` / `ceiling_from` for the Line panel, all compare
  before write (a settled pass writes nothing, R5).
- **Round buttons (2.15, suite UI rule).** `ui/theme.style_buttons`: on a
  light theme every `GIZMO_GT_button_2d` is a light disc with a dark ring
  (`box_edge` as `color`, `backdrop_fill_alpha` 0.15, `line_width` 2); on a
  dark theme a dark disc (fill 1.0). The stand buttons draw a `shape` glyph
  (`GLYPH_CROSS` / `GLYPH_PLUS`, one 12-point polygon each): with a
  backdrop Blender draws a shape in black over a light disc and white over
  a dark one, which a theme icon cannot do (probed on 5.3, 2026-10-13).
- Bevels are BUILT, not applied: Blender 5.3 has no bevel node and a
  Curves object accepts no Bevel modifier (`modifiers.new` returns None).
  Swept parts use `NodeGraph.filleted_rectangle` (Fillet Curve, Poly,
  3 arcs); boxes use `rounded_box`; cylinder caps use `bevel_caps`
  (extrude-and-shrink steps along a quarter circle). Posts are swept over
  realized unit lines so their bevel does not stretch with the height.

## Materials

Every line object carries five material slots on its Curves data (Frame,
Rollers, Belt, Modules, Links -- `materials.SLOT_ROLES`), created with the
shared defaults. The node trees take all their materials from modifier
inputs that `build_line._push_inputs` fills from those slots, and the
depsgraph handler re-pushes them when the user changes a slot in the
Material panel. Material indices on the generated mesh do NOT resolve
against a Curves object's slots (tested), hence the input route.
Duplicating the object copies the slots with the data; Alt-D / Ctrl-L
share them, like any other object.

## Goods flowing across a junction

A docked feeder's FULL spline is extended (model/spine.write_spine
`continuation`) with the main line's centerline from the junction's face
center onwards, transformed into the feeder's local space and blended
laterally from the face onto the centerline over the wedge length
(detect_junctions.continuation_for). The feeder's populate stream simply
rides that longer path, so its goods leave the feeder, slide across the
junction and continue down the main line to its end, then reappear at the
feeder's start. The extra points carry segment_index -1 and are ignored by
runs, legs and the highlight. When the main line rebuilds, its docked
feeders are rebuilt too (`_refresh_docked_feeders`); when it moves, they
follow it rigidly (`follow_target`, see "Origin attach").

## Transfer parts and the junction chooser (2026-09-30, v2.6)

Transfer sections are laid out in pure Python (`model/transfer_parts.py`)
and written into the spine as small part splines (roles 7-13:
ROLLER, BELT, CHAIN, WHEEL, BOX, RAIL, PLATE; fences reuse role 2), carrying
the curve attributes `part_r` (radius / width), `part_h` (height) and
`part_mat` (the material slot of wheels and boxes: Frame, Belt, Modules or
Links). `common.build_parts` only sweeps them (rollers and wheels: circles
scaled by part_r through Curve to Mesh's Scale input; belts, chains and
rails: fixed profiles, level normals), instances unit cubes (boxes) or fills
plates (Fill Curve works in XY and drops Z, so each vertex is lifted back to
the height of the outline point it lies on, faces are turned up and
extruded). So the geometry of every transfer type is exact, readable and
testable outside Blender (`tests/test_transfer_parts.py`).

The layouts follow manufacturer data collected for v2.6 (Interroll RM 8731
belt transfer, RM 8330 / 8230 angled merges, RM 8711 HPD, PM 9730 chain
transfer; Itoh Denki F-RAT-NX75, F-RAT-S and POP-UP; Hytrol E24 and spurs;
Intralox ARB; Cisco-Eagle pushers):

- the main line is left alone: its rollers stay square and run straight
  through every junction and its frame is continuous (no skewed rollers:
  none of the merge modules found have them; skewed rollers are separate
  edge-alignment sections);
- pop-up belt transfer (BELT, and the RAT corner): 2-5 yellow blades (3 on
  ~0.5 m, ~0.18 m apart) standing in widened roller gaps, parallel to the
  rollers, each with a 16 mm black belt on its top edge round end pulleys,
  flush with the roller tops (raised they ride 10-13 mm above). The bed is
  re-spaced like the real units (`blade_bed`): the rollers flanking a blade
  stand against it, every other gap is one common step (the line's pitch
  stretched a little so the length comes out whole);
- pop-up wheels at 90 degrees (Itoh F-RAT-NX75): a staggered row of black
  40 mm wheels in EVERY gap of an opened-up bed; angled (Itoh POP-UP):
  flat cover plates in every gap with the wheels turned to the feeder's
  travel, rising 3 mm through them;
- pop-up chain (pallets): 2-3 duplex strands in widened gaps, sprockets, a
  jack shaft and a gear motor under the bed;
- high-performance divert (STRIP, Interroll HPD): 2-4 cassettes of 120 mm
  in place of main-line rollers, each a top plate with two rows of eight
  pockets on a 60 mm grid and a short roller in each pocket swivelled to
  the feeder's travel, placed between the face's middle and the sharp tip
  (the upstream end of the opening once mirrored for a divert);
- angled merges: the wedge is the END of the feeder: rollers square to its
  travel, each clipped so its end caps clear the main line's frame (an
  angled side frame lies against it) and the taper frame, shorter row by
  row; a sheet-metal dead plate (two PLATE polygons, clipped out of the
  wedge with half planes) covers the side frame and the stepped roller ends
  and fills the sharp tip past the last roller; a frame rail runs under the
  taper fence, which bends into the main line's fence;
- ARB: belt plate (tree) + small rollers on a 50 mm grid (clipped to the
  UNMIRRORED outline, then mirrored with everything else for a divert);
- pusher: unit on a bracket opposite the branch, paddle 6 mm over the
  rollers;
- drive / lift boxes hang under the frame on two end plates, inside the
  floor stands' posts and below the cross member the stands carry the frame
  on: stands are spaced evenly along the whole line and one may fall under
  a transfer;
- a RAT corner (module kind 1) is the pop-up belt bed with a frame on three
  sides, an end stop across the far end and guards on the closed side.
The solid yellow slab every junction and RAT sat on is gone; so are the old
node-built strip belts.

Technologies (`config/presets/technologies.json`, appended at the END so
the Technology enum's stored numbers stay valid): SKEW angled roller merge,
POPUP wheels (15-90), STRIP high-performance divert (HPD), ARB, PUSHER,
BELT pop-up belt RAT (90), CHAIN pop-up chain (90). AUTO: 90 -> BELT, below
-> SKEW (merge) / STRIP (divert).

The chooser (`operators/junction_edit.py`, icon in `ui/gizmos.py`): a
screen-space `GIZMO_GT_button_2d` is projected over the origin of every
attached line related to the active line (its own junction, or the
junctions on the active main line) on each redraw; clicking it opens a
popup (`invoke_popup`) with angle buttons, all transfer types valid for the
role (the others show the angles they need; picking one sets that angle)
and Goods IN / OUT + Detach. The Builder panel shows the same chooser.
Angle buttons SWING the line about its origin to exactly that angle, like
R with typed degrees (the first version added a lead-in curve instead so
the line kept its direction; a 15 degree lead-in on a 75 degree line read
as "says 90, isn't 90", so it was dropped on 2026-09-30 -- a leftover
lead-in is removed and its arc length given back to the first straight).
When the main line has no room right there the junction slides along it
and the line follows; the operator says so.

## Pop-up transfers that move (2026-09-30, v2.6)

A RAT corner and a 90 degree BELT / CHAIN / POPUP junction are animated
parametrically, in step with the item stream, no simulation:

- `model/transfer_parts.py` lays the moving parts out LOWERED (belt tops
  4 mm under the rollers, wheels 3 mm under, chains 5 mm) and gives them
  `lift` (16 / 6 / 30 mm) and `tr`, the id of the transfer they belong to
  (`build_line.transfer_id(line, segment index)`, a CRC so it is stable
  across rebuilds). The spine stores them as `part_lift` / `part_tr`.
- `operators/stream.py` computes the group's transfer WINDOWS
  (`StreamTree.transfers`): (id, c0, c1, owner mask, class, height) -- the
  stretch of the stream, in item-CENTRE coordinates, during which the
  transfer carries goods. RAT corner: from the corner to half a width + half
  a slot past it (mirrored on a reversed line). 90 degree merge: the
  feeder's slide onto the main centreline (`continue_extra_m`) plus half a
  slot before the entry. Routed divert: the branch's blend after its switch
  point. Every line of the group receives every window (`Transfer k
  From/To/Mask/Class/Height/Id`, `Transfer Ramp`).
- `geonodes/populate.py`: an item whose centre is inside a window it
  belongs to (owner and class) rides `Height` higher, easing over the
  ramp. The group also OUTPUTS `Lift k` = how far transfer k's belts are up
  now: the slot nearest the window's middle (windows are shorter than the
  spacing) is found by index, its owner / class come from the same seeded
  Random Value picks as the items (the slot index as ID), and the window
  function of its centre is the lift. Time is parametric (index * spacing +
  seconds * speed), so scrubbing works.
- `common.build_parts` moves the moving parts up by `part_lift * Lift k`
  where `part_tr == Transfer k Id` before sweeping them.

## Fork-column vertical lift (2026-09-30, v2.6)

The LIFT module is a continuous vertical conveyor with cantilevered
forks, modelled on the Qimarox Prorunner mk5 (measured from its STEP
files: column 1071 x 378 mm, legs 660 mm apart, 8 tines 10 x 20 mm at 75
mm, comb rollers at 75 mm halfway between the tines) and the Unitfine
fork-arm loop lifter the user referenced. The Dalson slat tower in the
same references is a different machine (folding slat platforms on four
chains) and is not modelled.

- `model/segments.py`: constants `LIFT_LEN` (1.47 m comb frame), `LIFT_R`
  (0.3375: half the leg spacing, made 9 tine pitches so both legs sit on
  one comb grid), `LIFT_Z_BOT`, `LIFT_PICK_CLEAR`. `lift_apex(height)` =
  the top wheel centre, just above the outfeed (the loop's top 351 mm over
  it, as on the Qimarox). `_sample_lift` walks
  along the comb to the pick leg, straight up, a semicircle of LIFT_R over
  the top onto the other leg, straight down to the outfeed and along (Z) or
  back (C); corners are sharp (a second sample at the same point with the
  new frame), the goods stay level (KIND_LIFT). `Module.apex_m` carries the
  apex.
- `model/lift_parts.py`: `lift_layout`, the comb rollers (both combs on
  the tine grid, Z: infeed [0, centre] / outfeed [centre, L]; C: infeed the
  whole length / outfeed [0, centre] at the top), comb frames with a
  lowered rail on the column side (the fork crossbars pass over it), stop
  plate, corner posts, window (a black inset), gearmotor housing; the
  column body is a ROLE_COLUMN spline with part_r / part_h that
  `build_columns` draws as a box down to the floor; `fork_loop` = the forks'
  path once round (role 14, `lift_index`), oriented along the FLOW (a
  reversed line lifts on the other leg).
- Timing (the forks must be under the goods): the populate group spreads
  the goods on a pitch of span / count (so the wrap keeps one grid); the
  line tree recomputes that pitch from the same inputs
  (`populate.slot_pitch`) and spaces the forks by it along the loop from
  its seam, shifted by (`Lift k Phase` + half a slot - Stream Offset + t *
  v) mod pitch, where Phase = the pick corner's loop coordinate minus its
  full flow arc (`route_values`, from build_line's `lift_data`). The loop's
  length is free (it is NOT a whole number of slots: a first version tied
  the apex to the pitch and the pitch to the line length -- a feedback loop
  with no fixed point), so the fork spacing is irregular once per loop at
  the seam, which `fork_loop` puts at the bottom apex under the infeed
  comb. Forks past the loop length are dropped (`fork_on_loop`).
- `common.build_lift_forks`: Points sampled along the loop, the loop's
  `heading` sampled for the rotation (forks stay level), tines (unit
  length scaled by |Reach|, turned a half turn for a right-hand column),
  crossbar and trolley as instances offset from the column face.
- LIFT runs are no longer swept (split_spine), get no fences or legs; the
  combs carry their own rails.

## Viewport editing and the visual panel (2026-09-30, v2.6)

`ui/segment_edit.py`: a background 3D gizmo covering the active line
(`test_select` hit-tests the cached centreline of each piece, band width =
the line's width; nearest to the eye wins) outlines the hovered piece with
GPU-drawn bands, a press selects it (sets `active_segment_index`) and a
drag edits it: straight length along its axis (ray to axis closest point),
curve angle by the mouse's angle about the curve's centre in the plane of
the piece (15 degree steps, 1 with Shift). `use_undo` gives one undo step
per drag; a cancelled drag writes the value back as an ID property so an
unsnapped legacy length survives. A 2D + button past the line's end opens
the piece palette (`conveyor.piece_palette`).
The caches (`seg_path`, `seg_path_heading`, `seg_path_index`,
`segment_start_heading`, `line_width_m`) are written by build_line, so
hovering never re-evaluates the chain.

`ui/line_map.py` draws PICTOGRAMS per piece kind with numpy into
`bpy.utils.previews` images (the list icons, the strip header, the piece
library's fallback). The whole-line MAP and the ZOOM of the two first rounds
were dropped on 2026-10-05 (see below).

The piece keys went through three designs with the user (2026-10-01/02):
six picture tiles in a grid ("weird"), a D-pad of 80 px picture tiles with
a hub and a drawer ("takes up the whole interface"), and the current one:
an arrow-key cluster (inverted T) of ordinary labelled buttons -- Straight
above, Curve L / More / Curve R below, Blender's own triangle icons.
Decisions, in Apple HIG terms: compact labelled controls for a pointer (an
arrow alone could mean "move up"), secondary choices behind the More key,
grouping by spacing and alignment rather than boxes, content before
chrome. The value strip sits right under the keys, un-boxed: a header
naming the piece, then the primary value (curve: angle presets, then
direction + radius; straight: the length field, then presets; spiral: turn
presets, then direction + height; RAT: exit; lift: shape, height; buffer:
length, gap). The viewport's + popup draws the same two functions. Alt +
arrow keys are bound to the same operators in the 3D View keymap
(`segment_edit._register_keys`; unbound there in Blender's defaults), so
the shortcut appears in the keys' tooltips.

## The panel, round three (2026-10-05, v2.6)

User brief: "more minimal, highlight the most-used functions, version at
the top, no picture on top (confusing), a section for add-to-the-end /
type / width and the other line parameters, Details under it, Pieces as a
dropdown, Populate, Scene; populate should go straight to the picker; the
viewport like a 2D CAD drawing where you set the dimensions; under More,
pictures of the conveyor types like a library; separate the sections".
Reviewed against Apple's HIG (apple-design skill: layout.md "order content
by relative importance ... progressive disclosure", disclosure-controls.md
"place controls people are most likely to use at the top of the disclosure
hierarchy", pull-down-buttons.md "an Add button could present a menu that
lets people specify the item", entering-data.md "offer choices instead of
requiring text entry", collections.md for the image grid).

`ui/panels.py`: one panel "Conveyor" with the version from
`blender_manifest.toml` in `draw_header_preset` (right side of the
header); body = New line row, piece keys, value strip, Type + Width
(property-split rows). Sub-panels in `bl_order`: Line (direction, roller
pitch, fences / nose-over, the dock and junction chooser block), Details
(kind + exact values + per-module settings; id `VIEW3D_PT_conveyor_piece`
so it does not inherit the old Advanced panel's collapsed state), Populate
(header checkbox; Pick button; item field; speed, throughput; nested
Placement, closed), Pieces (closed; list + end pose + Rebuild / Detect),
Scene (floor, floors, dock distance, Dimensions / Spine switches, Play,
Rebuild all). Each sub-panel's `draw_header_preset` shows a dim summary
("Forward · fences", "Piece 3", "9 · 16.69 m", the item name) the way an
inspector shows a collapsed section's value. No pictures.

`operators/pick_item.py`: `conveyor.pick_item`, a modal eyedropper. The
Populate checkbox's update (`props.line_settings._on_populate_changed`)
starts it with INVOKE_DEFAULT when Populate is turned on without an item
(skipped under `suspended_rebuild`, so the operator's own `populate = True`
does not start a second one). It finds the 3D View WINDOW region under the
mouse (it is started from the sidebar, whose region cannot ray-cast),
casts `scene.ray_cast` through the evaluated depsgraph and sets
`populate_item` on a click; conveyor lines are refused (a tote riding a
line hits the LINE, its instance); orbit / zoom events pass through; Esc
or a click on nothing keeps the placeholders. `conveyor.clear_item` goes
back to the placeholders.

`ui/piece_library.py`: `conveyor.piece_library` (the More key, Alt+Down):
an `invoke_popup` with a 3-column `grid_flow`, each cell a
`template_icon(scale=4)` of a 256 px transparent render plus an operator
button (`conveyor.segment_add` with kind / module / exit). The renders live
in `icons/pieces/<KEY>.png` and are loaded into a preview collection on
first use (touching `image_size` loads them synchronously, else the grid
shows spinners on its first draw); a missing file falls back to the
pictogram. `tools/render_piece_thumbs.py` (outside the extension) renders
them in Blender from the plugin's own geometry: a scene of its own, a new
MAIN window (`context.collection` cannot be overridden; a line created
under the user's window once landed in their scene), Workbench, flat light
+ cavity + outline (metallic steel goes near-black under studio light),
orthographic 3/4 view fitted to the evaluated geometry (`bound_box` of a
Curves object with a node modifier stays zero: the realized mesh and the
instances are measured). `geonodes/materials.py` now sets the materials'
viewport display colour / roughness / metallic from the Principled values
(and migrates older files' defaults), so Solid shading and the renders
show yellow modules and black belts.

`ui/dimensions.py`: CAD dimensions and the group overlay. A POST_PIXEL
draw handler writes every piece's figure (`dimension_text`: length + rise
/ angle + radius / turn + height / module label) on the active line: a
dimension line with extension ticks beside straights and modules (left of
travel, `DIM_OFFSET_M` outside the edge), a leader at the outer edge of
curves and spirals; the active piece's figure in the + button's orange.
`figures()` projects the cached piece polylines (`segment_edit._pieces`),
`_measure` sizes the labels with blf. A 2D gizmo (`CONVEYOR_GT_dimension`,
one for all figures) does the hit-testing: `test_select` finds the figure
under the mouse, sets `index` on its target operator
`conveyor.set_dimension` and lights it; being a 2D gizmo it wins over the
background 3D piece picker. The operator copies the piece's value into
its properties and opens `invoke_props_popup` with `activate_init` on the
first field (click, type, Enter); `execute` writes back under
`suspended_rebuild` and builds once; junctions (sized by the lines they
join) just get selected. The scene setting `show_dimensions` switches it
off. A POST_VIEW handler draws the GROUP: `segment_edit.group_members`
(every other line with the same `stream.dock_root`, role MAIN / FEEDER /
BRANCH from the dock queries) as translucent bands along their pieces
(main orange, connected steel blue) with a role tag at each line's middle;
the piece picker's `test_select` also hit-tests those lines, stores the
hovered one (`group_hover`, brighter band and tag) and a click on it
selects that object instead of starting a drag.

`ui/segment_edit.py` `CONVEYOR_GGT_line_end` also owns the junction +
buttons: `detect_junctions.free_junction_faces(context, line, only=)`
lists, from the build caches, every free face of the line's merges /
diverters (a configured face without a docked line, or the other side of
a one-sided junction, mirrored across the centreline) for the active line
and for the junction it hangs on (`origin_dock`); each gets a + whose
target operator `conveyor.new_line_at_junction` (operators/new_line.py)
calls `open_junction_face` (a one-sided junction becomes a two-sided
MANUAL one keeping its docked line on its side; an auto junction becomes
manual so the second line docks at its angle and the junction survives a
line leaving), then `create_line(..., role=kind)` -- `role` pre-sets
`reverse` and the attach-role key so the first build docks it as a feeder
(MERGE) or a branch (DIVERTER) even at 90 degrees -- and selects the new
line. Renaming a docked line right after creation leaves the junction
with the old source name until the depsgraph handler's rename pass runs
(test scripts should `sync_feeder` after renaming).

## Throughput on the main line, shares on docked lines (2026-10-08, v2.6)

User: "the number of items populated acts weird ... the master throughput
should be set on the master conveyor and the merged conveyors get a % of
it, and the animation should correspond". The capacity-weighted owner
splits of the morning (feeders with a tighter default pitch took most of
the slots) were the weirdness. Now (`stream.tree_for`, `share_weights`):
the ROOT line's `throughput_ph` is the stream's total (0 = the root's
speed over its pitch, `capacity_ph`); every feeder has `share_pct` (0 =
auto); `share_weights` turns [feeder shares] into [root remainder, feeder
weights] -- explicit shares as given (scaled down together above 100 %),
the rest split equally between the root's own infeed and the auto
feeders -- and those weights ARE the slot-ownership splits (`Owner Split
k`), so the goods are dealt out in the set proportions. With a throughput
set, the spacing follows it at the root's speed (floored at item length +
clearance, with a panel warning giving the reachable maximum). Branches:
`share_pct` is the fraction of the goods passing their diverter; the
share-routing exits became weighted portions of a seeded random r per
slot (`Exit Split k` cumulative thresholds, `route_key` counts the
thresholds at or below r) carved depth-first (`carve`): a branch's slice
holds its own sub-branches' portions and then its remainder portion, so
its key range stays contiguous; feeders' branches carve from what the
root's branches left. `LineStream.fraction` and `line_load_ph` give the
rate through any line (the whole stream on the root, a feeder's share, a
branch's share of what passes it) for the bottleneck alerts and the
Populate read-outs ("Brings in 25 % of ZZ_Main's 1,500/h = 375/h").

**Fork pitch** (`lift_fork_pitch_mm` on LIFT segments, 400 mm default):
pushed as `Lift k Fork Pitch` (lift_data is 10 numbers), rounded down in
the tree to a divisor of the slot pitch; Details shows the resulting fork
count ("31 forks, 400 mm apart; goods on every 3. fork").

**The selected piece's band** (`segment_edit.CONVEYOR_GT_piece_picker.
draw`): drawn for the active piece on every redraw, in every shading mode
-- selection is feedback, the measurements are information and stay
hidden in Material Preview / Rendered (the user missed the highlight after
that change; the GN rail sleeves were in fact still there).

## Forks and throughput (2026-10-08, v2.6)

**Forks** (`common.build_lift_forks`). User: more forks, and forks
"spawning" during the animation. The forks were laid out from the loop's
seam at the slot pitch and dropped past the loop's end; the loop length is
not a multiple of the pitch, so one fork vanished at the end of the loop
and another appeared at its start at different moments -- a pop at the
bottom apex every slot. Now: fork pitch = slot / m with m = floor(slot /
0.4 m) (forks ~0.4 m apart, the goods on every m-th), n = round(loop /
fork pitch) forks on a uniform grid of n * fork pitch, mapped onto the
loop: identity on [pick - half a slot, drop + half a slot] (new inputs
`Lift k Pick` / `Lift k Drop`, loop coordinates from
`lift_parts.pick_loop_coord` / `drop_loop_coord`, direction-aware in
`route_values`; `lift_data` is 9 numbers per lift) and a uniform stretch
over the empty return leg that absorbs the remainder, continuous across
the seam. Forks move a few percent faster or slower on the return leg
and exactly with the goods where they carry them. (Sizing the loop to a
whole number of slots was tried on 2026-10-02 and reverted: the loop
length feeds the line length, which feeds the slot pitch -- no fixed
point.)

**Throughput** (`stream.capacity_ph`, `tree_for`). User: throughput should
come from the actual dimensions and speed. Every owner now moves `speed /
pitch` items per hour (pitch = centre-to-centre spacing, never below the
item length plus clearance), the usual "rate = speed / pitch"; the group
total is the sum, always present once the root is populated, so the
junction, transfer, spiral and vertical-conveyor bottleneck checks work
without typing anything. The old Throughput input is an optional **Target
rate**: with one set, `tree.targeted`, the group's spacing follows the
targets' total at the main's speed (owners without a target count at
their capacity), and the panel warns when the speed cannot deliver a
target at the pitch. The Populate section shows "Moves N/h · speed over
pitch" (and the group's rate on docked lines), plus a dim note when that
exceeds the type's practical rate (the catalogue's).

## Round twelve: faces of their own, four-way RATs, the pallet wrapper (2026-10-10 evening, v2.6)

Five asks in one evening. **Start-side mirror**: with the keys set to
Start the user looks back along the line, so a curve to their left is a
right turn in the line's direction of travel; `segment_add._configure`
mirrors CURVE_LEFT / CURVE_RIGHT and a RAT's exit when it prepends. The
Pieces list keeps the geometric truth (start to end).

**Each face as wide as its own line.** A two-sided junction had one
`merge_infeed_mm`; the 500 mm feeder on his 60° merge got a 1240 mm face.
`merge_infeed_right_mm` (0 = as the left) gives the right face its own
width; `junction_layout` takes `{side: width}`, `_set_infeed` writes the
side a line docks on, the panel shows "Left face / Right face" on a
two-sided junction, and switching a junction to Both copies the width
across until a line docks.

**A RAT is a four-way node.** `_is_junction` now includes RAT modules: a
RAT has no role of its own, each docked line brings one (`_line_role`:
the attach's `conveyor_attach_role`, else its flow), read through
`_junction_role` / `_source_role` wherever a module's kind decided
(docked_junction, feeders_of, _release_source, the refresh of docked
lines, goods linking). Its faces (`_module_face_world`,
`free_junction_faces`, `open_junction_face`) are the deck's side edges at
the module's middle, where `rat_parts` opens the guard (`open_sides`) and
`transfer_id` tags the belts; the face the line's own exit uses is never
offered. The + on a RAT face starts a branch (`new_line_at_junction` with
role DIVERTER); Goods in turns it into a feeder; the docked-line chooser
shows no angle or transfer type for a RAT host. In the live run the
operators completed (a branch docked on the right face, flipped to a
feeder and back) before the crash below cut the script short: the stream
census and the screenshot are still to do.

**Pallet wrapper.** `model/wrapper_parts.py` (pure, tested) lays out a
conveyorised turntable stretch wrapper from research (Handle It FA-4000,
Lantech Q Automatic: 65-81 in turntables, 86-92 in wrap height, up to
15-16 rpm, 40-45 loads/h, chain sections at ~0.23 m/s): a turntable disc
(a WHEEL part: it takes the module colour, a ROLLER would not) on its
pedestal, two chain strands under a pallet's runners with their beams,
the fixed sections' rails, the mast with its head, the film carriage and
roll (or a knife arm in Unwrap mode), the control cabinet. `table_radius`
= max(0.825 m, 0.8 × width): a 1260 mm pallet line gets a 2 m table.
Catalogued as module WRAPPER (segments.json, 2700 mm; technologies.json
inline_modules: 45/h for the chain-rule alert),
`MODULE_KIND_IDS` code 8 (an unknown code is a plain module run in the
trees: no bed, no rails, no legs -- no node change, no library
regeneration), `wrapper_mode` property, label "Pallet wrapper 2.70 m", a
More entry with a pictogram. Built live on a 500 mm test line (labels,
20 splines, the picture in the daily note); goods pass straight through
at line speed, a wrap cycle's dwell is not animated (parametric stream).

**The N sidebar** opens on the Conveyor tab when a conveyor line becomes
the active object (`ui/sidebar.py`: a message-bus subscription on
`LayerObjects.active`, re-subscribed after file load, with a second pass
0.15 s later because a hidden sidebar only gets its tabs on its first
redraw -- the first live call read the category back as UNSUPPORTED).

**The eyedropper and warehouse systems.** `pick_item.populate_from_system`:
clicking an object that publishes `wh_ports` (the Racks add-on, its
docs/INTEROP.md) takes the "out" port nearest the line's start (an "in"
port at the same spot loses), its load object (`warehouse.make_load` when
missing), the load's forward axis and the port's rate as the throughput
when the line had none. `populate.wh_load` reads the load dict;
`detect_forward_axis` honours its forward_axis (a EUR pallet travels on
its 0.8 m side; the longest-side guess turned it), `item_length_along`
its length_m / width_m. Verified live on ZZ_CraneRack: item, axis X,
0.8 m along travel; the port preference, Populate on and the integer
throughput were fixed after that run and are not re-verified yet.

**Blender crashed** at 18:09 inside the verification script: the
backtrace is the draw manager (`DRWContext`) under `screen.screenshot`
-- the test harness's screenshot of a just-opened window right after a
frame change, not an add-on operation (the RAT operators before it had
all returned). The crash log "Conveyor Test 2.7.crash.txt" and an autosave
from 18:08 are in the system temp folder. Harness rule from now on: draw
a new window once (`wm.redraw_timer`) before any screenshot, never
`frame_set` on a window that has not drawn.

## Round eighteen: every face of the RAT, the eyedropper on any rack (2026-10-11 night, v2.6)

Åsmund (screenshot of a corner RAT with one free + ): "the RAT does not
seem to be able to add conveyors to ALL its sides -- two independently
sized pallets attached to it".

- **The far face is a dock face.** A corner RAT (Exit Left / Right) has a
  fourth face opposite its start where the goods go straight through.
  Side `'END'` joins `'LEFT'` / `'RIGHT'` throughout detect_junctions:
  `_has_end_face`, `_source` / `_set_source` / `_set_infeed` / `_free_face`
  / `_docked_side` / `_sources` (segment fields `rat_source_end`,
  `rat_face_end_mm`), `_module_face_world` (centre at the module's far
  edge, heading straight on, a feeder's goods against it),
  `free_junction_faces` (a + there), `_sync_origin` (an origin within
  0.3 m of a far face docks there: `_rat_end_face_at`; no angle to snap,
  the role honours the attach role / flow), `_attach_branch` (keep yaw 0:
  straight through, unturned). `rat_parts` drops the end stop when a line
  docks there; `publish_line` publishes `rat{n}_end`; the panel lists the
  End face. The per-face width works as on the side faces, so a 1200 line
  straight through and an 800 line out of the side are two independently
  sized lines on one transfer; a feeder with Goods IN brings its own
  pallets.
- **+ on the start and end of a straight transfer.** Beside the piece
  keys (which extend THIS line) a second + starts a separate line: at
  the start a feeder of the RAT's type and width ending exactly on its
  origin (adopted as its tail parent, `adopt_tails`), at the end the
  takeaway (a tail continuation). `new_line_at_junction` takes
  `START` / `END`; `_line_at_rat_end` places the line.
- **A line ending in a RAT routes everything through its branches.**
  Åsmund's file (2026-10-11, screenshot): a main line out of a crane
  aisle ending in a RAT with one branch off its left face -- "the goods
  act weird". With the branch's Share at 0 the carve split the goods
  equally between the branch and the main line's own remainder, and half
  the pallets rode on into the transfer's closed far face and vanished at
  the wrap. `stream.dead_end`: a line whose last flow piece is a RAT with
  nothing beyond its end (no merge, no rack port, no line carrying on)
  keeps no remainder; its share branches take everything (explicit shares
  scaled up to the whole). `tools/trace_goods.py` traces the goods frame
  by frame (jumps, yaw flips, overlaps, counts per line) for the live
  check of the hand-over motion.
- **Docked lines' goods ran at the real speed, not the clock's (the
  "weird goods").** The root's Speed input is pushed as real speed × the
  scene's time scale; a docked line's goods run at the group's speed
  through "Stream Speed", which `route_values` pushed unscaled. At time
  scale 10 (round 13b T3) a branch's slot grid crawled at a tenth of the
  main's: the main dropped the pallet at the RAT hand-over at frame 45
  and the branch would have drawn it at frame 442; at Åsmund's scale 3
  every branch, carry-on and feeder moved its goods at a third of its
  main line's. Stream Speed is pushed × `time_scale(scene)` now;
  `push_time_scale` re-pushes every line on a clock change. Found with
  `tools/trace_goods.py` (one-to-one matched vanish / appear events; T1
  and T2 at scale 1 were clean, which is what made the clock the suspect).
- **Link anchors are flow-wise (IO-2).** `_entries` writes "end" for a
  reversed line's origin dock and "start" for its far end (contract §3);
  `conveyor_port` keeps its geometric keys.
- **One conveyor serving a crane aisle both ways (IO-1).** The Racks'
  delivery options (2026-10-11) publish one `aisle<k>_io` port per aisle,
  role "io", at the in-feed's place: `heading_deg` is the OUT direction,
  `heading_in_deg` the IN direction, `rate_ph` / `rate_in_ph` the two
  rates, `capacity_ph` the crane's dual-cycle capacity shared by both.
  `model/port_io.py` (pure, tested) reads a port for a LINE's role:
  `heading_deg(port, role)`, `body_heading_deg`, `rate_ph`, `accepts`,
  `link_role` (never "io"). `world_port(system, port, role)` takes the
  role, so a reversed line docking by its origin lies along
  `heading_in_deg + 180` and a forward line docking by its end aims along
  `heading_in_deg`; `apply_port_load(..., role)` seeds the throughput from
  the role's rate; `scan_ports` already served io ports for both lookups
  and the dock records the line's role. Ports at the rack's rear need
  nothing: position and heading say where they are.
- **Eyedropper on tote and flow racks (EYE-1/2/3, coordinating session).**
  `_defer_make_load` remembers the system and port it was asked for and,
  once the other add-on has built the load, applies it to the eyedropped
  line (a face port is no dock, so the dock re-sync alone never did) and
  puts the result in the status bar. `world_port` understands face ports
  (`"face": [p0, p1]`, `"outward"`): position = the face's middle, heading
  = outward; `port_distance` measures to the face segment, so a flow
  rack's pick face is told from its fill face. The Racks panel's "Carry
  This Rack's Load" (`warehouse.carry_rack_load`) goes through the same
  loads and `apply_port_load`, so the two paths always agree.

## Round nineteen: flow markers, the square RAT outline (2026-10-12, v2.6.3)

Åsmund: "the RATs don't act correctly" (his 2.6.2 predates the dead-end
and stream-speed fixes), "arrows on the conveyors showing which way they
bring the goods, clickable to change, on all of a RAT's sides", "the RAT's
bounding box should be just a square" -- then: "I love the arrows on the
rack conveyor, borrow this for the conveyors; set throughput and direction
by clicking them; automatic snapping between all these arrows across
plugins".

- **`ui/flow_markers.py`**, modelled on the Racks' `ui_markers.py` (same
  disc / capture ring / join bar / 1 m arrow / tag, same colours): two
  markers per line at the FLOW start ("in", the arrow ends at the start
  pointing into the line) and the FLOW end ("out", the arrow leaves it),
  for every line while a line or a port system is selected, in Solid /
  Wireframe with overlays, behind the scene's Flow switch
  (`show_flow_markers`). Colour: blue when the end is docked (junction,
  port, tail), red when the end feeds a port beyond its capacity, orange
  when free. The tag reads the user's own numbers (throughput or share)
  -- no stream evaluation on redraw. A `GIZMO_GT_button_2d` on each disc
  (48 at once) opens `conveyor.flow_settings`, a popup editing the line's
  `reverse` (with the forward / reverse label), throughput or share,
  speed and populate -- property updates rebuild and re-dock live, so a
  flip on a docked line swaps its role on the junction. A RAT's faces are
  therefore set one by one through the lines docked on them.
- **Snapping across add-ons** is the port docking that already exists:
  our start / end within 0.6 m of a Racks port docks (the capture ring
  drawn on both sides); the Racks side is asked to dock their delivery
  conveyors onto our published `line_in` / `line_out` ports the same way.
- **The RAT outline** (`segment_edit._rat_square`): a RAT's hover /
  selection outline is the module's square from the cached start frame,
  heading, `rat_length` and the line width, not the band along its
  turning centreline that drew a bent hexagon on a corner RAT.
- 2.6.3 packages this with the dead-end rule, the stream-speed clock fix
  and IO-1 / IO-2; no node tree changed, so the 18:40 library is reused.

## Round seventeen: the pouch sorter (2026-10-11 night, v2.6)

Åsmund: "another conveyor option: a pouch sorter with hanging pouches that
sorts objects; the bag always in x & y dimension, standard but
controllable". A sixth cross section, `pouch`:

- **Type** `pouch_sorter` (`config/presets/conveyor_types.json`), no width
  groups: `resolve_width_mm` returns the POUCH width, so the footprint,
  ports and switch geometry follow the bag.
- **Figures** in `model/pouch.py` (pure, tested): standard pouches
  400 × 600 (default), 300 × 450, 500 × 700 and Custom width × height;
  depth along the rail (120 mm) and trolley pitch (250 mm, never closer
  than depth + 30 mm); the rail section (60 × 80), hook, portal rise;
  `item_drop_m` (Height Offset: rail top down to the pouch bottom plus
  40 mm) and `quantize_m` (the goods' pitch = whole pouch pitches).
- **Tree** `geonodes/cross_sections/pouch.py` ("Conveyor - Line (Pouch)",
  version 1): the spine is the rail's TOP edge (the line object sits at
  rail height); one rail beam swept on the centreline through switches
  (`rail_runs`); portal frames at Support Spacing (posts beside the
  pouches down to `floor_below`, a beam over the rail, a hanger down to
  it -- nothing crosses the pouches' path); trolleys under the rail at the
  pouch pitch riding with the line (index × pitch + seconds × Speed,
  wrapped over WHOLE pitches like the goods stream, trolleys beyond the
  run are in the return loop and deleted), each a hook, a hanger bar and
  the pouch (Link material). `finish(surface="pouch")`: no junction decks
  (`build_merge_junctions` returns empty), the highlight sleeve sits on
  the single rail.
- **Wiring**: `_push_inputs` pushes `pouch.line_values` (bag figures, rail
  section, Guide Rails off, Height Offset) and turns the goods 90° so
  their long side lies across the rail inside the pouch; `stream.tree_for`
  floors and quantizes the pitch to whole pouches for a pouch root;
  `build_line` emits no transfer parts, fences or outlines for junctions
  on a pouch line (a switch is the rail); the panel shows Pouch / Width /
  Height / Depth / Pitch instead of Width, and no Fences toggle.
- **Open**: pouch k and item k stay aligned on a standalone root line;
  a docked or reversed pouch line may show the goods a fraction of a
  pitch off its pouches (the stream's offset and phase are not fed to the
  trolleys yet). No wheels on the trolleys, pouches are closed boxes.
  The shipped node library must be regenerated to include the tree
  (`tools/build_tree_library.py`); until then a pouch line builds its tree
  on first use.

## Round sixteen: the RAT unit's loose ends (2026-10-11 evening, v2.6)

Round 6 of the live symbiosis tests (the Rack session's bridge,
`_coordination/round6_result.json`) left five gaps.

- **A deleted line left its face wide (RAT-7).** The handler's
  deleted-feeder cleanup cleared `merge_source` alone. `_free_face(seg,
  side)` now frees a side: the source goes and a RAT's `rat_face_*_mm`
  is 0 again, so the module shrinks back; `_release_source` (undock,
  detach, role change) uses the same helper.
- **A renamed line lost its dock (RAT-8, reported as "made wider").**
  The test renamed the line right after creating it, then changed its
  type and width. The RAT face still carried the old name, so the next
  rebuild's `_sync_origin` saw the face taken by a name no line has,
  tried to cut a 90° merge into the RAT line (no straight: "needs a level
  straight"), and dropped the dock; the cleanup later cleared the name
  but not the 540 face. Now a source name no object has does not block
  the face (the line at the face adopts it), and the handler re-points a
  stale name to the line that records its dock on that RAT and sits on
  the face (`_renamed_source`) instead of clearing it. With the dock
  intact the width change already worked: `_set_infeed` takes the new
  frame width, the target rebuilds (`rat_length` grows the module), and
  `_refresh_docked_feeders` puts the docked origin back on the moved face
  centre.
- **New Line from End gave a 500 mm takeaway on an 800 RAT (RAT-9):**
  `create_line(like=src)` -- the takeaway keeps the line's type and width.
- **A feeder's end at a RAT's start face stayed loose (RAT-10).** Tail
  continuation (`_sync_tail`) ran only for the line that MOVED; the moved
  feeder's end reaching a standing RAT's start adopted nothing.
  `adopt_tails` (handler, after a moved line's own sync): a line whose
  START lies within TAIL_JOIN_M of the moved line's END, pointing on, not
  reversed and not pinned at its origin, gets TAIL_KEY and is snapped
  onto that end (`follow_tail`: the tail and everything docked on it
  move, the feeder the user is holding does not). `tail_continuation`
  also refuses a line pinned on a rack port.
- **RAT-to-RAT "0.10 m overlap" (RAT-11).** The decks do not overlap: the
  face sits at width/2 + SIDE_PLATE and the second deck starts there.
  The bounds measured were the GN H-frame stands: posts (Support Size
  0.06) inset half a post from each run end, foot plates 2.4 × size =
  0.144 m square, so 0.042 beyond a run end along travel and 0.062
  beyond the deck edge across. Two 0.9 m, 800 mm RATs put the second
  RAT's start-stand posts (0.04 / 0.86 along the face) on the host's
  end-stand posts (0.03 / 0.87): posts and feet through each other. A
  docked RAT end now gets no stand of its own: `build_line` collects
  `no_stand_ends[i] = (start carried, end carried)` for a RAT that is the
  line's first / last piece and not free there (`_rat_free_ends`), and
  `write_spine` flags the run's first / last point `no_legs` (the leg
  stage already drops stations where `no_legs` > 0.5). The frame it docks
  on carries that end, like a transfer bolted to the neighbouring frame.
  Not changed: two stands still meet where a straight runs into a RAT on
  the SAME line (the guide run's flush end stand and the RAT run's; feet
  overlap 8 cm).

Round 7 passed RAT-7/8/9/11 and left four more:

- **RAT-10 still loose.** `adopt_tails` ran in the handler for MOVED
  lines, but a line built with its end at the RAT's start was never
  "moved": its first build remembered its matrix. Adoption now runs in
  `sync_feeder` (after `_sync_tail`), i.e. on every build and every
  handler re-sync of the line whose end is there.
- **Open start / end faces on a standalone unit (RAT-12).** `rat_parts`
  did emit the guards across both ends, but every RAT fence point carried
  the MODULE's heading and the tree sweeps a fence with its normal left
  of the point heading: a guard across the line had its normal along
  itself and swept flat. `build_line._fence_points` gives each fence point
  the heading of the polyline's own direction (`atan2(-dx, dy)` in the
  module frame); along-travel guards are unchanged.
- **The deck read as plain rollers (RAT-13).** The pop-up belts were
  there, lowered 4 mm in 32 mm slots between 48 mm rollers, on blades in
  the deck's own colour. The blades are steel now (`MAT_FRAME`) and the
  belts rest 2 mm under the roller line (`BELT_REST_TOP` -0.002, lift
  0.014: still 12 mm over the rollers when raised), so the dark belt
  slots are legible at rest. The same parts serve 90° belt junctions.
- **A reversed feeder published line_in taken (RAT-14).** `publish_line`
  computed its taken flags geometrically (origin / far end) and wrote
  them onto flow-wise ports. It now swaps them for a reversed line and
  takes the far end's dock by its role (`DIVERTER` when reversed).

Round 8 passed RAT-10 and RAT-14 and showed the start guard still open
while the end guard stood -- the same polyline, the same heading, one
end upright and the other hanging. Rather than chase the sweep's
binormal, a guard across a face is now a BOX bar at guide-rail height
on its posts (`transfer_parts.end_stop`): a box is turned along its own
two points and stands whatever the heading. The belt slots are black
end to end (blade and belt), since a steel blade's edges made the slot
read as a groove. A drive / lift block under the bed was suggested and
left out: Åsmund called such boxes under transfers "ugly blocks" on
2026-10-10 (`_drive_box`); it can come back as an option on his word.
RAT-15 (the four-docked RAT "empty" in the iso while the top view shows
its roller stripes) was withdrawn after a live probe (`tools/probe_rat.py`):
the coordinator's bounds script summed node-tree instances only, and the
swept bed never appears there. Round 9 also showed the pop-up belts light
in Solid shading: a stale viewport display colour on the shared rubber
material. `materials.rubber()` now forces a near-black display colour on a
light one (never a restyle) and `ensure_slots` runs every role's factory
on each build, so the refresh reaches existing files. The near end-stop
bar looked tilted in the iso; the live instance dump (round 10) showed
both bars identical and level -- projection, closed. The round-10
close-up showed why the slots never read at rest: a 16 mm belt 2 mm under
the roller line with the blade 8 mm down is hidden by the near roller
from any iso angle. The blade is 30 mm now (it fills its 38 mm slot), the
belt 24 mm, belt top 1 mm under the roller line, lift 0.013 (raised:
+12 mm). Round 12 verified the slots (the offline station list of
`blade_bed` matched the probe's roller bounds to the millimetre; the top
view shows the four 38 mm slots with their pulleys) and settled the
colour: black belts on black carriers over a dark floor read as plain
gaps, so the carrier is the galvanized frame colour -- a light slot floor
with a black belt line, the Interroll look. (A zinc carrier would need a
roller branch in `build_parts`' box materials, i.e. every line tree.)
Rounds 11 / 11b passed the eyedropper on tote, carton-flow and pallet-flow
racks, the RAT far face with two widths, the start / end + of a
standalone RAT and the pouch sorter line.

## Round fifteen: the right-angle transfer as a unit (2026-10-11 evening, v2.6)

User: "the RAT should have legs on all its sides when it is standalone,
connect to all four sides, its width should follow the conveyor it is
attached to, but other sizes too: a pallet 1200 in and 800 out, two
different types connected intuitively and everything working together".

- **Per-face width** (`rat_face_left_mm` / `rat_face_right_mm`, 0 = the
  line's own): a line docking on a side face writes its frame width
  there (`_set_infeed`, the RAT variant), the module grows to the widest
  face (`transfer_parts.rat_length`: a 1200 mm line on an 800 mm RAT makes
  it 1240 mm long), the docked line is never resized, the face is its own
  width again when the line leaves (`_release_source`). `evaluate_line`
  builds the RAT with that length, so the path corner, the face centres
  (`_module_face_world`, `free_junction_faces`) and the parts agree.
- **Parts** (`rat_parts`): the opening in a docked side's guard is as wide
  as that line's frame, the guards either side close the step to a wider
  deck; a standalone transfer (nothing at its start / end, `_rat_free_ends`)
  gets guards across those faces and its own stands (two posts and a bar,
  `_stand`) under every free face down to the floor (`floor_drop` from
  the scene's floor level); the GN's own legs stay along the axis.
- **Goods sideways** (`populate.goods_turned`): on a line with a RAT corner,
  or hanging on a right-angle face / carrying on from a line that ends
  sideways, the item's long side runs along the line, so
  `populate_item_length` (the pitch floor, the slot inset, the Item Length
  input) uses max(length, width) there: a EUR1 is 1.2 m along after the
  transfer. The Populate panel alerts when a docked line's share exceeds
  what it carries at the group's speed with that floor (the chain rule).
- **Intuitive attach**: the + on a RAT face starts a line of the RAT's own
  type and width (`create_line(like=...)`); a line that starts with a RAT
  docks on another RAT's face (a sorter grid: `_sync_origin` lets a
  RAT-first line match RAT faces only, never a cut-in junction); the RAT's
  Details list each docked face ("Left: Line.001 · 1200 mm roller (mdr) ·
  in"). Adjacent RATs share the join: the docked one's start is open (no
  guard, no stand), the host's face is open.
- **Published faces** (`publish_line`): a RAT's free side faces are `io`
  ports on the line (`rat1_left` / `rat1_right`, width = the face's,
  taken when a line is there), so stations and lifts dock onto them by the
  same path and a floor-plan builder lists free faces.

## Clean binaries, a repository others may read (2.26.4)

- The 21 piece icons carried Blender render stamps (PNG tEXt chunks), including the path of the
  .blend they were rendered from on another computer. The text chunks are stripped; the pixels
  are byte for byte the same.
- `tests/test_public_text` now:
  - checks that no shipped PNG carries text chunks and no shipped .blend a local path (zstd is
    decompressed where Python can);
  - keeps the company and product names as SHA-256 hashes (`NAME_HASHES`). Every word, and its
    start cut to each name's length, is hashed and compared, so the test never spells them.
- The manifest excludes `/publishing/` (listing media) and `/.github/` (issue templates): the
  GitHub repository carries them, the zip never does.

## Stands added by hand (2.26.3)

- `model/legs.plan_stands(added=, added_sources=, gaps=)`: each added arc stands where the user put
  it, on a supported stretch, kept half a post inside the stretch's ends and a post clear of every
  other stand. Removals still match planned stands only.
- `gaps` gives the middle of every stretch between two stands that is at least `ADD_GAP_M` (0.6 m)
  long on a supported stretch.
- Records: `added_stands` on each piece (metres from its start), next to `removed_stands`, so they
  travel with their piece.
- Operators: `conveyor.stand_add`. `conveyor.stand_remove` drops an added record within a post
  (`ADDED_REACH_M`) before it would record a removal. `conveyor.stands_restore_all` ("Reset")
  clears both kinds.
- `build_line` publishes `stand_gap_arcs` / `stand_gap_points`, interpolated on the spine, with no
  extra samples.
- `ui/stands`: a − (`theme.GLYPH_MINUS`) on every stand, a + on every removed spot, and a smaller,
  quieter + in every gap. The Line panel says "− takes a stand out, + adds one" while editing, and
  counts what is taken out and added.

## Build mode: Shift and Ctrl tune the piece just added (2.26.2)

- `model/build_keys.key_action`: Shift + arrows → `adjust:longer / shorter / left / right`; Ctrl or Cmd
  + up / down → `adjust:up / down`. Cmd because macOS keeps Ctrl + up / down for Mission Control.
  Other modifier mixes pass through.
- `model/build_keys.adjust` (pure) gives the new values for the piece at the growing end:
  - a straight ±150 mm (the catalogue step, at least 150 mm);
  - a curve's radius one standard size in its own system (metric / imperial), or ±100 mm when
    custom;
  - a curve steered ±15°, flipping side through straight, at most a U-turn;
  - a straight's rise ±100 mm; a spiral's or a lift's climb ±100 mm, keeping its way.
- `operators/build_mode.CONVEYOR_OT_adjust_piece` applies them with one build, and is called with
  undo = True: one undo step a key. Key repeat works.

## Several lines on a RAT; the pouch sorter's look; types retired and hidden (2.26.1)

- **One stand per joint** (`model/legs.share_joints`, called from `model/spine._stand_ranges`).
  - Every run got a stand flush with each end. So where a transfer met the run beside it there
    were two stands a post apart, with their foot plates through each other.
  - Now the transfer keeps its stand and the run beside it rests on it. Between two transfers,
    the first keeps it.
  - A joint inside a leg-free or carried stretch is left alone.
- **Lines on a straight transfer's sides rest on its frame** (`build_line._ends_on_rat_faces` →
  `write_spine(rests_on=...)`): no stand of their own at the face.
  - A corner stands only under its start and its exit. So lines on its far face or its other
    side keep their stand, because they carry those edges.
  - `rat_parts` no longer gets `stands`. Those posts under a transfer's free faces stood beside
    the planned stands, and went to the floor under a ceiling-hung line.
- **A corner with lines on its other faces** (`stream._transfers`):
  - **The stop sits `STOP_PAST_M` past the corner.** At the corner itself the lines on the faces
    part from the main line, and every one of them drew the standing item (three in one place).
  - **Goods going straight through to a line on the far face neither stop nor lift.** The
    transfer's new last field `except` names that line's edge. The populate tree reads it as
    `Transfer k Except` and leaves the goods that edge takes alone.
  - **Arrivals (R22.4).** `arrivals_record` skips the stand for those goods. It now counts the
    corner's stand for the lines on the other faces too: the old `stop < leave_at` test missed
    a stop at the parting point.
- **Side faces lift on the deck only.** A branch's goods were set down half a slot out over its
  rollers, and a feeder's rose half a slot early on the feeder. Both now ride up and down at the
  face, with the ramp inside the deck, as at a corner since round eight.
- **Cleated belt retired.** It was the `pocket` tree.
  - `REPLACED_TYPES` maps its enum number 5 to the belt (2). `build_line.migrate_removed_type`
    applies it on build and in the sync pass, so a saved line opens as a belt.
  - Enum numbers stay as they are.
- **Hidden types** (`ConveyorTypeSpec.hidden`, `loader.get_offered_types`). The omni-wheel deck is
  hidden until its redesign (docs/OMNI_SPEC.md).
  - The enum keeps every type, so saved lines and scripts still use it.
  - The Type row is a menu of the offered types (`CONVEYOR_MT_conveyor_types`); the gallery and
    the registry's presets offer them too.
- **The pouch sorter's look** (`cross_sections/pouch.py`):
  - an I-section rail with rounded edges;
  - moulded plastic trolleys (the Links material) coupled into a train, with four rubber wheels on
    the bottom flange;
  - round hooks;
  - a moulded hanger bar and mouth rim;
  - a subdivided, smooth bag that fills out to a rounded bottom (its bounding box stays width ×
    depth × height, open at the top);
  - portals on bevelled swept posts (`common.swept_posts`, shared with `build_legs`), with knee
    braces;
  - round ceiling rods.

## Simple flow, published (round 8 D, R22 / R22.2 / R22.3 / R22.4, 2.23)

- **Ports in the group's resolution** (`flows._port_graph`): each system a
  line docks at enters with its own graph, `simple_flow.build_graph` over its
  published records (its ports, and its system node dealing its delivery
  points when it is one stream). A port a line STARTS at leads its stream
  (a dock edge; the line keeps its own Speed, `own_speed`; a pre-R22 port's
  legacy rate stands in for its population; a port with neither leads
  nothing); a port its end feeds takes the stream and caps it by its
  `max_population` (a legacy `capacity_ph` converts). Resolution with
  `simple_flow.DEFAULT_SPEED` (R22.2). The master may be a port: the panels
  say "100 % of Rack · out0" (`flows.port_label`).
- **Caps** (R22.2): the slot grid's floor goes into resolve as
  `max_population` on every section of every line (item + gap over the
  floor pitch), published on `line_in` and on every taken junction port
  when below 1, so build_graph gives each section the same limit. A layout
  whose owners together outgrow the grid with no section carrying all of
  them (a branch before a merge) still falls back to slowing every owner
  (`GroupFlow.scale`): rare, and then a follower's published value can
  differ from a reader's resolve. Where a merged section is over its cap,
  warehouse_common resolves the feeders first and the main stream takes
  what is left -- so a main can stop: main, a 45 degree feeder and a 90
  degree feeder at 50 % each under the 90 degree stop's 45.7 % floor run
  at 0 %, 45.7 %, 0 % (test_merge_stream / test_tech now stay under the
  floor; reported to the PM for a decision).
- **Published** (`publish_line`, `wh_system`): `population` -- a master
  (WC's `is_master` of its first section) its slider, the stream's input (0
  without goods of its own), every other line its resolved `line_in`
  population, what it animates (R22.3; check 11: followers equal resolve,
  a master at or above it); `speed_m_s` = the speed in use
  (`stream.line_speed`); `master: true` when pinned. Ports' `period_s`
  where a line's end gets only some of the slots (a branch): the average,
  3600 / the flow there (`crossings_at`).
- **conveyor.set_line_flow(line_id, population, speed_m_s, share, by)**
  (R22): population 0..1, speed_m_s > 0, share 0..1 of the master (a
  branch's Share slider; its link keeps the local fraction); a negative value
  leaves that slider; one build for all; record `conveyor_flow_from`
  {by, what was set} ("Set by Floorplan"); the same again writes nothing
  (`model/public_api.flow_plan`, unit tests).
- **Exact arrivals** (R22.4, WC 0.6.2, `stream.arrivals_record`): a link
  whose flow anchor is "end" carries `arrivals` {"schedule": [[0, phase_s,
  period_s]] -- the slot grid's crossings of the stream origin, item k at
  phase + k period, operation seconds, the populate tree's numbering --
  "path": [[fractions, branch], ...] -- the owners' deal first on a shared
  grid (the root's goods: owner 0), then every split the goods pass toward
  the port with its edges in split_order and the edge they take (None: what
  no branch takes) -- "delay_s": the travel from the origin (an item centre
  half a slot in) to the end, plus each stop's stand on the way
  (`transfer_motion.lag_m`)}; `simple_flow.branch_arrivals` over it gives
  the very times the goods reach the port. Omitted (readers keep phase_s /
  period_s, the average) for a stopped stream, a feeder's goods reaching
  the end, a merge or a bypass re-join on the way, a Route by class, a
  branch with its own item, a buffer on the line.
- **The end is where the goods are drawn** (`build_line`
  `path_length_m`, `stream.path_length_m`): populate samples spline 0 by
  LENGTH, and a 45 degree divert's blend off the main runs longer than
  the main's arcs it replaces (91 mm on a 0.6 m-wide divert): the flow
  end's stream coordinate is the offset plus that drawn length (the
  crossings at an in-port and at the line's own `line_out` too).
- **The wrap a hair over whole pitches** (`WRAP_MARGIN` 1e-5): the tree
  floors span / pitch in single precision, and the exact multiple Python
  gave it came out just under on some lengths -- one slot fewer, every
  pitch 1/n wider than published (6.9 m at 61 %: 1.243 m drawn, 1.066 m
  published; 5 of 63 lines in test_simple_flow L).
- **A clock change takes at once** (`build_line.push_time_scale`): a line
  whose on-screen speed changed is tagged (input writes alone left the
  goods at the old clock until the next rebuild) and republishes its
  ports and links (their operation-second times follow the clock).
- tests/headless/test_flow_publish.py: a lone line, a divert, a merge, a
  capped master, a pinned master downstream, a rack-led line (own speed),
  a crane in-feed's cap, set_line_flow; every published population checked
  against build_graph + resolve over all published records (check 11's way).
- tests/headless/test_arrivals_r22_4.py: branch_arrivals over the published
  arrivals against the animation (goods followed to the port across frames,
  to 0.01 ms): a 45 degree divert's branch and main, a 90 degree pop-up
  (the stop on the way), a shared grid (a feeder merging downstream), a
  line the API turned about (reversed, its origin at the port), a share
  change, a 2x clock; none behind a merge, a bypass, a stopped stream.

## Buffers: Output %, a FIFO (round 8 E, R22.6, 2.24.0)

Åsmund (round 8): "the buffers should be connected to the previous conveyor
... we should be able to set 'output' percentage for it. But the in should
be set by the conveyor in front of it. It should fill up with items from the
object populated before." The PM's design, approved 2026-10-15:
- **Setting**: `buffer_out_pct` (Output, 0-100 %, default 100). In follows
  the line before. The Out rate (Auto / Set) is gone from the panel; its
  fields stay in the file. Migration (`flows.migrate_buffers`, once a line,
  stamp `conveyor_buffers_migrated`): Set -> Output % = out / what arrives
  there (`model/flow_migration.buffer_out_pct`), Auto -> 100 %.
- **Published (R22.6, warehouse_common 0.6.5)**: each buffer's exit is a
  port in the line's wh_ports, `{"id": "b:<uuid>", "role": "buffer",
  "kind": "point", "u_m", "taken": true, "exclusive": true, "out_fraction",
  "capacity_items"}` (+ the line's `max_population`); the uuid lives on the
  piece (`wh_buffer`). build_graph makes it a section boundary entered by a
  "buffer" edge whose share is the out fraction; resolve passes that much
  on and reports the rest in `Resolution.buffered`. `flows._sections` does
  the same for the group's own resolution (`GroupFlow.buffer_out`). The
  populations published are the state BEFORE the buffer is full; the cap
  once it is full is the animation's. A buffer no longer throttles the
  stream statically.
- **Animation (model/buffer_fifo, populate tree 30)**: from t0 (frame_start)
  a buffer lets one item out every in-period / Output % (`Period`, from
  rank `First` at `Start`), first in first out -- buffer_item_times exactly
  until full (test_buffer: 0.000 s); the rest roll up to the queue and stand
  a zone each behind the front stop, stepping up at the belt's speed as the
  front leaves; slugs leave a full buffer's zones together. Every item keeps
  its slot (it is drawn behind it by the time it waited; `Stream Extra
  Slots` covers the longest wait). Once the first buffer is full the
  stream's root runs at what it lets out: from `Switch Time` (when the
  slots then crossing the origin reach the full buffer) its slots are
  thinned to the Output % by Bresenham and the items numbered on, so owners
  and splits deal them without gaps; per-item times stay within one
  in-period of warehouse_common's chained switch (approved). The rank (FIFO
  order) is the item number when every slot passes the buffer, the owner's
  number when one owner's goods do, or the number after the route edges in
  front of it (`route_chain`'s running index); several owners AND a split
  in front of one buffer fall back to the item number (v1).
- v1 limits: one switch per stream (the first buffer to fill); a second
  buffer filling later on the same path backs its queue up the line.
- tests: tests/test_buffer_fifo.py (unit, against buffer_item_times and
  branch_of_item), tests/headless/test_buffer.py (fills and holds, departures,
  the thinned root, slugs), test_flow_publish K (a 40 % buffer and a divert
  after it: WC's resolve) and L (migration).
- **Panel (2.24.1, PM)**: Output % and time, never items an hour (round 8:
  no physics in the UI; Racks tests "no /h anywhere"): "Lets out 40 % of
  what arrives", "Full after 17 s, then holds 4" -- or "Full after 4 min
  (after scene end)" when `buffer_info` full_s is past the scene's end
  frame (`panels.buffer_fill_text`; seconds under a minute, hours from
  600 min). The /h line stays behind `SHOW_THROUGHPUT_PHYSICS`.

## Load ids, matched as warehouse_common spells them (2.24.2, WC 0.6.6)

A load id can be spelled more than one way: "pallet:EUR1:Plastic:1.0" and
"pallet:EUR1:Plastic:1" are the same load (warehouse_common's `load_id`
writes a pallet's height with %g). Racks builds `make_load("...:1.0")` as
"...:1", so 2.24.1, comparing ids as strings, missed Racks' object and made
its own placeholder (found by test_round6_w2 run with Racks enabled; rule 9).
Every load-id comparison now goes through `loads.same_load` /
`canonical_load_id` (WC 0.6.6): `public_api.find_load_object` (the Warehouse
Loads lookup behind set_line_item and `_load_object`), `pick_item.apply_port_load`
(a port's load found by its id when its object name finds nothing),
`stream.same_item`, and the dock record's "did the port's load change"
(`ports._changed_load`, the flow-signature branch of the dock sync). Our own
placeholder is named and recorded under the canonical id, one per load.

## Goods sized and published as they ride (2.23.4)

PM / Racks, 2026-10-15 (joint check 11, Racks' 60/40 in-feed render): a
pallet line carries EUR1 (wh_load: 0.8 m along travel, forward X); a 90
degree POP-UP divert sends 60 % to a branch at a crane in-feed. A pop-up
transfer does not turn the goods ("1200 in, 800 out", 2.18), so on the branch
the pallet runs 1.2 m along -- the length `populate_item_length` (pitch,
populations) already used there (`goods_turned`). Two places still used the
main's 0.8: the branch's published load (`ports._load_descriptor`), so
warehouse_common sized the branch 0.8 (0.200 against 0.294 at the crane's
cap), and the populate tree's `Item Length` (`populate_values`), so the
pallet overhung the in-feed by 0.19 m before it went. Now `Item Length` is
`populate_item_length` for every line carrying an item, and a line where the
goods ride sideways publishes them sideways (length and width traded,
forward axis X <-> Y) when the width is the larger side. A free end was
already clean (the front reaches the end, the item goes). Fork face first at
a crane in-feed off a 90 degree pop-up divert would take a turntable or a 45
degree divert (the goods turn with its branch). tests/headless/
test_goods_turned.py (it fails on 2.23.3: 0.8 / X published, 0.294 vs 0.200,
191.7 mm overhang); previews conveyor_goods_turned_handover_* and
conveyor_goods_free_end_*.

## An in-feed receives what a branch brings (2.23.3)

The joint suite's check 12 still failed on 2.23.2: its main carries the
placeholder totes, and `dock_line` gave the branch the crane in-feed's EUR1 --
an item nothing upstream brings, so the branch sorted for it and took
nothing (0 %, empty on screen, no arrivals). A line carrying its main's goods
(`ports.carries_upstream_goods`: stream.parent_of DIVERTER / CONTINUE) no
longer takes an in-port's load at its end, neither from `dock_line` nor from
the sync pass (`apply_port`); a line starting its own stream still does.
Files saved before may hold such an item on a branch: the ✕ next to the item
in its Populate panel clears it. tests/headless/test_arrivals_r22_4.py
parts P (an EUR1 main) and Q (a placeholder main).

## A branch carrying its stream's own load keeps its Share (2.23.2)

Found by Racks rendering a 60/40 in-feed (PM, 2026-10-15): `dock_line` gives a
line docked at a port that port's load (2.11.1), so a branch docked at a crane
in-feed carries an item -- the very load its main line carries. `tree_for`
took ANY branch with an item for one sorting by item (it took those owners'
goods whole: 100 %, its Share ignored) and `arrivals_record` refused every
branch with an item (`item != line`, always true). Now a branch routes by its
item only when the item SORTS -- some goods passing its divert are another
item (`takes != passing`); `stream.same_item` counts one object, or objects
with the same `wh_load` id, as one item; `LineStream.item_routed` marks the
sorting branches and arrivals_record skips only those.
tests/headless/test_arrivals_r22_4.py part P (EUR1, 60/40, dock_line end).

Also in 2.23.2:
- **A foreign change re-resolves the docked lines** (PM, Floorplan's R22 branch:
  "All Half Full" took door1 from population 0 to 0.5; line A kept publishing
  0). The dock record keeps `flow` = `ports.flow_signature(system, port)`: the
  port's population, population_in, speed_m_s, max_population, master,
  share and legacy rates, and the system record's own stream keys. A pass
  that finds it changed rebuilds the line (its stream and peers follow) and
  stores the new one; a dock stored before 2.23.2 just records it (no wave of
  rebuilds on load); 0 writes at rest. test_flow_publish part J (it fails
  with the check off: 0.0 / 0.0 against 0.5 / 0.25).
- **warehouse_common 0.6.4**: a port that says nothing is no source, a legacy
  stand-in takes the docked line's item, a sink's capacity_ph is its
  max_population -- what Conveyor's readers did already; `_port_graph`'s
  fallbacks now use WC's speed for them (the port's, else its surface speed,
  else the load kind's default via the port's, the system's or the line's
  load).

## A published population wins (R22.5, 2.23.1)

PM, 2026-10-15, found with Floorplan's R22 branch: a door published
population 0.5 at 0.2 m/s (about 424/h) and a stale `rate_ph` 16.5; the line
followed the 16.5. Now, as warehouse_common 0.6.3's build_graph (vendored):
- `model/port_io.rate_ph` / `capacity_ph`: the R22 `population` /
  `max_population` win when published -- even 0, a stopped source; the
  legacy `rate_ph` / `rate_in_ph` / `capacity_ph` stand in only without one.
- `flows._port_graph`: build_graph already stands a legacy rate in (at the
  port's speed, else `surface_speed_m_s`, else the load kind's default
  speed) when the port's load gives a length; Conveyor fills in only where
  no population is published and build_graph had no length (the line's item,
  the same speed rule). A port publishing neither leads nothing.
- WC 0.6.3 also marks a master capped when its own `max_population` clamps
  its slider, so check 11 accepts the slider it publishes (R22.3).
- `conveyor.set_line_flow` (population) / `set_line_rate` on a line a port
  leads: FINISHED as before, plus the INFO "<line> follows Rack · out0"
  (`public_api.follows_note`; its own Population is kept, the port's flow
  runs and is published). tests/headless/test_flow_publish.py part I.

## Simple flow panels, the state in effect (PM, 2.22.1)

A line carrying its master's goods (a branch, a takeaway: `parent_of` DIVERTER /
CONTINUE) shows its Populate box ticked and greyed with "goods from <root>" --
its own box no longer says what it carries. The master says why it is one,
"Master (first on the stream)" or "Master (pinned)"; the toggle reads "Pin as
master" / "Pinned" (no property split: the words are on the button) and is hidden
on a lone line. Tests (rule §2.10): test_omni and test_v24 save their scenes to
TMPDIR only; tests/test_test_hygiene.py fails on any save_as_mainfile /
save_mainfile in tests/ or tools/ whose path does not come from TMPDIR.

## Simple flow: Population, Speed, the master (round 8 B + C, 2.22)

Åsmund, 2026-10-15: "simpler sliders setting population amount and speed
amount on the populated objects ... the master populated object ... the
merged conveyors should be able to set the % of the master throughput".
Contract INTEROP.md §12 R22 / R22.1 / R22.2; maths: warehouse_common 0.6.1
`simple_flow` (vendored).
- **Settings** (props/line_settings.py): `population_pct` (0-100 %, default
  50, step 5, multi-edit), `flow_master` (Master), `share_pct` (a branch's
  Share OF THE MASTER, the old meaning of "% of the main"). `throughput_ph`,
  `populate_spacing_mm`, `populate_fill` and a feeder's Share stay in the
  file untouched (older versions read them) but no longer act.
- **Flows** (`operators/flows.py`): `resolve_group` builds the group's graph
  with build_graph's ids ("<line uuid>/line_in", one section per taken
  junction port by u_m, 1 mm boundaries; divert, merge and continue edges --
  a bypass gets both its divert and its re-join) and runs `simple_flow.
  resolve`. The master is the flagged line (by name), else the root; the
  group runs at its speed (v1: one speed per docked group; a feeder's own
  Speed is not used, the panel shows "from <master>"). Goods come in at the
  root and at every populated feeder; a branch's or takeaway's Population
  counts when it is the master. Shares: % of the master -> the LOCAL
  fraction at the split (share / the split section's share of the master,
  resolved again until stable); the master's own Share is local (a share of
  itself means nothing); a Route by item class = its class's part of the
  classes still passing; a branch with its own item = its owners' flow over
  what passes; a dead end (a transfer with nothing beyond) sends all to its
  branches. Caps: the slot grid's floor (item + clearance + a merge's lag, a
  right-angle stop's pitch, a pouch) and a rack in-feed / a throttling buffer
  scale every owner (`GroupFlow.cap_to`): silent, "Runs at 72 % (capped)".
- **The stream** (`operators/stream.tree_for`): owners = root + populated
  feeders; `tree.rates` = their flows x 3600 (for the dormant readers);
  pitch = speed / the group's flow (>= the floor); `Owner Split k` = the
  owners' cumulative flow shares. `owners_on(line, u)` = the owners on a
  line's own path just before u (a merge AT a split is not part of it:
  R22.1's one boundary -- goods merged at a junction never leave by its
  other face). Each line's `chain` = the splits its goods pass on their
  way to and along it (`path`: the parent's path up to its divert, its own
  divert edge, the feeders' own splits, its own; `onward`: past a merge or
  a bypass's re-join), each split's edges in simple_flow's split order with
  q = the edge's fraction of what is still undealt (the line's own continue,
  dealt last, is implicit), `Take` on the edge that is this line's way on.
- **Populate tree 29** (line trees roller 58, belt 55, chain 55, omni 28,
  pocket 27, pouch 5): every slot's item NUMBER k = wraps x slots - identity
  (the k-th item centre to cross the stream origin, item 0 at Stream Phase:
  simple_flow's numbering, unbounded); the owners deal the items in order
  by Bresenham (`slot_owner`), giving each item its number among its
  owner's; `route_chain` deals every split edge by edge exactly as
  `simple_flow.branch_of_item` (floor((i+1) q) > floor(i q), the number
  carried on: among the taken, or among those left; float32 with a 1e-4
  epsilon), a class edge by the item class; past an edge that took the item
  the other way (or a Take edge that did not) the item is not this line's.
  `Transfer k Rule` = the route edge whose goods a transfer lifts and stops
  (a transfer on a branch's way: that branch's edge; none on a line whose
  goods never pass it). So the same items leave at a divert in every
  add-on (tests/headless/test_simple_flow.py D: 25 % takes items 3, 7, 11
  ...). Owners at a merge: every owner's goods evenly over the grid (E: two
  equal feeders, the main's goods every second slot).
- **A bypass** (a line leaving a main at a diverter and merging back into
  the same main downstream, `stream.is_bypass`): a branch now, not a
  feeder. Its goods keep pace: `stretch` = (where its own path starts, the
  main's span to the re-join, its own length + the merge slide), the
  populate tree draws its own path stretched over that span (`Stretch
  From / Span / Length`), its rollers turn that much faster
  (`stream.line_speed`), and its goods merge back into the very slots they
  left; past the re-join they pass the main's splits like the main's.
- **Panels** (ui/panels.py, labels <= ~36 characters, the state in
  effect): the master shows Population and Speed, a follower
  `simple_flow.share_text` ("30 % of Main", "Stream of Main"), its
  Population in effect and "Speed 0.50 m/s, from Main"; a branch its Share
  of the master; a feeder its own Population; Master on every line;
  "Set by Racks" under an R6 rate. Throughput, rate read-outs, bottleneck
  and over-capacity alerts, the port row's "150 -> 56/h" and Add buffer
  before Rack are dormant (`panels.SHOW_THROUGHPUT_PHYSICS`). Flow markers
  tag "in · 50 %" from `conveyor_flow_pct` (written by the build: no
  stream maths per redraw).
- **R6**: `conveyor.set_line_rate` is a deprecated shim: the Population that
  carries the rate at the line's speed (`model/public_api.population_plan`;
  record `own_pct`); docking at a port copies its flow into Population.
- **Migration** (`model/flow_migration.py`, `flows.migrate`): a line without
  `conveyor_flow_migrated` gets, once, its owners' share of the old slot
  grid x (item length + 0.05) / the old pitch (Throughput at its speed, else
  Spacing / Fill); the build and the sync pass write it, `tree_for` reads the
  same value until then; new lines start migrated at 50 %.
- **Tests**: unit test_flow_migration, test_public_api (shim); headless
  test_simple_flow (pitch, rate, empty, branch_of_item, owners, master
  downstream, feeder speed, migration, shim, cap, bypass); the suites that
  set Throughput now set the Population that carries it.

## Goods wider than the line (PM, 2026-10-15, 2.21.1)

The 2.20 divert previews showed totes hanging over a branch's rails: a 90°
transfer keeps the goods' orientation, so the default 600 x 400 tote (long
side first on the main) crosses the default 500 mm branch with its 600 mm
side -- right for the real unit, which must be sized for it. build_line
measures, into `goods_across_mm` (`populate.OVERHANG_KEY`), how wide the
goods run across: `across_mm(sizes, yaw)` = max over the goods' kinds of
w |cos yaw| + a |sin yaw| (`goods_sizes_mm`: the item as laid on the line
it comes from, else the placeholder totes and cartons), over the line's own
points on pieces (a transfer's own deck is as wide as its faces: skipped),
and at the last continuation point of a feeder (its goods on the main). The
Populate panel compares with the widths at draw time
(`populate.overhang_notes`, 5 mm tolerance): "Goods 600 mm across, line
500 mm" and, where a yaw near 90° is the cause, "Sideways after the 90°
transfer"; a feeder: "Goods 600 mm across on Main" / "It is 500 mm; goods
ride sideways". Labels stay under ~36 characters (the panel's default width
cuts longer ones). Panel only, no records. tests/headless/
test_goods_overhang.py; previews conveyor_goods_wider_light / _dark.
warehouse_common 0.6.1 vendored (simple_flow: a crane rack's stream node
takes its first out port's item length).

## The stream graph, published (round 8 R22.1, 2.21)

Contract INTEROP.md §12 R22.1 (PM, 2026-10-15): every add-on builds the same
stream graph from records (warehouse_common 0.6.0 `simple_flow.build_graph`,
vendored), so line-to-line junctions became records, written by this add-on
only (R14). `operators/junction_ports.py`:
- **Ports on the main line** (`publish_line`): each TAKEN merge / divert
  face is `{"id": "j:<uuid>", "role": in | out, "kind": "point", position,
  heading_deg (the goods' direction at the face centre), width_m (the docked
  line's), u_m, "taken": true, "exclusive": true, level}`. `u_m` is the
  flow-path distance from `line_in` to the module's centre
  (`module_u_m`: `own_length_m` minus it on a reversed line), so both faces
  of one junction share it and the graph makes them one boundary. A free
  junction publishes nothing (no docking offer). A RAT's io faces keep their
  ids and gain `u_m` when taken. `docked_faces` checks each source name with
  `docked_junction`, so a copy's leftover name or a deleted line publishes
  no port.
- **The uuid**: made once per face (`face_uid`, ID properties
  `wh_junction_left` / `wh_junction_right` on the piece, unique within the
  line); `detect_junctions._choices` carries them through a re-fit, so a
  feeder sliding along keeps its port; `_remove_junction` clears them.
- **Links on the docked line** (`ports._entries` + `junction_links`):
  `system_id` (the main line's), `port`, `role` (in / out, io on a RAT
  face), `anchor` start (divert) / end (merge), `edge` divert | merge, and a
  divert's LOCAL `share`; a takeaway (`tail_continuation`) links the line's
  `line_out` with `edge` continue. The v1 `wh_port_link` dict is only ever a
  port dock. `refresh_links` no longer stops at "no port docks", and
  `_refresh_stream_peers` refreshes the group's links (compare first).
- **The share** (`stream.branch_share`, pure `model/split_shares.py`): what
  the animation does, as a local fraction: per owner, the route keys (exit
  portions with their widths, item classes, or one key) that reach the
  divert, minus every rule passed upstream; the branch takes its keys of
  its owners. A second 20 % branch after a 30 % one is 0.2 / 0.7; rules and
  merges at the same place are one split (same 1 mm boundary as the graph).
  A bypass (its end merges back) is a feeder in today's stream, so its
  Share % stands in; without one the link has no share (the remainder).
- **Older files**: lines without `conveyor_records_rev` 2 are republished
  once by the sync pass. tests/headless/test_r22_1_junctions.py feeds the
  published records into `build_graph` (a divert, a merge, a RAT with a
  branch and a feeder, a bypass, tail to head, a free face) and checks ids
  through rebuilds and a sliding feeder, deletion, the republish and 0
  writes at rest; tests/test_split_shares.py the shares.

## A stop at every sideways transfer (round 8 choice 3, 2.20)

Åsmund, 2026-10-15: stop-lift-transfer at EVERY sideways transfer, with the
2.18 warp and timings. `operators/stream._transfers` adds a stop for every
goods path that crosses a junction's face sideways:
- **Where**: a 90° pop-up merge or divert (`animated_transfer`; timings by
  `resolve_junction_tech`: BELT and POPUP wheels 0.2 + 0.3 s, CHAIN
  0.5 + 1.0 s) and the side faces of a RAT the line goes STRAIGHT through
  (BELT). A RAT
  the line turns on keeps its one corner stop: every item stops there
  already, whichever side it leaves by.
- **Divert** (outbound): the branch's goods (its owner and class mask)
  stop at `prefix_u + STOP_PAST_M` (0.1 mm past where the paths part, so
  the branch draws the standing item and it is drawn once), stand while
  lifted, then leave along the branch. Goods going straight on never stop.
- **Merge** (inbound): the feeder's goods (its owner bit) come in raised
  and are set down standing at their `entry_u` on the main line, then
  speed up again.
- `side_transfers` builds both, for pop-up junctions and RAT faces alike.
  `_rat_stop_techs` also counts RATs with lines on their side faces and
  pop-up junctions with a line docked, so the stream's pitch keeps length
  + width + lag and its extra slots cover the lag. Populate tree
  unchanged (28): only the per-transfer inputs. tests/headless/
  test_side_transfers.py: a pop-up divert, a straight-RAT branch and a
  pop-up merge each stand the full stand, lift or set down by the belt
  stroke, draw each item once and write nothing per frame.

## Simple flow, readers first (round 8 R22, 2.19)

Racks and Floorplan may publish `population` (0-1), `speed_m_s`,
`max_population` (sinks), `population_in` (io ports) and `master: true` on
ports, and `share` on links, instead of the rate keys, which became optional
legacy. Until the stream runs on warehouse_common 0.6's simple-flow maths,
`model/port_io` reads them into the flow the stream already understands:
`rate_ph` = the legacy key when above 0, else population x goods speed x
3600 / (load length + GAP_M 0.05 m, Åsmund's gap at 100 %); `capacity_ph`
the same from `max_population`; `goods_speed_m_s` = `speed_m_s`, else
`surface_speed_m_s`; `is_master`, `link_share` for later. The callers
(stream throttle, buffer AUTO out, flow tags, the port row, the eyedropper's
rate, the speed taken on a fresh dock) pass the line's item length and
speed for ports whose load has no length. No UI changed.

## Right-angle transfers: their sides and the stop (Åsmund, 2026-10-15, 2.18)

- **Widths** (`operators/rat_faces.py`, applied at the start of every build):
  a transfer that turns at the end of its line takes the takeaway's frame
  width (TAIL_KEY, New Line from End) on its exit side (`rat_face_left_mm` /
  `rat_face_right_mm`, flagged `rat_exit_from_tail` so only this module
  resets it when the takeaway goes, in the sync pass); a standalone unit
  (only RAT pieces) takes its feeder's width preset, else its takeaway's
  (RNA write inside `suspended_rebuild`, so it never spreads to selected
  lines). `neighbours_to_refresh` rebuilds the transfer when either
  neighbour's width changes (compare first: no loop). Docked faces were
  already handled by `detect_junctions._set_infeed`.
- **The stop** (`model/transfer_motion.py`, `geonodes/populate.stop_warp`,
  populate tree 28): per transfer, `Stop` (item-centre stream coordinate),
  `Hold` (stand in stream travel = v x (settle + lift)), `Turn` (the lift,
  v x lift), `Inbound` (reversed: set down standing) and a stream-wide
  `Transfer Ease` (v^2 / 2a). The warp: unchanged before c - a, speed
  falling linearly to 0 at c, standing `Hold`, speeding up, then 2a + Hold
  late; applied in flow order on the item's centre before it is mapped to
  the line, so every line of a stream (and a takeaway) shows the same item
  at the same place. The lift is timed on the coordinate before the warp
  (the last `Turn` of the stand) and set down on the one after it.
  `operators/stream.tree_for` keeps the pitch >= length + width + lag
  (`populate_item_footprint`) and adds `extra_slots(lag)` invisible slots so
  the late goods still reach the end. Nothing is written per frame (R5).
  Timings: BELT / POPUP settle 0.2 s, lift 0.3 s (Interroll RM 8731
  datasheet), 1.5 m/s^2; CHAIN (pallets) 0.5 s, 1.0 s, 0.5 m/s^2 (assumed:
  PM 9730 publishes a 30 mm stroke, no time). Pop-up junctions and the
  side faces of a straight transfer stop too since 2.20 (above).

## Floors without an implicit scene switch (R3.1, 2.17)

Contract amendment from the PM, 2026-10-14 (found by Racks while planning
multi-tier walkways: one marked deck switched every line in a scene without
a Floorplan building to "marked floors only"). `operators/floors.py`:
`floor_mark(obj)` is True / False / None; `_candidates` = the automatic
candidates (now also minus `wh_floor` false) updated with every `wh_floor`
true object, or only the latter with Scene `floors_marked_only` (default
off, `_rebuild_all`); the Floors collection still wins in build_line. The
operator `conveyor.mark_floor(mark='FLOOR' | 'NOT_FLOOR' | 'AUTO')` replaces
the old boolean `state`; it writes only on the user's own meshes and stamps
`conveyor_floor_mark` beside `wh_floor`, so a mark another add-on made (no
stamp) is shown and never changed. A marked deck hidden with the eye or
disabled in viewports still carries the legs (Racks' walkway helper:
tests/headless/test_floors_r31.py).

## Suite round 7: a line along points (R21, 2.16)

`bpy.ops.conveyor.new_line(kind="line", preset, points="<JSON [[x, y, z], ...]>", by)`
(signature fixed with the PM, 2026-10-13; location / heading_deg are ignored
with points). `model/route.plan_route` (pure, tests/test_route.py):
- **Corners**: a point turning 1° or more gets a flat curve tangent to both
  legs; smaller turns merge into one straight run, and a run whose merged
  points stray more than 5 cm from its line gets its worst point back as a
  corner. The curve takes the catalogue's default inside radius; a leg too
  short for the tangents at its ends shrinks the bigger of them through the
  smaller catalogue radii of the same system, else the path is refused. A
  corner that is not a whole degree keeps its exact angle on the piece
  (`curve_angle_exact`, read by `segment_curve_angle_deg`; any hand edit of
  the angle drops it), so the line still ends on the last point.
- **Heights**: curves are flat at their corner's height, so a run climbs
  between the curves at its ends. The build inserts a nose-over arc between
  two pitches, ADDING its length (model/segments.evaluate_chain); the
  planner fits each as a fillet: at a run's start the virtual vertex sits
  R·tan(θ/2) past the curve's end (fixed point in θ), interior vertices cut
  R·tan(Δθ/2) from both legs. A straight's rise is length·sin θ, which
  segments_from_settings turns back into the same Incline. The last run may
  end on a slope (the chain does not level out at its end).
- **Checks**: the type's incline limit (`loader.incline_limit_deg`, shared
  with the panel's alert: 0 = cannot climb), vertical legs, U-turns on one
  point, legs too short to climb; then the planned chain is evaluated and
  must end within 2 mm of the last point. Planning happens before the object
  exists, so a refusal (WARNING + CANCELLED) leaves nothing behind.
- **Build**: `create_line(..., fill=)` puts the pieces in before the first
  build (straights as ID-property writes: the 150 mm snap is for hand
  edits); `by` goes into `conveyor_layout_from` {"by", "points"} and the
  Line panel says "Laid out by Floorplan along N points"
  (`model/public_api.addon_name`, also used by the R6 rate note). No dock
  inside new_line: the normal sync rules apply, and `conveyor.dock_line`
  gives a guaranteed one.

## The warehouse library contract (v2, 2026-10-11)

The add-ons of this warehouse library (Racks, Conveyor, and the ones to
come: shuttle, QA station, mezzanine, floor-plan builder) talk through
custom properties only, never imports. The agreed text is mirrored
verbatim in `docs/INTEROP_CONTRACT_v2.md` (source of truth:
`_coordination/LIBRARY_CONTRACT_v2.md` beside the plugins). The Conveyor
side of it lives in `operators/ports.py` (docking, links, the line's own
`wh_system` / `wh_ports` / `wh_path`, the `wh_addons` entry),
`operators/pick_item.py` (loads), `props/scene_settings.py` (the shared
clock `wh_time_scale`) and `model/clock.py` (the hand-over phase maths).

## Round fourteen: edge cases of the symbiosis, the line as a system (2026-10-11 afternoon, v2.6)

The coordinating session's round-4 stress test (8 systems, 16 lines)
and the user's own report ("objects interfere with each other at the
merges") drove a rewrite of `operators/ports.py` and a fix in
`build_line`:

- **Duplicated lines collided.** Shift+D copies every ID property, so
  the copy of a feeder kept `continue_target` (and port docks): its full
  spline still ran onto the main line and it drew a second stream of
  goods there, through the originals. `_shed_borrowed_docks` runs first
  in every build: a copy (same `conveyor_uuid` as another line, its
  recorded name not its own) sheds continuation, branch, tail and port
  docks and the attach role; every line sheds junction keys whose junction
  no longer names it (`_drop_stale_docks`).
- **Two docks per line, by anchor**: `conveyor_port` is {"origin": …,
  "end": …}; `wh_port_links` is a JSON list (one entry per dock, contract
  §3: version, system_id, system, port, role, anchor start/end, rate_ph,
  requested_ph, by, line_id, phase_s/period_s on in-docks), `wh_port_link`
  the first entry for v1 readers. Docks resolve a system by `wh_system.id`
  first, name second.
- **Exclusive ports**: a second line within reach is not docked; its
  panel reads "aisle0_out is taken by Conveyor Line" with a Take over
  button (`conveyor.port_take_over`); a scaled system is skipped with
  "<system> is scaled; sizes are 1:1 metres".
- **Systems that move or change** (`sync_links`, every handler pass,
  keyed on each system's matrix and raw `wh_ports`): origin docks follow
  the port, end docks re-aim within 1 m, beyond that -- or when the port
  is gone -- the dock is released and the line's panel says "lost Pallet
  Rack · aisle0_in (2.3 m away)" until re-docked (lines with such a note
  re-sync whenever a system changes) or dismissed.
- **Near misses**: a free end within 2 m of a free port of the right role
  gets "0.9 m from Pallet Rack · aisle0_out — move within 0.6 m, or
  [Dock]" (`conveyor.port_dock`).
- **In-ports are sinks**: effective rate = min(Throughput, capacity_ph)
  through the throttle (index -2), the panel "Pallet Rack takes 52/h,
  this line brings 300/h" and "Add buffer before Pallet Rack"
  (`conveyor.add_buffer_before_port`: a 6 m buffer, Out Auto, cut from
  the last straight so the end stays on the port).
- **Load creation deferred**: `warehouse.make_load` is never called from
  the handler (it re-entered itself through our sync); a timer makes the
  load and re-syncs the line.
- **The line as a system** (contract v2 §1, §2, §6): `publish_line` at
  the end of every build writes `wh_system` (uuid kept through renames,
  a copy gets a new one; footprint = the swept frame; height above the
  floor), `wh_ports` with `line_in` at the flow start and `line_out` at
  the flow end (width, surface, speed, load, delivered rate, capacity,
  handover, taken, revision, phase/period at the end) and `wh_path` (the
  centreline, <= 1 m spacing); `wh_addons` gets our entry from a timer
  after enable and on load_post; `conveyor.new_line` takes use_args /
  location / heading_deg for a floor-plan builder.

## Round thirteen: rack ports, the throughput correction, the buffer's out rate (2026-10-11, v2.6)

Asked by the user through the coordinating session (Racks add-on): lines
snap to the rack's crane in/out conveyors; the buffer holds goods and
stacks from the back with an out logic; "throughput and motion do not
seem to work" (the correction below).

**Rack ports** (`operators/ports.py`): a rack system publishes `wh_ports`
(JSON, local frame: id, role in/out, kind point/face, position,
heading_deg in this add-on's convention, width_m, load {id, object,
forward_axis, ...}, rate_ph, capacity_ph, handover, revision). `sync_port`
runs before the origin attach in `sync_feeder`: a forward line's origin
within max(Dock Distance, 0.15 m) of an "out" port is placed on it
(`_place_origin`, port heading), a reversed line's origin on an "in"
port (body away -- Racks' own "Dock a Line Here" pose); `sync_port_end`
turns a forward line about its end onto an "in" port. `apply_port` sets
the width (`set_width`: a catalogue width or Custom), and through
`pick_item.apply_port_load` the load object (the rack's `make_load`
operator when missing), the forward axis and the throughput when the line
had none. The line writes `wh_port_link` {system, port, role, rate_ph =
line_load_ph, by = "conveyor_system"}, refreshed at the end of every
`build_line` (`refresh_link`) and removed by `release_port` when the line
leaves (or Docking is turned off); Racks' timer link (by =
"warehouse_racks") yields to it. `sync_links` in the depsgraph handler
drops a dock whose system or port is gone and re-applies a load whose
revision or id changed. The goods start at the port's handover point:
`route_values` raises `Prefix` to `start_offset_m` for a line starting on
an "out" port. New Line at Cursor on a port starts the line there
(`port_at`: out first). The Line section shows the dock (`draw_port`) and
alerts when a line into an "in" port carries more than its capacity_ph.
Not yet verified live (the bridge was down).

**The buffer's out rate** (`buffer_out_mode` Auto / Set, `buffer_out_ph`;
`operators/buffers.out_rate`): Auto is what the next machine downstream
on the line takes -- the next junction's technology rate, an inline
module's rate (lift, spiral, ARB, wrapper, RAT), the capacity_ph of the
rack the line feeds -- else the in rate. A buffer whose out rate is below
the stream's in rate holds the source back: `tree_for` caps the group's
effective rate (`tree.effective_ph`, `tree.throttle`) so the goods move at
the out rate with wider gaps, the buffer runs full (the stepping queue
holds nearly all its zones at the sparser pitch), and the buffer panel
reads "In 100/h, Out 60/h (Pallet Rack): holds 4, full after 6 min, backs
up 7.5 m" with the alert "Goods back up: the line is held to 60/h"
(`model/buffer_queue.fill_time_min`, `tree.buffer_info`). The requested
rate stays in every read-out. Agreed with the coordinating session: a
growing queue cannot be periodic (the stream is a closed form of index
and time), so the honest picture is the steady state after the fill --
the buffer full and the queue backing up along the line upstream of it,
the source throttled. The throttling buffer's stepping queue therefore
takes its zones over the module PLUS the straights and curves back to
the previous module (`run_before` in `tree_for`): the user sees the line
behind a too-small buffer packed and stepping.

**Slug release** (`buffer_release` Singulated / Slug). A slug is the whole
queue leaving together, nose to tail, then the buffer filling again --
periodic, so it fits the stream: `Buffer k Slug` = K (Populate tree v26,
every line tree bumped for the new input), `Tail` = the FRONT stop. Item
q = K - 1 - (identity mod K) rolls to its place q pitches behind the stop,
stands until the first item has waited (K - 1)(S - p) (the last one has
arrived), then the slug moves off as a block; the next slug's first item
reaches the stop exactly as the block clears it
(`model/buffer_queue.displayed_slug`, `slug_wait`, tests). K is the
largest divisor of the stream's slot count that the queue can hold
(`slug_size`), so the pattern repeats cleanly round the wrap; the stream
gets K - 1 extra slots. A slug leaves the slot grid, so a merge
downstream would collide: the panel alerts with the merging line's name
(`buffers.merge_downstream`). Not yet verified live.

**One clock for both add-ons.** The crane animation runs on a compressed
clock (3-4x), the stream in real time, so 50/h on the rack showed 150-200
pallets per scene hour against the line's 50. `scene["wh_time_scale"]`
(operation seconds per scene second, 1 = real time) is the one clock:
`props/scene_settings.time_scale` mirrors it as a Scene-panel field
(get/set on the Scene ID property), `_push_inputs` pushes Speed x the
clock into the trees (goods, belts and rollers move faster on screen; the
Speed field, the pitch and every rate stay real), and the depsgraph
handler re-pushes every line's speed when the value changes under us
(`push_time_scale`: the Racks field). A port's `surface_speed_m_s` sets
the line's Speed on a fresh dock (no speed step at the hand-over).

**The pitch the tree really uses.** The tree fills the wrap with a whole
number of slots and widens the pitch to fit, so an 18 m line at a 15 m
pitch ran 18 m slots while the Python side computed waits and slugs with
15 -- a slug's release test fired at once and the item left the line
(coordinating session's census). `tree_for` now rounds the wrap UP to
whole pitches (`tree.length`; the slots beyond the lines are never
drawn) and recomputes the pitch the way the tree does (`tree.actual_spacing`,
= the target pitch at Fill 1); every buffer figure, the slug wait, the
opening phase, the carried rate and the panel's pitch read it. A slug is
every zone of its buffer; the stream is padded with invisible slots until
the slug divides the slot count (`extra_slots`), and the opening phase
uses floor, so frame 0 shows the queue standing complete but one, leaving
the moment the last arrives. Replicated offline before the live run.

**The wrap goes to every line.** `route_values` pushed "Stream Length"
(the wrap), Spacing, Fill and Slot Length only for shared groups; a single
line wrapped over its own curve length and the tree widened the pitch to
fit (an 18 m line at a 16.2 m pitch drew 17.6 m slots), so the hand-over
lock with a rack drifted 13 frames per pallet and every slug figure was
off. They are pushed for every populated line now: the drawn pitch is
exactly `tree.spacing` whatever the line's length, the wrap a whole
number of pitches, the extra slots invisible.

**Out-port cap and the hand-over phase (R4).** A root line on a rack's
"out" port is throttled to the port's capacity_ph through the buffer's
throttle (`tree.throttle` index -1 = the port): "Pallet Rack delivers 55
of 100/h". `model/clock.py`: operation time runs from frame_start at
`wh_time_scale`; a line on a linked out port sets the tree's "Stream
Phase" (scene seconds, Populate v27) so a slot centre crosses the port at
the rack's phase_s + k period_s (`ports.out_port_phase`); a line ending at
an in port writes phase_s and period_s of its own slot centres crossing
the port into its link (`ports.in_port_crossings`, refreshed on every
rebuild). Links carry rate_ph = delivered and requested_ph = headline.

## Correction (2026-10-11): the throughput sets the gap, not the speed

Round eleven's "throughput sets the speed" was wrong for every line below
nose-to-tail flow: a 100/h pallet line with Throughput 100 crawled at
0.03 m/s (100 × 1.03 m / 3600) -- "throughput and motion do not seem to
work" (user, through the coordinating session). A conveyor runs at its
design speed and the rate sets the GAP: `tree.speed` is the Speed field
again, `tree.spacing` = max(min pitch, v × 3600 / Q) with Throughput set
(the 2.5 rule) and the Placement spacing without, `tree.min_spacing`
holds the floor. The planner's formula survives only as the alert: when
the floor is hit the line stays at its speed, saturated, and the panel
reads "Carries 1,836/h at 0.50 m/s; 12,000/h needs 3.27 m/s or 7 lanes"
(`carried_ph`, `required_speed_m_s`); every rate read-out keeps the
REQUESTED rate so the bottleneck shows on the Racks side too. The speed
is never raised behind the user's back.

## Round eleven: goods keep their orientation across lines; throughput sets the speed; origins at junction faces (2026-10-10, v2.6)

User: the tote "rotates 90 degrees because it follows the curve's normals
in a fillet type way -- right on a merge junction, wrong on a RAT, where
it is lifted by the belts"; throughput and % "not according to real
calculations, research it"; "the merge junction is not scaling to the
width of the merged module"; "study the file I have open and fix errors".

**Orientation across lines.** Within one line a right-angle transfer
already keeps the goods unturned: `model/segments.py` turns the heading
by 90° at the corner and takes the same 90° off the item's `yaw_offset`.
The handover to ANOTHER line lost it: a branch's or continuation's prefix
(the parent's path copied in front of its own, operators/detect_junctions
`prefix_for`) carried `yaw_offset` 0 on every parent point, and a
continuation's own body started at yaw 0 (`_sync_tail` passed `keep` 0),
so goods turned with the heading at the parent's RAT corner and again at
the handover. The parent's per-point `yaw_offset` is now read back from
its spine (`_spine_yaw`, flow-ordered by `_flow_yaw`, sampled piecewise
constant by `_yaw_at`); every prefix point carries it (7th tuple element,
`model/spine.write_spine` already stored one), `_attach_branch` adds the
parent's yaw at the divert to the branch's `keep`, and `_sync_tail`
starts the continuation at the parent's final yaw. Verified on ZZ_RAT →
ZZ_RATNext: the same yaw on every item over 12 sampled frames, through
the corner and the handover. Angled merges still turn the goods onto the
main (the wedge aligns them), as asked.

**Throughput sets the speed.** The planner's relation is items/h =
3600 × v / (item length + gap); sizing a line goes the other way: the
required throughput at the chosen pitch gives the speed, v = Q × pitch /
3600 (Industrial Monitor Direct's conveyor capacity / belt speed notes,
Cliff Holste's Supply Chain Digest columns on merge and sorter rates,
the roller-conveyor throughput guides all state the same formula). Until
now the group derived the PITCH from a fixed speed. `model/throughput.py`
(pure, tested) holds the formula; `tree_for` sets `tree.speed` from the
total throughput over the pitch (the Placement spacing, floored at the
item plus the merge clearance plus any continuation lag), `group_speed`
returns it, so rollers, belts and goods on every line of the group run at
it. The Speed field only rules while Throughput is 0. Panel: "Speed 3.26
m/s, set by the throughput", "12,000/h × 0.98 m pitch = 3.26 m/s" and one
alert with advice when that speed is above the type's typical (lower the
throughput or split the flow). Verified in the user's file: 12,000/h over
0.98 m = 3.263 m/s, and the instances step 0.136 m per frame at 24 fps on
the main line and both feeders.

**His file (Conveyor Test 2.7).** Two lines made with the + on the faces
of a manual "Merge 60° LR" (1200 mm and 500 mm wide) had never attached;
the junction stayed at its default 540 mm. Cause: his Dock Distance is
0.1 m and `attach_candidate` accepted an origin only within the Dock
Distance of the main's EDGE -- but the face centre of an angled merge
sits 0.75 m (540 mm infeed) to 0.93 m (1240 mm) from the centreline of a
1200 mm line, far outside half the width plus 0.1. Three fixes:
`attach_candidate` accepts an origin at a line's junction regardless of
the Dock Distance (`_near_junction`: within the junction's footprint
along the main and no further out than its faces plus `FACE_TOL_M`);
`_sync_origin` matches a free / manual junction by that footprint, not
only by a 0.3 m radius round the face centre -- the face MOVES when the
junction widens for the line on its other side, which orphaned the second
feeder with "needs a level straight"; and a two-sided junction takes the
widest of its two lines as its infeed (`merge_infeed_mm` = max), then
snaps both origins onto the new faces. Result in his file: both feeders
attached (origins 0.0000 m off their faces), infeed 1240 mm, each brings
in 33 % (4,000/h) of the 12,000/h, and re-syncing either keeps the other.
Not changed: 12,000/h on a 1 m/s roller line is his number; the panel
now tells him it needs 3.26 m/s.

**Then the frame census of his file** (36 frames, every item of every
line: steps, doubles, handovers, yaw) showed the two 90° branches drawing
a tote at 178° for one frame right after the handover and sliding it
DIAGONALLY to their face. Two bugs, both only on a reversed main:
(1) `_attach_branch` took the main's flow heading from `_flow_spine`
(already turned round on a reversed line) and added another half turn,
so the branch's kept yaw was +90° instead of −90°: the item was unturned
mod 180° on both sides of the corner but the heading and yaw attributes,
interpolated across the corner segment, swept it through half a turn in
one frame -- the user's "rotates ... in a fillet type way". (2) The
branches' `branch_from` arcs were stale by 0.85 m: the flow arcs of a
reversed main are measured from its END, and the merge junction growing
to 1240 mm had pushed the end out; `_refresh_docked_feeders` rebuilt the
branches with the old arc, so the slide started 0.85 m before the divert
and ran diagonally to the face. The refresh now recomputes every docked
line's arc (`_attach_branch` / `_attach_continuation`, which rebuild only
when something changed) before rebuilding it. After both: slides 0.62 m
straight across, every item on both branches at 90°, handovers at the
divert centre with the same yaw on both sides, no doubles.

**Takeaways follow the end.** Making the refresh re-read a continuation's
handover arc exposed a third stale-arc case: a line carrying another's
goods on (`conveyor_tail_target`) stayed put when its parent's end moved
(a piece lengthened), lost the continuation and -- its start now beside
the parent's body instead of at its end -- was grabbed by the origin
attach as a 90° feeder, with a merge junction cut into the parent.
`follow_tail` now keeps such a line's start at the parent's end whenever
the parent moves (`_on_depsgraph_update`, `_follow_dependents`) or is
rebuilt (`_refresh_docked_feeders`), keeping its own heading; `_sync_tail`
then re-reads the arc. Verified: parent +0.5 m and back, parent moved
0.3 m and back -- the takeaway rides along, keeps carrying on, items at
the same yaw.

## Round ten: far-end docks that slide to fit; the reverse / throughput matrix (2026-10-10, v2.6)

User: "divert not auto-updating to the merged conveyor in regards to width
on the module"; "something off with the reversing, throughput, % of
throughput and directions when populated -- test all use-cases".

**Width.** Every dock path was exercised with the feeder's width changed
afterwards: origin attach (45°), the junction's + (manual), a manual Merge
piece aimed at, far-end 90°, a real diverter (Goods out), all four 45°
transfer technologies, a custom width -- the junction's infeed and
footprint followed every time (540 → 1240 → 690 mm). What did NOT work:
`_sync` and `_sync_branch` (a line docking by its far end) inserted the
junction with `_insert_junction`, which needs the whole module on ONE
straight piece. A line built from 3 m pieces, or a main line whose
straight another junction already split, has piece joints everywhere; a
feeder aimed near one never docked ("junction does not fit"), and a
widened junction that no longer fitted in its piece was removed, the
feeder left undocked. Both paths now use `_insert_junction_fit` (slides
up to `MAX_SLIDE_M`, like the origin attach) and move the line's flow end
onto the slid face (`_module_face_world`); a pinned line (origin attached
elsewhere) cannot move and keeps the strict insert. A failure now leaves
an attach note ("No room on X for the 90° junction near the end").

**No goods on a switched line.** User's picture: a 90° branch, reversed,
"Branch of Conveyor Line", not one item on it. Reproduced by flipping a
line's role back and forth (Goods in / Goods out, or the Reverse toggle):
`continuation_for` stores the slide of a 90° merge as `continue_extra_m`
and never reset it, `_clear_continuation` did not delete it, and
`tree_for` holds the group's spacing above every member's extra
(`lag`) -- so a line that had once been a merge kept 7.8 m of it as a
branch and the whole group was spaced 8.4 m apart. Both now reset it;
the group's spacing is back to the throughput's pitch.

**The jump at the divert** (user's file, frames 302 → 303: a tote leaps
from the main line to the branch). Tracked both lines' instances per
frame: at 302 the main still drew the tote 0.26 m PAST the divert centre
(lifted on the belts), at 303 the branch drew it 0.3 m INTO its sideways
slide -- a 0.4 m jump. `past_prefix` (the branch draws from `Prefix` on)
and `left_here` (the main hides a routed slot past `Route At`) compared
the slot's START coordinate `u`, while both paths are sampled at the item
CENTRE (`u + half a slot`) and part exactly at the divert centre
(`branch_from` = the face centre's arc): the handover happened half a
slot after the paths had parted. Both now compare `center_u`. The
continuation's handover margin follows (Prefix = the parent's end minus
half an item, the parent stops when the item's front reaches its end).
Populate v25; library regenerated.

**The matrix** (ZZ_RM group: main 1,200/h; origin feeder 30 %, origin
branch 25 %, far-end feeder 20 %; the goods' velocity measured on each
line's own body against its flow direction): forward -- roles MERGE /
DIVERTER / MERGE, rates [600, 240, 360], branch 300/h, every line's goods
+0.50 m/s along its flow; main reversed -- the origin feeder becomes a
DIVERTER (reverse off) and the branch a MERGE (reverse on), rates
recomputed from the same percentages, goods still +0.50 along every flow;
forward again -- as before; far-end feeder reversed -- becomes a Divert
90° taking its 20 %; throughput 2,400/h -- spacing 0.75 m, shares scale
(720 / 600). No inconsistency found in roles, rates, read-outs or motion.

## Round nine: a line that starts where another ends carries its goods on (2026-10-10, v2.6)

User: "the Pieces list belongs right under the top part"; "the underside of
the RATs looks horrendous, remove the blocks"; "the RAT animation when
populated does not move in a 90 degree turn".

**Pieces** sub-panel: `bl_order 0`, right under the keys, Type and Width.

**Underside.** `transfer_parts._drive_box` (an Interroll-style drive /
lift box with two hanger plates and a motor block) hung under every pop-up
transfer: RAT, belt, chain and wheel junctions. From below it read as grey
blocks. Gone from all of them; only the high-performance divert keeps its
cassette body. The unit tests expect no Links-coloured box under a RAT.

**The 90 degree turn.** Tracked again: the RAT's own path is a clean L.
What the user builds, though, is the README's own recipe -- the RAT as the
line's last piece, then **New Line from End** for the takeaway conveyor --
and that second line was a separate stream: the goods vanished at the
transfer's edge (a line stops drawing a slot when the item's front reaches
its end) and the new line showed its own, unrelated goods 0.6 m further
on. Now a line whose origin sits within 8 cm of another line's end, pointing
on within 15°, neither reversed nor docked on a junction, **carries that
line's goods on** (`detect_junctions.tail_continuation`, stream kind
'CONTINUE'): `_sync_tail` gives it the parent's whole path as its
item-path prefix (the branch prefix machinery, `prefix_for` with no blend,
marked by `conveyor_tail_target` so `_drop_stale_docks` leaves it alone),
so its stream coordinates are the parent's; in `tree_for` it is a child
with the parent's offset, a mask of everything that reaches the parent's
end, fraction 1, and a `Prefix` of the parent's end minus the handover
margin (half a slot + half an item: exactly where the parent stops
drawing), so one line hands the item to the next in place. It inherits
the root's item and speed like any docked line; the panel says "Carries
on from ZZ_RAT", the main lists it ("ZZ_RATNext carries on from ZZ_RAT ·
1,200/h"), the overlay tags it "Carries on". A parent rebuild rebuilds its
continuations (`_refresh_docked_feeders`). Verified: 70 frames across the
corner and the edge, no jump, no double drawing.

## Round eight: the RAT sets down at the deck edge, buffers that queue (2026-10-09, v2.6)

User: "the RAT bugs a bit in the animation, it looks horrible"; "the buffer
conveyor is just standing still -- bins should stack up and go out, make
it realistic".

**RAT.** Tracked frame by frame (position, height, yaw of every item
within 2 m of the corner, 36 frames, forward / exit right / reversed /
eyedropped item): the path is continuous and the item never turns, but
the transfer window ran to `centre + width/2 + half a slot`, so the item
stayed 16 mm up (on belts that are not there) for 0.3 m over the takeaway
conveyor's rollers and then dropped. `_transfers` now ends the window at
`centre + width/2 - ramp`: the item (and the belts, `Lift k`) are down
exactly when its centre reaches the deck's edge; reversed, it is lifted
over the first `ramp` of the deck. The second thing in the frames: a
600 x 400 tote leaves a 500 mm line with its 600 mm side ACROSS (a RAT
does not turn the goods) and overhangs both fences. That is real-world
correct, so the strip and Details of a RAT piece say "Goods run 600 mm
across after the transfer: widen the line (500 mm)"
(`_rat_width_alert`).

**Buffers.** The buffer used to draw a STATIC queue (`queue_branch`, the
populate group at speed 0 over the queue span) and HIDE the moving goods
inside the zone, which teleported them from its start to its end. Now
the buffer is a stepping queue inside the one parametric stream
(`model/buffer_queue.py`, unit-tested; `geonodes/populate.buffered_position`):
an item rolls in, stops at the last zone's stop, waits, moves one zone
(at the belt's speed) at every step and stands the rest of the period,
leaves at the belt's speed. The delay is a WHOLE number of slots:

    m = floor(K (1 - p / S)), K_eff = ceil(m / (1 - p / S)), w = m S - (K_eff - 1)(S - p)

(K zones of pitch p = item + gap, items S apart; w is the first wait,
in (0, S - p] so the zone ahead is free as the next item arrives), so
downstream the stream is the SAME slot grid, just m slots late -- merges,
diverters, transfers and forks further on keep working. Two consequences,
both in the trees: the stream has `Stream Extra Slots` (the most slots
any path's buffers hold back) more slots and wraps that much later, so
the tail of the line stays full; and a slot's IDENTITY (owner, class,
route key: the seeded picks) is `index + Identity Shift`, a line's shift
being minus the slots the buffers ahead of its goods hold back
(`LineStream.identity_shift`, modulo the slot count) -- so a line that
merges in downstream of a buffer fills exactly the gaps the delayed goods
leave (two items at the same displayed slot always resolve the same
identity: both have the same buffers still ahead). The belts' `Lift k`
outputs are now an Attribute Statistic (max over the slots) of the
per-slot window, so they follow the goods wherever the buffers put them.
`route_values` pushes `Buffer k Tail / Wait / Pitch / Zones` (tail = the
slot coordinate of the last zone's stop: the front item's front one gap
before the blade, `Queue Pitch` still sizes the zones and their
photo-eyes); `Buffer From / To`, `Queue Span / Offset` and the static
queue are gone. Verified: 4 zones, 2 slots held back, first wait 0.75 m;
items never closer than the pitch, standing ~1/3 of the time, the queue
stepping as one, downstream gaps back at 1.50 m. Populate v24, line
trees roller 52 / belt-chain 49 / omni 22 / pocket 21; library
regenerated.

## Round seven: feeders join the stream, in / out, growing backwards (2026-10-09, v2.6)

User: "we should be able to add conveyors from the start too and go
backwards"; "the merging and throughput does not seem to work right";
"the user should be able to set the merged conveyor to out or in";
"the main conveyor sets the total throughput, and from there the
percentage that goes to a line merged to it".

**Why merging looked broken.** `tree_for` counts a docked feeder as a
source only when ITS `populate` is on, and nothing switched it on except
`_link_goods_on_attach` at attach time -- which only acts when the main
line is already populated. Dock first, populate the main later (the
natural order), and the feeder stayed empty, its Share ignored, its panel
reading "Brings in 0%". Now `_on_populate_changed` switches on every line
feeding into the one being populated (`detect_junctions.feeders_of`,
recursive), and `_attach_continuation` links the goods for far-end docks
as well as origin docks. A branch's Share field was also disabled
(`sub.enabled = settings.populate`) although a branch takes its share
without a Populate of its own: enabled when docked, and its rates line
shows too.

**In / out is a choice.** The Line section of an attached line draws two
buttons, Goods in / Goods out (`conveyor.junction_set` with the new
`role` property; `set_junction` swings the line to the mirrored angle
below 90°, at 90° only the flow flips). The pose still decides the role
at the FIRST attach. The share field reads "Brings in" / "Takes out", the
docked line's read-out "Brings in 30% of ZZ_M's 1,200/h · 360/h", and
the main line lists every docked line: "ZZ_F brings in 30% · 360/h",
"ZZ_B takes out 25% · 300/h" (instead of "Split 70% / 30%"). A branch's
percentage is of the MAIN line's throughput, wherever the branch leaves:
`carve` turns it into a slice of the route-key range equal to those
items per hour over the owner rates passing its diverter
(`passing_rates`), so 25 % reads 25 % and 300/h before or after a feeder
merges in (it used to be 25 % of what passed there: "18 %" on the panel
for a typed 25). A branch asking for more than passes takes all of it and
the panel says "Only 840/h pass its diverter". The rates are therefore
computed before the share routing in `tree_for`.

**The merged line's goods are the main line's goods.** Each line's
modifier instanced ITS OWN item (`_own_populate_values`): a feeder without
an eyedropped item showed placeholder totes that turned into the main's
item at the junction, and its rollers spun at its own Speed while the
goods crossed at the group's. Now a docked line without an item of its own
takes the root's item values (`route_values`, feeders as well as branches;
`stream.effective_item` for the item length and the by-item routing) and
every docked line runs at the root's speed, rollers and goods alike
(`stream.group_speed` feeds the modifier's `Speed`; the panel shows the
speed dim, "from ZZ_M"). The flow controls moved under Populate with the
throughput and the percentages (user: "the line direction should be
controlled under Populate"): Forward / Reverse on a free line, Goods in /
Goods out on an attached one; the Line section keeps the junction chooser.

**Growing backwards.** `conveyor_line.grow_at` (End / Start, the
segmented control beside "Add at" over the keys; the + before the line's
start sets Start, the + past its end sets End -- `piece_palette.at_start`).
With Start, `segment_add` prepends (`_prepend`): the piece goes to index 0
and the build's START ANCHOR moves the object so that the new piece ENDS
where the line used to start. The anchor is general: `build_line` stores
the local end pose of piece 0 after every build (`START_ANCHOR_KEY`) and,
in Start mode, `_keep_start_anchor` re-places the object whenever that
end moved (a prepended piece, piece 0's length or angle edited) --
`model/segments.reanchor_pose`, unit-tested -- so everything from the
second piece on stays exactly where it is; `_remember_matrix` keeps the
depsgraph handler from reading it as a user move, and `_resync_docked`
re-syncs the lines docked on it (their arcs along it changed). In End
mode the origin stays and the rest follows, as before. A line whose
origin sits on a junction cannot grow backwards (its start IS the face):
the operator says so and the start + is hidden. `adds_piece` replaces
`is_end_selected`: index -1 adds, the last row adds (End), the first row
adds (Start), anything else replaces.

## Round six: forks inside the tower, draw-safe read-outs, the self-test (2026-10-08, v2.6)

User: "the forks are still a bit buggy and have some cubes there; test the
plugin yourself for visual bugs, logical bugs and simplicity".

**The cubes** were the leveller trolleys: a 0.12 x 0.18 x 0.16 m block
instanced at every fork, half of it proud of the column's face beside the
posts. The real trolley rides inside the column, so none is drawn now;
only the fork shows (tines on a crossbar). The fork has **6 tines** instead
of the unit's 8: with the legs 675 mm apart in a 1,071 mm column, 8-tine
forks (535 mm) overhang the column by 70 mm each side, which read as
blocks beside the posts from behind (`LIFT_TINE_N`, `lift_parts.TINE_N`;
the crossbar is `n * pitch - 0.07`). The opening between the posts is
0.9 m wide (was 0.66 m: the legs sat on its edges) and runs past the apex
forks' crossbars.

**Under the floor.** The loop's bottom turn is 0.36 m under the infeed
and the column posts 0.56 m (`lift_parts.UNDER_BED`); a line laid on the
floor (z 0, the default cursor) had forks underground. The fork stage
drops points below `floor_below + 0.03` (`separate_geometry` on the
instance points) and the panel -- the always-visible strip as well as
Details -- says "Raise the line 0.56 m" (`_lift_floor_alert`, from
`build_line.segment_frames_for`). A new lift is 3 m tall
(`LIFT_DEFAULT_RISE_MM`): added from the library it used to be 0 m, built
0.3 m and listed as 0.00 m.

**Seam jump.** The grid-to-loop mapping stretched the return leg by
`(loop - loaded) / (grid - loaded)`; a low lift with a long slot left no
return leg after the half-slot margins (denominator clamped to 1 mm):
the forks teleported across the seam. The margins are now trimmed so at
least one fork pitch of return leg remains (`room = grid - fork pitch -
(drop - pick)`), and the denominator never drops below half a fork pitch.
Verified: 15 forks constant over 20 frames, max step 21.1 mm/frame against
20.8 expected.

**Draw-safe read-outs.** `segments_from_settings` wrote each lift's and
junction's fitted footprint back into `seg["length_mm"]`; Blender forbids
ID writes during a panel or gizmo draw, so every read-out that evaluates
the line (rates, fork count, split line, the new floor alert)
silently vanished on any line with a lift or a junction until something
rebuilt it and refilled `tree_for`'s cache. `_store_length` writes only
when the value changed and swallows the draw-context error.

**Self-test** (scripted user flow through the operators, fake-layout
draws of every panel and gallery in 15 selection states, instance census
per frame). Fixed: `conveyor.new_line` / `new_line_from_end` used
`context.selected_objects`, which only exists with a screen context (a
script or timer got an AttributeError after the line was created);
`is_end_selected` read index -1 ("nothing selected", e.g. after a click on
empty space) as "replace piece 0" and the keys then replaced the LAST
piece through Python's negative index; Duplicate copied a stale reference
-- `segments[i]` taken before `segments.add()` reallocates the collection
-- so a copied spiral came out as a straight or lost its turns, and the
copy list missed every newer field: `segment_values` snapshots all
writable RNA properties first, `apply_segment_values` writes them (kind
first, rise/length last). Dimension figures of pieces too short on screen
(< 48 px, or shorter than their own label) are left out unless the piece
is selected, so a zoomed-out line is not a pile of labels
(`MIN_FIGURE_PX`, `LABEL_OVER_CHORD`). Line trees roller 51 / belt-chain
48 / omni 21 / pocket 20; library regenerated (the stale-tree path appends
from it in 0.7 s).

## Shipped node trees, galleries, catalogue numbers (2026-10-08, v2.6)

**Performance** (user: the first "New line" took too long). Measured on
5.2: building the roller line tree 12.1 s (1607 nodes), the populate group
5.2 s, the frame 0.1 s; `build_line` on an existing line 0.12 s, an edit
end to end 0.18 s. So the only slow thing was node-by-node construction
through the Python API, once per tree per file (and after every version
bump). `geonodes/library.py` + `geonodes/library/conveyor_nodes.blend`
(1.9 MB, written by `tools/build_tree_library.py` from the builders, with
`conveyor_nodes.json` listing the TREE_VERSIONs): `get_or_create_tree`
asks the library first and `build_line._apply_modifier`'s stale path
appends the whole wanted set in one `bpy.data.libraries.load`. The
library is used only when it ships EXACTLY the code's versions, as a set
(line trees link the shipped Populate and Frame; mixing shipped and built
copies would cross-link stale interfaces); otherwise everything falls
back to the builders as before. Appended duplicates: shipped node groups
replace same-named ones (`user_remap`, remove, rename), existing
materials replace shipped ones. Result: a belt line on a file without the
belt tree builds in 0.14 s instead of 12 s. The builders remain the source
of truth; regenerate the library after any builder change (the tool also
re-pushes every line's modifier inputs and removes trees it had to create).

**Galleries.** `piece_library.draw_gallery(layout, entries, current)` is
generic; `conveyor.type_library` (picture button beside Type; sets the
type through `conveyor.set_type`) and `conveyor.transfer_library` (beside
the compact chooser's pull-down; runs `conveyor.junction_set`) reuse it.
`tools/render_piece_thumbs.py` renders `TYPE_<id>` (a straight of each
type) and `TECH_<id>` (a junction of each technology at an angle it
exists for) next to the pieces.

**Catalogue vocabulary and numbers** (public conveyor knowledge):
- Vocabulary: "Roller (MDR)" (motor-driven rollers are the workhorse; a
  gravity roller is a 2-4 % decline shipping lane), "Modular plastic
  belt", "Cleated belt (steep)" (a "pocket conveyor" is the overhead pouch
  sorter, a different machine), "Vertical conveyor (S / C)" with S =
  through (our Z geometry) and C = same side (continuous vertical
  conveyor, 1,000-1,400/h; a platform lift is cycle-based and slower).
- Numbers (conveyor_types.json, technologies.json): typical speed windows
  (MDR 0.3-1.0, belt 0.5-2.0 m/s) and practical rates (MDR 2,400/h, belt
  3,000+/h, 90 deg pop-up 1,500-2,400/h, HP 4,000/h, ARB 5,000/h, pusher
  600-1,200/h, spiral 2,000/h, S/C 1,000-1,400/h). `ConveyorTypeSpec`
  carries `speed_m_s` and `rate_per_h`.
- Checks in the panel (warnings only, best practice): speed above the
  type's window; the smallest item on fewer than three rollers
  (`_three_rollers`: after a right-angle transfer the SHORT side runs along
  the rollers); a buffer on a belt line ("a plain belt cannot
  accumulate"); a 90 deg branch narrower than the item is long ("the
  divert lane must be as wide as the unit is long"); the chain rule for
  spirals, vertical conveyors, RATs and ARB elements (`_rate_alert`,
  throughput vs. the element's practical rate; junctions had it already).
- 2.25 (public release): the price-based Budget was removed with all its
  data; the scene's obstacle checks moved to `conveyor.checks`.
- Not changed, deliberately: sorters (cross-belt, shoe, tilt / split /
  cross-tray), pocket sorter, decanting / carton machines are system-level
  elements outside a conveyor-line builder; gap control / induct remains a
  note.

## Round four: less, flush, CAD-like (2026-10-06, v2.6)

User brief: legs flush with the conveyor ends (docking to other
machines); the drawing layer must be switchable off and must vanish in
Material Preview / Rendered shading; the divert animation "still a bit
off"; the panel shows too much.

- **Legs** (`common.build_legs`): stations by COUNT per spline
  (`floor(length / Support Spacing) + 2`, min 2, Resample Curve in Count
  mode with a per-spline field) so every run has a stand at both ends and
  even spacing between; the end stands are pulled in by half a post along
  the tangent (Spline Parameter factor ≈ 0 / 1) so their outer faces are
  flush with the end face. (Resampling by length used to leave the last
  stand wherever the length ran out.) `NodeGraph.vmath('SCALE', v, s)`
  feeds the Scale socket.
- **Overlay** (`ui/dimensions.overlay_shown`): drawn only when the scene
  switch is on, the viewport's overlays are on, and `shading.type` is
  SOLID or WIREFRAME; the figure gizmo group polls the same, so nothing is
  hit-tested either. The switch sits in the panel header
  (`draw_header_preset`, ruler icon) next to the version.
- **Right-angle divert path** (`detect_junctions.prefix_for`,
  `_attach_branch`, `_set_branch`): a branch docked at ≥ 80° gets
  `branch_blend` 0, `branch_keep_yaw` = the main's flow heading minus the
  branch heading (±90°) and `branch_slide` = the face centre's distance
  from the centreline. Its prefix is the main's path to the divert
  centre, then a straight slide to the face (heading = the branch's,
  yaw = keep), and the branch's own spine starts with that yaw
  (`build_line.evaluate_line` passes it as the start Pose's yaw_offset),
  so the goods keep the main's orientation and ride the branch sideways,
  exactly as `continuation_for` already did for right-angle merges. The
  transfer window for the belts spans `branch_blend + branch_slide + half
  a slot`. Angled branches keep the Hermite blend.
- **Panel** (`ui/panels.py`, `junction_edit.draw_chooser(compact=True)`):
  hints are gone (they live in README and tooltips); Details shows fields
  (property-split) plus warnings only; the docking block shows the
  junction's angle row, the transfer as one pull-down
  (`CONVEYOR_MT_junction_tech`) with swap / detach icons, and "Feeds X
  (45°)" / "Branch of X"; nothing is said when a line is simply not
  docked. The gear popup keeps the full chooser.

## Share routing (2026-10-05, v2.6)

User report: branches off diverters "do not follow the mathematical logic
or animation of the main conveyor" -- they had no Route (the main was
populated after they were docked, so `_link_goods_on_attach` never set
one) and so ran their own streams. Now `stream.parent_of` makes EVERY
branch docked on a diverter of a populated main a 'DIVERTER' child, and
what it takes is one of three things: a CLASS (Route set on the diverter),
its own ITEM (eyedropped; owner masks as before), or its SHARE. Share
branches are numbered depth-first along the flow (`tree_for`: `number()`
from the root and then from every non-share member, so a branch's subtree
is one contiguous range), `tree.exits` = N + 1 (index N = stays on the
main), and each gets `only_class .. only_hi` = its range. The populate
group's `route_key` is the slot's item class, or -- with `Route Exits` >
0 -- `slot index mod Route Exits` (round robin: three branches, every
fourth item carries on); `key_in(lo, hi)` replaces the single-class
compares everywhere (`Only Class / Only Hi`, `Route Class k / Route Hi k`,
`Transfer k Class / Transfer k Hi`, all pushed by
`operators/populate.route_values`; transfer tuples carry (lo, hi)). With
a Route anywhere in a group the keys are classes and unrouted branches get
`NO_CLASS` (nothing) until they get a Route too -- ranges cannot express
"class c, any exit" and "exit e, any class" at once. The Route menu's first
entry reads "Share"; `junction_load_ph` scales a share branch's load by its
exit count. Verified live over a full stream cycle (3 branches, 6 slots:
2 / 2 / 1 slots, no duplicate instances).

## Buffer photo-eyes (2026-10-05, v2.6)

`common.build_buffer_stops`: the zone sensors moved to the FRONT of every
queued item -- one Queue Gap before the end stop, then every pitch
upstream (the queue packs against the stop with the gap after each item,
`populate.queue_branch`) -- and became photo-eyes: a 20 x 30 x 45 mm black
housing (`materials.sensor`, "Conveyor - Sensor (Black)") on a bracket from
the right frame rail, lens 60 mm above the rollers, a 40 x 40 reflector on
the left rail. `buffer_gap_mm` defaults to 150 (was 50): a zone is one item
plus the gap, and the gap is what makes the queue read as ZPA.

## Node tree layout (2026-10-05, v2.6)

User brief: "clean up the geometry nodes so people can read them; a visual,
group-based system that takes the user through the flow". `NodeGraph`
gained stages: `g.stage(title, note)` starts a new column with a gap and a
labelled, coloured `NodeFrame` ("3 · Fences") that every node made until
the next stage is parented to, plus the stage's OWN Group Input node --
`link()` / `_feed()` redirect any Group Input socket to the current
stage's copy (same identifier), and `guide()` hides every Group Input
socket without links, so each stage shows only what it reads and the
tree has short local links instead of hundreds of noodles from one node.
Nodes stack by an estimated height (header + 22 px per visible socket) and
wrap into a new column inside the frame past `_STAGE_HEIGHT`. `guide()`
(the last call of every builder) also writes a Text datablock
("Guide · <tree>": the intro and the numbered stages with their notes)
into a frame at the top left. Each `build_*` in `cross_sections/common.py`
opens with its stage (Spine, Frame rails, Fences, Legs, <surface>, Modules,
Junction decks, Buffer stops, ARB decks, Goods, Highlight, Transfer parts,
Columns, Spiral arms, Lift forks, Output); the populate group has ten.
Node groups per stage (one group node each) would be the next step; the
stage functions pass many sockets (SpineParts) between them, so that is a
larger refactor.

## Origin attach (2026-09-30)

The primary way to join lines. A line's ORIGIN (its start, where the
object origin sits) attaches by proximity (`detect_junctions._sync_origin`):

- `attach_candidate` takes the line whose centerline is within its half
  width + the Dock Distance of the origin in plan, within 0.3 m of its
  surface height, and not at its very ends (`END_MARGIN_M`: New Line from
  End continues a line, it does not attach to it). Loops are refused
  (`_hangs_on`).
- Side = the side the line's body extends to (so R past the main line's
  axis moves it to the other side). Angle = the body's angle to the
  target's FLOW folded into 0..90, snapped to 15 degree steps
  (`junction.snap_step`, min 15). Role: body UPSTREAM (phi > 90) = MERGE,
  the line is set reversed (goods run to the origin); DOWNSTREAM =
  DIVERTER, forward; at 90 the previous role, default MERGE. Toggling
  Direction on an attached line keeps angle and side and swaps the role,
  so the line swings to the mirrored angle.
- The junction's face center lands where the origin is (module start =
  s_at - face y). `_insert_junction_fit` slides it up to 1 m to the
  nearest level straight where it fits with >= 50 mm pieces left either
  side, so a re-sync finds it at exactly the same place. Moving along
  re-inserts it and carries `junction_tech` / `route_class` over. A free or
  manual junction whose face is at the origin is used with its own angle;
  a renamed line adopts its orphaned auto junction (before, a second one
  was inserted beside it and slid 0.6 m).
- An attached line is PINNED: its far end docks the classic way only
  within `PINNED_REACH_M` (0.15 m) and is fitted by stretching its trailing
  straight (undone if the dock fails), never by moving or rotating the line.
  Attached lines sit at 15 degree steps, so their far ends used to meet
  neighbouring feeders at exact junction angles and grab them.
- Following: the depsgraph handler puts lines docked on a moved line back
  on their junction faces (`follow_target`, rigid, cascading down chains of
  attached lines) instead of re-aiming them. `_refresh_docked_feeders`
  (line rebuilt in place) does the same with `rigid=False`: when the
  target's flow flipped, a line whose pose now says the other role keeps its
  pose and swaps role instead of swinging to the mirrored junction.
- Matrix bookkeeping: `conveyor_last_matrix` is computed from the object
  channels (`_world_matrix`) and re-stamped whenever the add-on itself
  places a line (`_remember_matrix`), so only real user moves re-sync a
  line. Before, a just-snapped line looked moved on the next update and was
  re-evaluated against a main line the user had moved meanwhile: it came
  loose. `_drop_stale_docks` drops a continuation / prefix whose junction
  is gone.
- First attach (`_link_goods_on_attach`): a merge onto a populated group
  turns Populate on; an outfeed from a line carrying placeholder items
  routes class 0. New Line at 3D Cursor with the cursor on a line starts
  square off it (`attach_heading_at`): a 90 degree merge.

Shared streams centre every item in a slot of the group's LONGEST item
(`Slot Length` on the populate group, `StreamTree.slot_length`). With its
own item length a line carrying small items put them (L1 - L2) / 2 off the
slot grid -- into the neighbouring slot's goods after a merge.

A rebuilt node tree re-pushes the inputs of lines in EVERY scene (node
trees belong to the file; lines in other scenes lost their legs and rails).

## Junction technologies, ARB elements, ZPA (2026-09-29)

`config/presets/technologies.json` holds the junction technologies
(label, valid roles and angles, typical rate). A MERGE / DIVERTER segment has `junction_tech` (AUTO resolves per
role and angle in `build_line.resolve_junction_tech`); `Module` carries
`tech`, `skew` (transfer direction relative to the heading, flow-aware),
`side` (geometric) and `flip` (layout mirrored), written as the curve
attributes `module_tech / module_skew / module_side / module_flip` on the
module run AND on its outline extra (extras may carry an attribute dict).
`common.build_merge_junctions` builds the deck, then per technology:
skewed rollers (landing-zone rollers yawed by `module_side`, using a
stored `mod_arc` spline length), pop-up wheel rows between rollers
(Endpoint Selection drops the last row), strip belts (a 5-strip set
scaled to `min(0.95 L, 0.9 W / |sin skew|)` and rotated by heading +
skew), ARB (a belt plate over the junction's own outline plus a raycast
wheel grid with `skewed=True`; no rollers underneath) and the pusher unit
on the far side. `stream.junction_load_ph` sums the owner rates entering
a merge / taken by a divert's branches (class routing divides by the
placeholder count); the panel flags a bottleneck above the rate.

ARB inline elements: module kind ARB (6) is a belt deck with herringbone
(centre) or uniformly skewed (turn) roller rows; kind PIVOT (7) is swept
by the line's own surface plus a pin at the edge. `Module.turn` adds to
the goods' `yaw_offset` at the module end (linear interpolation rotates
them in motion); `Module.center` makes `write_spine` emit `lane_scale`
(1 -> 0 over the module in flow order) which the populate group multiplies
into Lane Offset. `spine.ensure_attribute_defaults` gives older spines the
attributes newer trees sample (called for all lines on a tree rebuild).
Buffers get ZPA zone sensors: the reversed buffer run trimmed to whole
zones and resampled at the queue pitch.

## Spirals, lifts, floors, pocket belts (2026-09-29)

`Spiral(angle, inside radius, direction, rise)` samples a helix with true
3D arc lengths and a constant pitch (`spiral_pitch`); it "bends itself"
(no nose-over before/after, a zero-length level duplicate after it) so the
stated height is exact. A LIFT is a `Module(kind="LIFT", height_m, shape)`
whose path is two quarter arcs (nose-over geometry, `LIFT_RADIUS_M`) and a
vertical straight; Z keeps the heading, C continues over the top (pitch
90->180) and leaves as a level frame with heading + pi. Lift points carry
KIND_LIFT -> the spine's `item_level` attribute -> the populate group zeroes
the incline so carriers stay level. Lift and RAT modules are excluded from
guide splines and legs; lifts are swept like the conveyor (belt).

Columns: ROLE_COLUMN (5) extras -- a spiral's centre (`spiral_center`) and
a lift's two tower posts -- are 2-point splines whose first point is the
top; `build_columns` drops a round column from there to the floor.
Floors: `floor_below` casts a ray down from each leg/column point against
the realized `Floors` collection (Collection Info, object-relative) and
uses the hit's z, else `Floor Z`; per-point, so a line above a mezzanine
deck stands on it. When no Floors collection is set, `operators/floors.py`
keeps an unlinked helper collection ("Conveyor Floors (auto)") holding
every mesh object of the scene except placeholder / eyedropped items; the
depsgraph handler re-syncs its membership, so any plane dropped under a
line becomes its floor. (Conveyor lines are Curves objects and never
candidates, which also avoids dependency cycles.)
Spirals carry `no_legs` = 1 on their points (build_legs deletes those
stand points) and ROLE_ARM (6) 2-point splines every 45 deg of plan angle
from the drum out under the track (`build_arms` sweeps a 80x50 mm tube). Pocket belt (`cross_sections/pocket.py`): the belt tree
plus cleats that ride with the belt (chain-link sampling) and side walls.

## Flow direction (2026-09-25)

`reverse` on a line defines its FLOW: goods enter at the flow start and
leave at the flow end (the curve's end, or its start when reversed). All
docking works in flow terms (`detect_junctions._flow_end/_flow_start`,
`_flow_spine`): the flow end docks onto a MERGE, the flow start onto a
DIVERTER, so a reversed line docked by its curve end is an outfeed.
Junction wedges are laid out along the target's flow (`merge_layout_for`
mirrors on reversed mains) and dock angles snap to the target's flow
heading. `continuation_for` / `prefix_for` return flow-wise point lists;
`build_line` composes the geometric full spline from them (mirrored and
swapped to the other end for reversed lines) and `write_spine` takes
geometric `before` / `after` lists with an `own_shift`. The populate group
gets `Stream Flip`: the shared stream always runs forward along the flow
(speed magnitude) and a flipped line mirrors the sampled arc and turns the
items to face their travel. Flipping Direction releases every dock first.

Routing by item: an outfeed with an eyedropped item takes the slots of
every owner line carrying the same item (`stream.allowed_owners`); route
rules then carry class -1 (any) with that owner mask. Throughput: when any
line of a group sets items/h, spacing = speed * 3600 / total and slots are
dealt by share through cumulative `Owner Split k` inputs (weighted random
pick per slot index).

Buffer modules (kind 4) are swept like the conveyor; `stream.tree_for`
turns them into stream-coordinate zones pushed to every line whose goods
pass them (`Buffer From/To k`, hiding items by their centre) and into
`Queue Span/Offset k` for the line's own static queue (the populate group
with speed 0 over the span, packed against the end at item length + gap).

Omni type (`cross_sections/omni.py`): deck plate + staggered wheel rows
(`common.build_omni_wheels`); junction wedges get a local wheel grid kept
where a downward raycast hits the slab (`omni_wheels_on_slab`); RATs a deck
box with wheel rows. Only the line trees that exist in the file (plus the
one needed) are rebuilt on a version bump, so a fresh file builds one tree.

## Shared item streams (2026-09-24)

Lines docked onto each other (feeder end on a merge, branch start on a
routed diverter) form one group with ONE stream (`operators/stream.py`):
one spacing (the largest any member needs, including the wedge-path lag),
one speed (the root's), one seed, one wrap length. Each slot has one
OWNER -- root 0 or a populated feeder 1..K, picked per slot index with a
seeded Random Value -- and only the owner draws it (`Owner Mask` bit test
in the populate group), so merged goods can never overlap. A feeder draws
its slots along its own path and, via its continuation, down the main.
Stream coordinate `u = full-spline arc + Stream Offset`; a feeder's offset
is offset(main) + face arc - (own length + transfer extra), offsets are
shifted to be >= 0 and the wrap length is the largest offset + full length.
Every rebuild re-pushes the inputs of the whole group
(`_refresh_stream_peers`). A single line is a group of one (no ownership,
wrap = own length) and behaves as before.

Diverter rules carry an owner mask and are pushed only to the lines whose
goods pass the diverter (the main, feeders entering upstream of it,
branches leaving downstream of it) -- never to the branch receiving that
class. Renaming a docked line: the stale-source cleanup in the depsgraph
handler now re-docks lines whose continuation/prefix still point at the
main instead of just dropping the junction.

Transfer paths (`continuation_for`): 30/45/60 merges follow a Hermite blend
that starts tangent to the feeder and lands parallel on the centerline over
the taper length; goods align with the main as they go. 90 (RAT-style)
merges slide straight across to the centerline and then ride the main with
`yaw_offset` = the turn the item did NOT make (a right-angle transfer
never rotates the goods). Arc lengths on these points are GEOMETRIC (the
populate group samples by true length); the excess over the main's stretch
is `continue_extra_m` and enters the stream offset and the shared spacing.

Fence openings: `guide_gap` is a bitmask (1 = left, 2 = right) on the
spine points. It must NEVER be interpolated: a swept face at the start of a
right-side opening averaged corners 0 and 2 to 1 = "left open" and deleted
the far fence along the whole neighbouring straight, and resampled bracket
points read the wrong side (brackets standing inside openings). The trees
therefore store one 0/1 flag per side (`guide_open_1/2`) on the guide curve
before sweeping / resampling and test those, and `write_spine` adds exact
samples 5 mm outside every opening so the flag does not ramp from the
previous spine point metres away (brackets 2 m upstream read "open"). The
main fence stops where the feeder's inner fence line meets it (a T-join)
and resumes after the taper lands; there are no connector stubs at any
angle (they read as loose fence profiles inside the merge).
Resample Curve keeps a curve's end points, so a line always got a bracket
pair at its very end -- on a docked feeder that is the merge face. The
spine carries a `bracket_skip` flag over the last/first 0.2 m of a docked
end/start and the trees place no bracket there. Brackets are rotated by the spine frame, whose X axis points RIGHT (the
rail profile's X points left through the Free normal), so a bracket built at
+X tests the RIGHT opening flag.

Master materials: the depsgraph handler tracks the material slots of each
"master" line (`stream.dock_root`: the line nobody docks on) and, when they
change, copies them to every line docked onto it, directly or through
further docks (`_propagate_master_materials`). Only changes propagate, so a
docked line can still be recoloured on its own until the master changes.

Fences and legs: `write_spine` emits ROLE_GUIDE (4) splines -- consecutive
runs joined across junctions, RAT modules left out -- and the trees sweep
guide rails (with caps) and place floor stands on those, so there are no
seams, open rail ends or doubled legs at module boundaries. Merge/diverter
junctions on belt and chain lines get a belt/plate-chain top instead of
rollers (`build_merge_junctions(surface=...)`); the Builder panel shows the
installed version from `blender_manifest.toml`.

## Routing (2026-09-24)

A DIVERTER is the outbound twin of a MERGE junction: the same wedge
geometry mirrored along the main direction (`model/junction.mirror_layout`),
so the taper opens downstream and the face sits at the module's end. A
branch line docks with its START on that face (`detect_junctions._sync_branch`
mirrors `_sync`: aim backwards from the start, snap the heading, move the
line so its start is at the face, insert an auto diverter or dock onto a
free/manual one). `merge_source` on the diverter names the branch;
`docked_diverter` / `docked_junction(kind)` look it up. Releases are scoped
by junction kind so a line can be a feeder (end) and a branch (start) at
once. All docking math uses `_world_matrix(obj)` (recomputed from the
object channels) because `matrix_world` is stale until the depsgraph runs.

Item streams: main and branch draw ONE stream. The branch's FULL spline is
prefixed (`write_spine(prefix=..., prefix_shift=...)`, segment_index -2)
with the main's full spline up to the switch point plus a lateral blend onto
the branch start (`prefix_for`), and its own arc lengths are shifted by the
face center's arc on the main (`branch_from`). The populate group then gets:

- `Stream Length`: shared wrap length = the longest full spline in the
  routing tree (`stream_length_for`), pushed to the root and every branch.
- `Prefix` (branch): items with arc < switch are hidden (the main draws them).
- `Only Class` (branch): the placeholder index routed here (`route_class`).
- `Route Class k` / `Route At k` (main, 4 slots): that class is hidden past
  the switch arc of diverter k (`route_points`).
- `Use Stream Speed` / `Stream Speed` (line tree): the branch's stream runs
  at the main's signed speed; its own Speed still drives its rollers.

The item class is the Random Value pick per item index (same seed ⇒ same
class on both lines); the class index is the placeholder's position in
NAME order, because Collection Info sorts a collection's children by name.
`populate_values` derives a routed branch's populate inputs from its main
(`routed_from`, recursion-guarded) so chained routing works. Rebuilding a
line re-pushes the inputs of its whole routing tree (`_refresh_stream_peers`)
and rebuilds docked branches (`_refresh_docked_feeders`, key `branch_target`).
Undocking (`_undock`) clears prefix and continuation.

Viewport gotcha: instances of an object that is *disabled in viewports*
(`hide_viewport`) evaluate but draw nothing; the placeholder items are
hidden another way (see `ensure_placeholders`).

## Junctions

The merge junction is a MODULE on the MAIN line (model/junction.py):
a deck with an angled infeed face on one side or on both (`merge_side`
LEFT / RIGHT / BOTH, `merge_angle` 15/30/45/60/75/90 -- 90 is the
perpendicular right-angle-transfer style dock) sized for the docking
line's frame width (`merge_infeed_mm`, kept in sync with the docked line,
shared by both faces of a two-sided junction). Its footprint along the main
line is exactly the face plus the taper's tail, so a 90 dock is as wide
as the docking conveyor. Short connector fences join the main fence to
the feeder's fence ends at both corners of the face.
Between the face and the main edge a wedge deck carries rollers that get
progressively longer (per-row raycast against the deck slab in the tree,
so any number of junctions share one node tree), and a fence tapers with a
tangent arc from the face's outer corner onto the main line's fence. The
main line's own fence opens over the junction on the infeed side. Outline
and taper fence are written into the main line's spine as role-3 / role-2
splines; the junction's footprint length is derived from the geometry.

A FEEDING line needs nothing special: it ends flat. operators/
detect_junctions.sync_feeder runs after every build and on transform
changes. Its ORIGIN attaches by proximity (see "Origin attach"); for the
FAR end it aims a ray from the feeder's end (reach = the scene's Dock Distance, default 0.6 m, measured to the target's near edge), snaps the
feeder's heading to the nearest catalog angle (rotating the object about
its end), fits the end so the near corner of its face sits on the main
edge (re-lengthening a trailing straight, or adding a fitted filler
straight after a curve), and then either docks onto a free or manual
junction of matching angle and side within 0.8 m (moving the feeder onto
its face) or inserts an auto junction by splitting the straight under it.
Auto junctions follow their feeder, and are folded back into the straight
when the feeder leaves or is deleted; manual junctions stay and are just
marked free. A line whose last segment is a CURVE that lands parallel to
(or too shallow against) another line within 3 m is re-aimed: the curve's
angle is changed to the first catalog approach in (45, 30, 60, 90) whose
end can still reach the target's edge, then the normal fitting adds the
filler straight and docks. The panel shows why a line is not docked. A line's `dock_enabled` switch (Detach / Dock buttons in the
Builder panel) turns docking off for that line and releases its junction.

Module lengths are per segment (`length_mm`): RATs are user-editable so
other lines can dock along them (the RAT group is stretched along travel),
diverters stay at catalog length, junctions are derived.

Two hard-won rules for shared node groups: (1) a group rebuilt in place
gets new socket identifiers, which orphans the stored inputs of EVERY
modifier using it, so `_apply_modifier` rebuilds all line trees together
when any shared tree is stale and then re-pushes every line's inputs;
(2) never call `NodeTree.interface_update()` from Python -- on 5.3 it
zeroed the inputs of other objects' modifiers.

### Junction mechanics

`operators/detect_junctions.py` runs after every build and on transform
changes (a `depsgraph_update_post` handler watches each line's matrix).
When a line's end lands within the target's body band plus tolerance, the
feeding line's trailing straight is re-lengthened, a MERGE module is
appended, and the target receives a `guide_gaps` entry (keyed by the
feeding line's name) that opens the guide rail on that side over the
feeding line's width. Exact spine samples are inserted at the gap
boundaries so the attribute never smears along a straight; the guide
sweep deletes faces whose corners all lie inside the gap. Gaps follow the
feeding line when it moves and are removed when it leaves or is deleted.

## Tree lifecycle

Each builder owns a `TREE_VERSION`. `get_or_create_tree(name, version)`
rebuilds when new, stale or forced and never stamps; `mark_tree_built` is
the builder's last line, so a mid-build exception leaves the tree stale and
the next call retries. `build_line` re-asserts every modifier input on
every run (cached inputs are keyed by socket identifier and a rebuilt
interface orphans them).

Nested groups (`Frame`, `Populate`, module trees) are referenced by the
line trees as datablocks, so rebuilding a nested group updates every line.

## Materials

One material per role (`geonodes/materials.py`), stamped with
`MATERIAL_VERSION`; an existing material at the current version is left
alone so user restyling survives. The belt material reads the geometry
attribute `belt_scroll` (= arc length − time·speed, stored by the belt
tree), which is how a single shared material scrolls at each line's speed.

## Live update and callback safety

Every geometry-affecting property carries `update=_rebuild`, which
resolves the owning object via `self.id_data` (never the active object).
Operators batch edits under `suspended_rebuild()` and build once.
Auto-merge only edits the feeding line's own segment list; nothing inside
a callback deletes or replaces objects.

## Testing

`python3 -m unittest tests/test_segments.py` covers the chain math
(straights, curves, inclines, nose-overs, RAT exits, runs). Live checks use
`utils/probes.py`: `evaluated_geometry()` (never `to_mesh()` on CURVES) and
instance frame probes (rotate unit vectors, check `right.z == 0`).

## Reload recipe (live session)

1. `addon_disable` first, 2. purge `sys.modules` entries starting with
`bl_ext.user_default.conveyor_system`, 3. `addon_enable`, 4. bump
`TREE_VERSION` or `build(rebuild=True)`, 5. rebuild every line.

## Out of scope / deferred

BOM export, multi-lane populate, modal draw tool, curve→segments
converter, MDR motor housings, spiral/lift/pallet/chute modules (the module system accepts new kinds:
add to `segments.json`, a `geonodes/modules/*.py` builder, and one entry in
`common.build_modules`).

## Round twenty (2026-10-12): the start side is the goods' side

- `operators/segments.py::_prepend` no longer mirrors curve kinds or a RAT's exit: left / right / up / down always mean the goods' travel direction, at either end (the mirroring made a prepended Curve Left turn the goods right). The origin still moves back so the built part stays put (`START_ANCHOR_KEY`).
- The goods keep their world place after a prepend: the growth of `own_length_m` accumulates in `settings["stream_shift_m"]`; `stream.tree_for` subtracts `shift / (speed × time scale)` from `phase_s` for a root line with no origin-port link (node tree: traveled = (scene s − Stream Phase) × speed). Gap: a first-piece edit with keys at Start also moves the origin but does not update the shift yet.
- Spiral height in Details: `height_m` beside Turn, `conveyor.set_spiral_height` (1/2/3/4 m, keeps the sign), `conveyor.spiral_flip` ("Down").
