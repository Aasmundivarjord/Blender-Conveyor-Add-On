# Build v2 of the "Path-Driven Conveyor System" Blender Extension

This is the complete brief for **version 2** of a Blender Extension that lets a
user design realistic, catalog-accurate warehouse conveyor systems inside
Blender. Version 1 was built and iterated live with the user over many rounds;
it got far, but one core problem (how populated goods sit on the conveyor)
was never solved to the user's satisfaction, and the diagnosis was that the
*path model itself* was the flaw. v2 is a **full rewrite from this brief**,
using v1 only as a source of lessons and of verified catalog data.

Read this whole document before writing any code. Section 12 tells you how to
start.

---

## 0. Where things are

- **Working folder (v2):** `.../Self Initiated/Conveyor Extention/` — this is
  what the Blender extension symlink points at
  (`~/Library/Application Support/Blender/5.3/extensions/user_default/conveyor_system`,
  Python module name `bl_ext.user_default.conveyor_system`).
- **v1 archive (frozen, never edit):** sibling folder `Conveyor Extention v1/`
  (manifest 1.0.0, 52 files) and `conveyor_system-v1.0.0.zip`. Consult it for
  reference when a lesson below needs code context; do not copy its
  architecture.
- **Original v1 brief:** `blender_conveyor_extension_prompt.md` in the working
  folder. This v2 brief supersedes it; the v1 brief remains the source for
  the product vision and the initial research dataset (restated in §2 and §5).
- **Already in the v2 folder when you start:**
  - `blender_manifest.toml` — stamped `version = "2.0.0"`.
  - `config/presets/*.json` — v1's verified catalog data (widths, roller duty
    classes, incline limits, conveyor types). Carry over as data; rewrite all
    code that reads it.
  - `model/segments.py` + `tests/test_segments.py` — pure-Python segment-chain
    math (no bpy) with unit tests. This is the intended foundation of v2's
    path model (§7). Verify the tests pass (`python3 -m unittest tests/test_segments.py`)
    before building on it; adjust freely if the design in §7 calls for it.
- **Live test environment:** the user's own running Blender (**5.3.0 Alpha**,
  not 5.2 LTS), reachable through the Blender MCP connector
  (`execute_blender_code`, `render_thumbnail_to_path`). The user works in the
  same live session concurrently — see §10 for the rules that follow from that.

---

## 1. Product vision (unchanged from v1)

A user designs a warehouse conveyor line in minutes, entirely inside Blender,
without modeling or importing CAD. They lay out a path, pick a conveyor type
and width from real catalog options, and get a render-ready line: frame,
rollers/belt/chain, support legs, guide rails, and (optionally) totes/cartons
flowing along it, animated by a single speed value.

- **Primary use case:** fast, good-looking conveyor layouts for sales/proposal
  visualization that also hold up as photoreal marketing renders and short
  walkthrough videos.
- **Personal project, single user**, but built cleanly enough to open-source
  later: clean modular code, documented decisions, editable config data, no
  hacks.
- **Explicitly out of scope (all versions so far):** BOM/parts export,
  company-specific integration, multi-user, vendor SKU matching, spiral /
  lift / pallet / chute modules (design the module system to accept them,
  don't build them).
- **Prior art to study, not clone:** Configura CET's Material Handling
  vertical and its Conveyors extension. CET assembles conveyors from discrete
  catalog modules (straights, fixed-radius curves, inclines, transfers) that
  snap together and behave like real products. **v2 adopts that
  segment/module model** (§7). Use CET's taxonomy
  (transportation / accumulation / gravity / sortation / transfer / lift /
  chute / pallet) for coverage; design our own UI, naming and visuals.

---

## 2. Feature rundown — everything v1 delivered (the v2 target, at minimum)

Every item below was working and confirmed by the user in v1 unless marked.
v2 must reach at least this feature set, on the new architecture.

### 2.1 Conveyor types (one generic GN system, parametrized by type)
- **Gravity roller** — idle rollers, side rails, support legs, guide rails.
- **Powered roller (MDR)** — same cross-section, MDR duty class
  (drive/motor housing detail was *not* modeled in v1 — a known gap).
- **Belt** — rails, end pulleys, continuous belt surface, idler rollers
  beneath (belt UV scroll animation was *not* done in v1 — known gap, see §4.9).
- **Chain / modular plastic belt** — link plates at a fixed pitch, sprockets.
- **Curves** — continuous-radius turns of any of the above.
- **Right-Angle Transfer (RAT)** — discrete inserted module (powered transfer
  head), never a bent path.
- **Merge / transfer junction** — module joining two lines.
- **Diverter / sorter** — visual module only (skewed-roller style); was in the
  catalog JSON in v1 but its geometry was never built.

### 2.2 Cross-section details the user explicitly asked for and approved
- **Support legs on both long sides**, on the rail line, always perpendicular
  to the *local* travel direction (v1's first attempt put them in the middle /
  along the wrong world axis — the user was emphatic: "IT SHOULD BE ON THE
  LONG SIDE OF THE CONVEYOR!!!! just see how CET does it"). Legs go down to
  local Z=0 (floor).
- **Dense roller pitch** — real catalog pitch reads as sparse in a viz tool; the
  user asked twice for tighter rollers. v1 applied a 0.5 visual factor to the
  catalog pitch *and* a hard floor `pitch >= diameter + 4 mm` so rollers can
  never interpenetrate. High Detail must still show a visible gap between
  rollers.
- **Rollers must stay inside the rails** — roller ends may not poke through the
  outer rail face (v1 clamped roller overhang to `< 0.6 * rail_thickness`).
- **Smooth shading** on all cylindrical parts (rollers, idlers, pulleys,
  sprockets), 32 sides in High Detail, 12 in Low.
- **Guide rails** — a second, thinner rail pair raised above the main frame
  rails ("safety guides so packages don't fall off"), on by default, that
  should connect across merged/joined lines.
- **Materials:** brushed/galvanized steel (frame, rollers, legs), black rubber
  (belt), painted steel / safety-yellow accents, neutral plastic. Real shipped
  node-group materials, separate swappable slots, one shared material per
  role so the user can restyle everything at once.

### 2.3 Path / layout behaviour
- **Standard angles only.** Conveyors turn at standard angles (45°/90° etc.),
  climb at standard incline angles (v1 snapped to 0/15/30/45/60°). v1 did this
  by snapping a freeform curve after the fact; v2 gets it for free from the
  segment model.
- **Constraint feedback with Auto-Fix**, not passive warnings: the user found
  a warning panel "not useful"; they want one click that fixes bend radius /
  incline violations. In the segment model, constraints are enforced at
  authoring time instead (a curve segment simply only offers catalog radii).
- **Live update.** Any setting change regenerates geometry immediately — no
  "Generate" click. (A manual Refresh stays as a fallback.)
- **RAT at 90° corners.** A true 90° corner should become a discrete RAT
  module, not a swept curve; the user must be able to revert a corner to a
  smooth curve. In v2 this is simply a choice between a Curve segment and a
  RAT module segment.
- **Auto-merge.** When one line's end comes near another line's body, snap it
  on and create a junction automatically, no button. Manual override of the
  junction module type must exist.

### 2.4 Populate (goods on the conveyor) — the v1 pain point, see §4.1
Controls the user asked for and approved:
- **Pick Item** — Blender eyedropper on an Object property to use any scene
  object as the item (in addition to shipped placeholder totes/cartons).
- **Spacing (mm)** — center-to-center distance, seeded from the picked item's
  length on pick (once), then user-owned.
- **Fill %** — density: fewer items, still spread evenly over the full line
  (NOT random thinning — the user hated the uneven clusters that produced).
- **Rotation offset (deg)** — manual yaw correction for an item whose forward
  axis isn't Y (see §4.10 for why v2 should auto-detect this instead).
- **Deterministic layout, no spacing jitter** ("we do not need any space
  jitter"), items never intersect, the line fills end to end, first item flush
  with the start of the line.
- **Correct height**: the item's bottom face sits on the conveying surface
  regardless of where the asset's origin is (use the object's bounding box,
  which is in local space *before* object scale; `.dimensions` bakes scale in).
- **Correct scale**: `Object Info (As Instance)` carries location/rotation but
  NOT the source object's scale — re-inject it explicitly.
- **Flow animation** driven by Blender's scene time and the line's Speed:
  items advance along the line and wrap. The user **loves** the
  "spawning" look: items should disappear at the end and be fed in fresh at
  the start rather than teleport the length of the belt. **Negative Speed
  reverses everything** (items and roller spin together).
- **Orientation**: items follow the path in all three axes — yaw through
  turns, pitch up/down inclines, and **zero roll**: the item's Z must be
  normal to the conveying surface and its X must run side-to-side across the
  belt. "It should look like the objects are actually transported by the
  conveyor." This is the requirement v1 could not satisfy visually.

### 2.5 LOD, units, UI
- **High / Low Detail** per line + scene-level override; Low Detail = fewer
  cylinder sides, coarser pitch, coarser curve resolution.
- **Units**: canonical mm in config, converted to Blender units at the
  boundary; follow scene unit settings (imperial display supported).
- **UI**: a "Conveyor" N-panel tab with per-line settings, a Populate panel,
  a Modules panel, Scene settings (LOD override, Play/Pause).

---

## 3. v1 architecture (for context — do NOT reproduce it)

```
__init__.py               registration list of submodules
config/  specs.py loader.py units.py presets/*.json
geonodes/ builder_common.py (NodeGraph wrapper, shared rail/leg/wheel builders,
          SCHEMA_VERSION cache stamping), cross_sections/{roller,belt,chain}.py,
          modules/{rat,merge_junction}.py, populate.py, materials.py
props/    path_settings (per-curve PropertyGroup with update= live callbacks),
          module_settings, scene_settings, preferences
operators/ generate (the hub), insert_module, resolve_corners (split curve at
          90° corners -> RAT), detect_junctions, populate, regenerate_all,
          snap_angles, autofix
ui/panels.py   utils/curve_geo.py (bezier sampling, snapping, autofix)
```
Key v1 design choices and their fate:
- Node trees built **entirely in Python** (`nodes.new`/`links.new`/
  `interface.new_socket`) via a small `NodeGraph` wrapper — **keep this**; it
  made everything diffable and iterable.
- Path = user-drawn **freeform Bezier/NURBS curve object**; the GN modifier
  lives on that curve object; a second Populate modifier stacks on top.
  **Replace this** (§7).
- Orientation for rollers/legs came from `Curve to Points` → `Rotation` with
  `twist_mode='Z_UP'`; orientation for populated items came from a *separate*
  hand-built frame off `Sample Curve` → `Tangent`. **Two orientation systems
  that had to agree and never quite did** — the central lesson (§4.1).
- One global `SCHEMA_VERSION` stamped on every node tree to force rebuilds
  when builder code changed. **Replace with per-tree versions** (§4.3).

---

## 4. Every problem v1 hit, its root cause, and the v2 rule that follows

This section is the reason v2 exists. Each entry: what happened → root cause →
rule for v2.

### 4.1 Populated items never sat right on curved + inclined paths (unsolved)
The user's screenshots repeatedly showed totes rolled sideways on turns, or
tilted so the rollers passed through them on inclines, while the conveyor
geometry itself always looked right. Chronology of attempts, all "verified"
numerically at the time, all rejected visually by the user:
1. `Align Rotation to Vector(axis=Y, pivot=Z)` — yaw only; items rode level
   through inclines (ignored the tangent's Z).
2. `pivot='AUTO'` — pitched correctly on straight inclines but **rolled
   sideways on flat horizontal turns**.
3. Explicit frame: `right = normalize(cross(tangent, world_up))`,
   `up = cross(right, tangent)`, `Axes to Rotation(Y→tangent, Z→up)` —
   numerically roll-free, but still visibly wrong in places on the real path.
4. Finite-difference tangent (sample position slightly before/after) to smooth
   segment-boundary jumps — the tangent of a `resolution_u`-discretized
   NURBS/POLY curve is a *step function* along the path.
5. Fine fixed-length resample (3 cm) of the path for all Populate queries —
   smooth motion, still "not realistic" per user.
6. Reusing `Curve to Points`' native Z_UP `Rotation` via a dense lookup table +
   `Sample Index(QUATERNION)` + a fixed +90° X remap onto the item's
   Y-forward/Z-up convention — **measured by rotating probe vectors through
   the result: the item's up left world-vertical on flat turns, i.e. it
   rolled.** Reverted to (3)+(5).
7. Also found and fixed: Lane/Height Offset was added in **world** space via
   `Set Position → Offset`; on a slope that sinks/floats the item. Must be
   rotated into the item's frame first (same bug class as the leg fix in 4.2).

**Root cause (the user's diagnosis, adopted):** deriving orientation from
sampled tangents of a freeform curve, with rollers and items using different
derivations. **v2 rule:** the path is a chain of analytic segments; every
point carries exact `heading` and `incline` scalars; **one** frame function
`Euler XYZ (incline, 0, heading)` orients rails, rollers, legs *and* items. Roll
is zero by construction; there is no tangent sampling anywhere in the
orientation path. Populate is built and visually verified **early** (§9).

### 4.2 Support legs placed on the wrong axis
`Set Position → Offset` with a raw world-space `(x, 0, 0)` only works when the
path runs along world Y. Fix: rotate the local offset through the point's
Rotation (`Rotate Vector`) first. **Rule:** any "local" offset (legs, lane,
height, guide-rail rise) is rotated by the point's frame before being applied.

### 4.3 Legs, rails and guide rails vanished after an unrelated change
Bumping the *global* `SCHEMA_VERSION` (for a Populate change) forced a
rebuild of the shared roller tree; the modifier's cached inputs — keyed by
socket identifier — were orphaned against the rebuilt interface and silently
reset to 0/False for every socket the operator didn't actively set
(Rail Height, Support Spacing, Guide Rails…). **Rules:** (a) version node
trees **per tree**, not globally; (b) the generate operator **re-asserts every
modifier input on every run** — never rely on a socket's default value
surviving; (c) after any rebuild, re-run generate on every object using that
tree.

### 4.4 A builder that raised mid-build left a broken tree marked "current"
`get_or_create_tree` cleared the tree and stamped the schema version *before*
the builder ran. A typo (`pivot_axis='AUTOMATIC'`, the real enum is `'AUTO'`)
raised halfway through; the half-built tree stayed stamped as current and was
silently reused for the rest of the session (every probe returned "0 items"
with no exception in sight). **Rule:** stamp a tree as built only as the
*last* line of a builder, after construction succeeded (`mark_tree_built`).

### 4.5 Reloading code did not reload it
`addon_disable`/`addon_enable` does not re-import submodules already in
`sys.modules`; Blender's own file watcher only re-execs `__init__.py`. Edits to
`operators/*.py` silently did nothing until the session was purged. **Rule:**
to reload, first
`for n in list(sys.modules): if n.startswith("bl_ext.user_default.conveyor_system"): del sys.modules[n]`,
then disable/enable, then force `build(rebuild=True)` on affected trees
(Python reload never touches existing node trees in `bpy.data`).

### 4.6 Probing GN results gave false negatives for hours
- `Object.to_mesh()` and `bpy.ops.object.convert(target='MESH')` do **not**
  realize `Instances`; on a mesh-type object `to_mesh()` also drops bare
  `Curve`/`Points` components. Everything built with Instance on Points looked
  like "0 items". **Rule:** to inspect GN output, copy the tree, insert
  `Realize Instances` (or `Points to Vertices`) right before Group Output,
  then `to_mesh()`.
- `Store Named Attribute` probes attached to the raw *curve* evaluated fields
  on the curve's control-point domain (2–3 points), then interpolated across
  the display mesh — garbage that looked like data. **Rule:** attach probes to
  the same geometry/domain the field actually runs on.
- Euler-angle readouts hid roll (gimbal coupling near ±90° yaw). **Rule:**
  verify orientation by rotating world `up`/`right` probe vectors through the
  Rotation and checking their raw direction (up must stay `(0,0,1)` on any
  level stretch; right must have `z = 0` everywhere).
- `Attribute Domain Size` returned 0 for a geometry built inside a nested
  field context (worked in isolation). Don't depend on it there.
- Probe tree copies accumulate as `Conveyor - Populate.001…`; delete them.
- Orthographic cameras looking down a path's length collapse every
  cross-section into one image; leftover viewport state corrupts
  `camera_to_view`. Frame renders explicitly and from the user's viewpoint.

### 4.7 Blender 5.3 API facts learned (verify again at build time)
- Modifier inputs: `modifier.properties.inputs[socket.identifier]["value"] = v`
  (not the old `modifier["Input_2"]`).
- `Resample Curve` **Mode is a menu socket**: `inputs["Mode"].default_value = "Length"`;
  `Curve to Points` mode is a Python enum (`.mode = 'COUNT'`).
- `Sample Curve` outputs: Value, Position, Tangent, Normal — **no Rotation**.
- `Curve to Points` (twist Z_UP) Rotation convention: **local Z → tangent,
  local X → across-width (horizontal)**. Cylinders (native Z axis) need a 90°
  Y pre-rotation to lie across the belt.
- `Align Rotation to Vector.pivot_axis` ∈ {'AUTO','X','Y','Z'}.
- `Axes to Rotation` exists (Primary/Secondary Axis inputs, `primary_axis`/
  `secondary_axis` props) — the right tool to pin two axes at once.
- `Sample Index` supports `data_type='QUATERNION'` for Rotation fields.
- `Object Info (As Instance)` drops the source object's scale (re-inject via
  its Scale output). `obj.bound_box` is pre-scale local space.
- `Curve to Points` in `COUNT` mode places points including both endpoints;
  `Resample Curve` by Length adjusts spacing so segments divide the length
  exactly. A raw `Points` component is invisible to `to_mesh()`.
- Socket `min_value` on `Speed` blocked negative values; remove it to allow
  reverse.

### 4.8 Live-update callback safety
Never delete/replace the object whose property `update=` callback is
running (real crash risk). v1 kept path-splitting (RAT insertion) a manual
operator and only allowed purely additive work (junction creation, endpoint
nudge) inside callbacks. **Rule stands** for v2.

### 4.9 Known gaps left in v1 (v2 should close or consciously defer)
Belt UV scroll not animated (shared material can't carry a per-object speed;
needs a shader-side attribute-driven offset); no MDR motor housing; diverter
geometry never built; no multi-lane populate; no modal draw tool; no swapping
a junction's module type; docs not updated for the last features.

### 4.10 Item forward-axis mismatch
The user's real asset `Eurotec_Tote` is 600 × 400 × 280 mm with its **long
axis on X**, while the system assumed items are Y-forward — hence a permanent
~90° Rotation Offset the user had to dial in. **Rule:** default the item's
forward axis to its longest horizontal bounding-box dimension; keep the manual
offset as an override.

### 4.11 Shared live session hazards
A cleanup sweep deleted the user's own test curve (recreated from captured
data, but it happened). Objects also disappeared between steps because the
user was editing concurrently. **Rules:** never bulk-delete by pattern in
the user's scene; prefix all test objects (`ZZ_Test_*`) and delete only those;
never assume an object still exists; restore any setting you change
(camera, modifier visibility, speed) at the end of every probe.

---

## 5. Catalog data (carry over as data; extend)

v1's `config/presets/*.json` (already in the folder) contain, with sources:
- **Widths** — ISO 400/500/650/800/1000/1200/1600 mm; CEMA 18"–72" (metric
  equivalents). Bulk-handling standards reused as the width dropdown; custom
  width always allowed, flagged as non-standard.
- **Roller duty classes** (unit handling, sourced): `light` Ø25 mm @ 28 mm
  pitch (Interroll roller track); `standard` Ø48.3 mm @ 76.2 mm (Hytrol 1.9");
  `mdr` Ø50 mm @ 76.2 mm (Interroll EC5000). "≥3 rollers under the smallest
  item" rule of thumb (unverified — keep flagged). Belt pulley Ø80 mm estimate
  (unverified).
- **Incline limits** — smooth belt 18°; cleated 30°; gravity/MDR roller and
  chain: flat-to-slight-decline only (no self-conveying incline).
- **Conveyor types** — ids `gravity_roller`, `powered_roller`, `belt`,
  `chain`, `right_angle_transfer`, `merge_junction`, `diverter`, with
  placeholder min bend radii (1500/1500/1000/1200 mm, unsourced).

**New for v2 — `segments.json`** (from a targeted research pass; keep flagged
as catalog-ish until confirmed against a specific catalog page):
- Curve angles offered by manufacturers: **30 / 45 / 60 / 90 / 180°**
  (Hytrol tapered-roller gravity curves and 199-CRRC live-roller curves list
  30/45/60/90; 180° via two 90°s or as a single module).
- Curve **inside** radii: standard range **24"–48"** (610 / 762 / 914 /
  1219 mm); offer metric 600 / 800 / 1000 / 1200 mm too. Centerline radius =
  inside radius + width/2. Gravity curves use tapered rollers.
- Straight sections: **600–3000 mm in 150 mm increments** (Monk); 10 ft /
  3000 mm is the common standard module (BestConnect); larger systems up to
  6000 mm.
- Inclines: rule of thumb **cartons ≤ 25°, plastic totes ≤ 15°**; smooth belt
  18–20°, rough-top 25–30°, cleated 45°+. Transitions use a **nose-over**
  (single nose-over up to ~15°, double for ~30°) — model the flat↔incline
  transition as a short vertical arc, not a hard kink, at least visually.
- Sources: Hytrol tapered roller curves (condrives.com), packagingconveyor.com
  gravity guide (24"–48" radii), Interroll SH1210 curve, Hytrol 199-CRRC
  (cisco-eagle.com), packagingconveyor.com incline guide, Remcon incline
  guide, Monk roller conveyor technical spec PDF, BestConnect 10' section
  (cisco-eagle.com).

---

## 6. v2 requirements that are new or sharpened

1. **Segment-based path** (§7). No freeform curve input in v2. A "convert
   freeform curve → segments" tool is phase 2, and must output segments.
2. **Single frame source.** One node group / function turns `(heading,
   incline)` into a Rotation. Nothing else computes orientation.
3. **Populate early** — build step 3, visually verified on a line containing
   a straight, a 90° curve, an incline and a decline, from the user's
   viewpoint, before belt/chain/modules exist.
4. **Per-tree versioning**, `mark_tree_built` semantics, and operators that
   re-assert every input (§4.3, §4.4).
5. **Item forward axis auto-detected** from the bounding box; manual offset
   remains (§4.10).
6. **Local offsets always rotated by the frame** (§4.2, §4.1.7).
7. **Nose-over transitions** between flat and incline segments (§5).
8. **Reverse (negative speed)** supported end to end; despawn/spawn at the
   line ends while moving; all items visible at rest.
9. **Testing protocol is part of the definition of done** (§10).
10. Keep everything the user approved in §2.2–§2.5.

---

## 7. v2 architecture

### 7.1 Data model
- A **conveyor line** is one Blender object (a POLY curve object, the
  *spine*) carrying a `PropertyGroup` with: conveyor type, width preset /
  custom width, speed, LOD, populate settings, start pose (location +
  heading), and a `CollectionProperty` of **segments**. Segment kinds:
  - `STRAIGHT(length_mm)` — snapped to 150 mm increments, default 3000.
  - `CURVE(angle_deg ∈ {30,45,60,90,180}, direction L/R, inside_radius_mm from
    catalog)` — horizontal only.
  - `INCLINE(angle_deg from the type's allowed set, length_mm)` — positive
    climbs, negative descends; with nose-over transitions.
  - `MODULE(kind ∈ {RAT, MERGE, DIVERTER}, footprint length)` — flat, straight.
- `model/segments.py` (pure Python, unit-tested) walks the chain from the
  start pose and returns a **Spine**: sampled centerline points with exact
  `heading`, `incline`, cumulative arc length `s`, and `segment_index`.
  Straights/inclines/modules contribute endpoints (heading/incline constant
  → linear interpolation is exact); curves are sampled every 2° (chord error
  < 1 mm at catalog radii); a pitch change emits a zero-length duplicate point
  so interpolation never smears pitch across a kink. Conventions:
  heading `h` = yaw about +Z, CCW from above, `h=0` travels +Y, LEFT increases
  h; incline `p` = pitch, positive nose-up; frame `R = Rz(h)·Rx(p)` = Blender
  Euler XYZ `(p, 0, h)`; `right = (cos h, sin h, 0)` (always horizontal);
  centerline radius = inside radius + width/2.
- `model/spine.py` writes the Spine into the line object's curve data as a
  POLY spline with per-point float attributes `heading`, `incline`, `arc_len`,
  int `segment_index` — the only thing GN ever reads.

### 7.2 Geometry Nodes
- `geonodes/frame.py`: `(heading, incline) → Rotation` via
  `Combine XYZ(incline, 0, heading) → Euler to Rotation`. Used everywhere.
- Cross-section builders (roller / belt / chain) sweep rails and guide rails
  along the spine (Curve to Mesh with a rectangular profile; the spine's
  attributes drive tilt), instance rollers/idlers/links at catalog pitch via
  `Resample Curve (Length)` → `Curve to Points`, orienting each with
  `frame(heading, incline)` (sampled attributes, not `Curve to Points'`
  Rotation), and place legs by rotating a local `(±offset, 0, 0)` through
  the same frame. Legs extend to floor (world Z=0) so they lengthen under
  inclines.
- `geonodes/populate.py`: items advance by arc length
  `(index·spacing + time·speed) mod usable_length`; position via
  `Sample Curve(Length)`, orientation via `Sample Curve` of the `heading` and
  `incline` **attributes** at that length → `frame()`; local
  (lane, height) offset rotated by that rotation; despawn window while
  moving; deterministic count from `Item Length`, `Spacing`, `Fill %` (floor
  the count, never randomly drop); forward axis remap from the operator.
- Modules (RAT / merge / diverter) are their own node groups placed at the
  segment's start pose with the frame's heading.
- Materials as in v1 (`geonodes/materials.py`, shared per role). Belt UV
  scroll: attempt a shader-side `Attribute`-driven offset so the shared
  material can stay shared; otherwise document why not.
- Per-tree `TREE_VERSION` constants; `mark_tree_built(tree)` as the builder's
  last line; `get_or_create_tree` never stamps.

### 7.3 Operators / UX
- **Conveyor Builder panel**: "New Line at 3D Cursor"; segment list
  (`UIList`) with Add Straight / Curve L / Curve R / Incline / Decline /
  Module, per-segment parameter fields (catalog dropdowns + custom), move
  up/down, delete. Every edit rebuilds the spine and re-asserts modifier
  inputs (live). The last segment's end pose is shown and is where the next
  segment attaches.
- **Junctions**: when a line's end pose lands within tolerance of another
  line's spine, snap and insert a MERGE module automatically (additive, safe
  in a callback); the module kind can be changed afterward.
- **Populate panel**: Pick Item, Spacing, Fill %, Rotation offset (auto-seeded),
  Populate / Clear.
- **Scene panel**: LOD override, Apply to All, Play/Pause, unit display.
- Phase 2: modal click-to-place tool that appends snapped segments; convert
  freeform curve → segments.

### 7.4 File structure
```
__init__.py                       registration list
blender_manifest.toml             2.0.0
config/  specs.py loader.py units.py presets/{conveyor_types,conveyor_widths,
         roller_specs,incline_limits,segments}.json
model/   segments.py (pure math, tested)  spine.py (writes curve+attributes)
geonodes/ builder_common.py frame.py materials.py populate.py
          cross_sections/{roller,belt,chain}.py modules/{rat,merge,diverter}.py
props/   line_settings.py (segments CollectionProperty + live callbacks)
         module_settings.py scene_settings.py preferences.py
operators/ new_line.py segments.py (add/edit/move/delete) build_line.py (hub)
           detect_junctions.py populate.py regenerate_all.py
ui/      panels.py (Builder, Populate, Modules, Scene)
utils/   probes.py (dev-only: realize+to_mesh, vector-probe helpers)
tests/   test_segments.py (+ more pure-Python tests as model grows)
docs/    ARCHITECTURE.md CONFIG_FORMAT.md CONVENTIONS.md (frame/heading math)
```

---

## 8. Acceptance criteria (per feature)
- **Frame:** on a level stretch, an item's up vector is exactly `(0,0,1)`
  regardless of heading; everywhere, its right vector has `z = 0`; on an
  incline of θ its up tilts by exactly θ about the horizontal across-axis.
  Verified by rotating probe vectors, and by a render from the user's angle.
- **Rollers/rails/legs:** legs on both rail lines, perpendicular to local
  travel, reaching the floor; rollers never intersect each other or the rails;
  smooth shaded; guide rails present and continuous.
- **Populate:** count deterministic; no overlaps; first item flush at start;
  items ride flat on the surface through straights, 90° curves, inclines and
  declines; motion smooth (no snapping) at 24 fps; despawn/spawn at ends while
  moving; reverse works.
- **Robustness:** rebuilding any tree never zeroes another object's inputs;
  a failed build never leaves a tree stamped current; a Python reload +
  regenerate restores the scene to the intended state.
- **Performance:** a 60 m multi-branch layout in Low Detail stays interactive.

---

## 9. Build order for v2
1. Scaffold (manifest, registration, empty panel). Confirm `model/segments.py`
   tests pass; add `spine.py` and a "New Line + Add Straight/Curve/Incline"
   panel that writes the spine curve with attributes. Verify attributes in
   Blender numerically.
2. `frame.py` + roller cross-section (rails, rollers, legs, guide rails) on a
   test line with straight + 90° curve + 15° incline + decline. **Render
   from the user's viewpoint.**
3. **Populate** on that same line, with the shipped placeholder totes AND the
   user's `Eurotec_Tote` (600×400×280, X-long) — orientation, height, spacing,
   motion, reverse, despawn. This step is the risk; do not proceed until the
   user confirms it visually.
4. Belt and chain cross-sections; nose-over transitions.
5. Modules: RAT, merge (auto-detect junctions), diverter.
6. Materials; belt UV scroll attempt.
7. LOD toggle + scene override; performance pass on a long layout.
8. UI polish, units display, docs (ARCHITECTURE, CONFIG_FORMAT, CONVENTIONS).
9. Phase 2 (only if asked): modal draw tool, curve→segments converter,
   multi-lane populate, MDR motor housings.

---

## 10. Working rules for the model building v2 (non-negotiable)
1. **Restate this brief in your own words, flag assumptions, propose any
   deviations from §7, and wait for confirmation before writing code.**
2. **Test in the user's live Blender through the MCP connector**, on every
   step, following §4.5 (reload recipe) and §4.6 (probe recipe). Purge
   `sys.modules` before disable/enable; force `rebuild=True`; re-run generate
   on all lines afterward.
3. **Numeric checks are necessary, not sufficient.** For anything visual,
   render from the user's viewpoint (perspective, framed on the area in
   question — not axis-aligned ortho down the path), compare against their
   screenshot, and end with "please look at it live". Do not say "fixed" or
   "verified" until the user has looked.
4. **Orientation checks use probe vectors**, never Euler readouts alone.
5. **Never bulk-delete in the user's scene.** Prefix test objects `ZZ_Test_`,
   remove only those, restore every setting you touched, delete probe tree
   copies (`*.001`).
6. Keep the Python-built node-tree approach, the `NodeGraph` wrapper idea,
   the config-data separation, and shared materials.
7. Default to no comments; when a decision is non-obvious (a Blender quirk, a
   convention, a rejected alternative) write a short *why* comment — v1's
   comments of this kind were what made the lessons in §4 recoverable.
8. Keep `docs/` current as features land (v1 fell behind).
9. Save cross-session lessons to memory as they happen (reload recipe,
   probe pitfalls, user preferences).

---

## 11. Open questions / assumptions to confirm at kickoff
- Segment authoring is panel-first (list + add buttons); the click-to-place
  modal tool is phase 2. OK?
- Curve segments are horizontal only; helical/inclined curves are out of scope.
- Nose-over transitions are modeled as short vertical arcs at a fixed
  transition radius per type (visual fidelity), not as separate catalog items.
- Junction auto-detect snaps a line's **end** onto another line's spine
  (endpoint-to-body), same as v1; endpoint-to-endpoint joins two lines into
  one chain instead. Confirm desired behaviour.
- Item forward axis = longest horizontal bbox dimension by default; confirm.
- Speed drives item flow and roller/idler spin; belt UV scroll is attempted in
  step 6 and may be deferred.

---

## 12. How to start
1. Read `model/segments.py` and run `python3 -m unittest tests/test_segments.py`.
2. Read `config/presets/*.json`.
3. Confirm the live Blender connection (`bpy.app.version_string`), the symlink
   target, and that the extension is currently disabled (it is — v1 code was
   removed from this folder; enable only once the scaffold exists).
4. Do step 1 of §10, then build order §9.
