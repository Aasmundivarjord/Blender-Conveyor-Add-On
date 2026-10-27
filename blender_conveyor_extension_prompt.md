# Build a "Path-Driven Conveyor System" Blender Extension

## 1. What you're building

Build a modern **Blender Extension** (targeting the current Extensions platform format, `blender_manifest.toml`, schema v1 — verify the current latest stable Blender version at build time, e.g. via `blender --version`, and target that plus reasonable backward compatibility) that lets a user design realistic, catalog-accurate warehouse conveyor systems entirely inside Blender, in minutes, without modeling or importing geometry from any external CAD tool.

The core interaction: the user draws a 3D curve through the scene (including lifting sections vertically for inclines/elevation changes), and the extension generates a fully detailed, render-ready conveyor line along it — frame, rollers/belt/chain, supports, and (optionally) goods flowing along it — driven by Geometry Nodes and parametrized by real conveyor specs.

**Primary use case:** fast, good-looking conveyor layouts for sales/proposal visualization, that also hold up as photoreal marketing renders and short walkthrough/product videos. This is a personal project for now (single user), but should be built cleanly enough to open-source later if it turns out well — so favor clean, documented, modular code over quick hacks, even though there's no license or public release commitment yet.

**Explicitly not required for v1:** bill-of-materials/parts-list export, company-specific integration, multi-user collaboration, or vendor-specific SKU matching. Keep the architecture open to these later, but don't build them now.

---

## 2. Prior art — read this, don't clone it

The closest existing product is **Configura CET**, specifically its **Material Handling** vertical and **Conveyors extension** — a standalone commercial CAD/space-planning platform (not a Blender add-on) used by material-handling integrators. It's documented as letting users click, snap, and stretch 2D/3D symbols that behave like real products inside warehouse layouts, with a Conveyors extension covering eight module categories: transportation (belt/roller/chain), accumulation, gravity (incl. spirals), sortation (crossbelt/shoe/linear-crossbelt), transfer (merge/divert/rotate), lift, chute, and pallet conveyors — with automatic multi-vendor spec/pricing and output as renders, fly-throughs, and 360° panoramas.
Sources: [CET Material Handling](https://www.configura.com/products/cet/material-handling), [Conveyors extension](https://www.configura.com/products/conveyors).

There are also existing (much simpler) Blender-marketplace Geometry Nodes conveyor assets, e.g. [3D Tudor's Conveyor Belt Geometry Node](https://superhivemarket.com/products/blender-conveyor-belt-geometry-node-by-3d-tudor/docs) and [Fab's Conveyor Belt Generator](https://www.fab.com/listings/b19a1d83-216f-4a7c-8bac-21774aaa98c7) — these do procedural belt/roller meshing but don't do path-based full-system design, catalog logic, merges, or a module library. That gap is the opportunity here.

**Use CET's module taxonomy (transportation / accumulation / gravity / sortation / transfer / lift / chute / pallet) as a reference for "what categories of conveyor modules exist in the industry"** so the extension's module library covers realistic ground — but design your own UI, own interaction model (see §4), own naming, and own visual style. Do not attempt to replicate CET's specific UI, icons, or workflow.

---

## 3. Core workflow & UX

1. **Draw the path.** A custom modal "Draw Conveyor Path" tool lets the user draw a 3D Bézier/poly curve directly in the viewport (click to add points, drag to set tangent handles, standard Blender curve editing afterward). Points can be placed at any height — lifting a point is how the user creates an incline/decline; there's no separate "incline tool," elevation is just part of the path.
2. **Path constrains itself to what the active conveyor type can physically do.** Once a conveyor type + width is assigned to a path (or segment), the path's editable curvature should be constrained/snapped to what that module can realistically achieve: minimum bend radius for a "smooth curve" section, maximum incline angle before the tool warns or auto-suggests cleats/a different module, and discrete-angle snapping (e.g. 45°/90°) where the conveyor type is inherently segmented (like a Right-Angle Transfer) rather than continuously curved. Surface this as soft snapping with visual feedback, not a hard block — sales visualization needs speed, not rigid CAD constraints, so warn/snap rather than refuse.
3. **Insert special modules by clicking a point on the path.** Clicking an existing point on a generated conveyor path opens a picker (pie menu or popup) of module types applicable at that point — merge/transfer junction, Right-Angle Transfer, diverter/sorter, incline break, spiral entry/exit, or a "connection stub" for linking to other warehouse equipment later. The chosen module replaces default geometry at that point with its own (still parametric) asset.
4. **Merges/branches auto-detect.** When two independently-drawn conveyor paths' endpoints (or a path endpoint and another path's midpoint) come within a snapping tolerance of each other, automatically generate an appropriate merge/transfer module joining them — but let the user click that auto-generated junction afterward to swap in a different, explicitly-chosen module type (auto-detect is the default behavior, manual override always available).
5. **Set conveyor type & width per path/segment** from an N-panel side tab ("Conveyor" tab): a dropdown for conveyor type (belt / gravity roller / powered roller (MDR) / chain / modular plastic belt), a width dropdown populated with real standard widths for that type (see §5), plus a "Custom…" option that unlocks a free numeric width field — width should be chosen based on the size of the totes/cartons/goods that will run on it, so tie width presets and the item-population system (§6) together.
6. **Populate with goods.** A "Populate Conveyor" operator scatters instances of tote/carton/box meshes along the path automatically, because a conveyor should rarely render empty. Controls: item mesh(es) to use (support multiple, randomly mixed), spacing/gap range (with randomization), lane offset if the belt is wide enough for multiple items across, and a "fill %" so the user can choose sparse vs fully loaded. This should work as a one-click default (sensible spacing based on the selected item size) with manual overrides available.
7. **Animate.** A single "conveyor speed" parameter (per path, in m/s or ft/min depending on unit system) drives: belt surface UV scroll (or chain/modular-belt segment animation), roller spin rate, and the populated items' movement along the curve (using the curve as a motion path, offset by time × speed). Provide simple play/pause and a speed slider in the N-panel; this doesn't need to be a physically-simulated belt, just visually-correct motion for renders/walkthroughs.

---

## 4. Conveyor types & module library (v1 scope)

Build the system generically — "conveyor type" should be a parameter/preset feeding one flexible Geometry Nodes cross-section-and-instancing system, not four separate hardcoded systems. v1 must cover:

- **Gravity roller conveyor** — idle rollers, frame, supports.
- **Powered roller conveyor (MDR)** — same as above with drive/motor detail added at intervals.
- **Belt conveyor** — frame, pulleys at ends, continuous belt surface, idler rollers beneath.
- **Chain / modular plastic belt conveyor** — link-plate or modular-tab belt surface, sprockets.
- **Curved sections** ("smooth" continuous-radius turns) for any of the above, generated by the path itself curving within that type's minimum-radius constraint.
- **Right-Angle Transfer (RAT)** as a discrete inserted module — a powered transfer head that lifts/diverts product 90° off the primary line (this is mechanically distinct from a smooth curved turn; model it as its own module, not a bent path). Reference: [Innoveyance RAT](https://innoveyance.com/product/right-angle-transfer-rat-conveyor-innoveyance/) (chain-driven transfer head), [Hytrol Transfers](https://hytrol.com/products/accessories/transfers/) (ball/belt/chain/roller transfer family).
- **Merge/transfer junction module** joining two paths (see §3.4).
- **Diverter/sorter module** (basic — full sortation logic is out of scope, just the visual module), e.g. skewed-roller diverter: [Roach skewed-wheel diverter](https://www.tceconveyors.com/roach-model-sd60-skewed-wheel-diverter).

**Explicitly phase 2 (design the module system to accommodate them, but don't build yet):** spiral (vertical) conveyors, lift/pallet conveyors, chutes, "connection to other equipment" stub modules.

---

## 5. Dimensional accuracy — research findings to use as a starting dataset

The user wants this to be **catalog-accurate**, not just visually plausible. Below is real reference data gathered for this spec — treat it as a verified starting dataset, but store it as **structured, editable config (e.g. a Python dict or JSON preset file), not hardcoded magic numbers**, so you (or the user) can correct/extend it as real manufacturer catalogs are consulted further during implementation. One important nuance to flag to the user in your build notes: most of the widely-documented standards below (CEMA/ISO) come from **bulk-material handling**, while this tool's actual use case is **unit/tote/carton handling** — belt-width standards transfer reasonably well, but roller diameter and pitch do not; unit-handling conveyors use much smaller rollers and tighter spacing than bulk conveyors. Call this out and default to sensible unit-handling proportions, doing a further targeted research pass (e.g. Interroll's package-handling roller/RollerDrive catalogs) before finalizing those specific numbers.

- **Standard belt widths:** ISO metric standard widths are commonly 400 / 500 / 650 / 800 / 1000 / 1200 / 1600 mm; CEMA (US, imperial) standard widths convert to metric equivalents such as ~1524 mm (60"). Off-standard widths carry real-world cost/lead-time penalties, which is a nice detail to preserve as flavor (e.g. flag non-standard custom widths in the UI) even though it doesn't need to affect anything mechanically. Sources: [Dry Cargo Mag — CEMA/ISO belt widths](https://www.drycargomag.com/belt-conveyor-widths-%E2%80%93-cema-and-iso-standards), [ANSI/CEMA 402 standard](https://cemanet.org/wp-content/uploads/2019/06/ANSI-CEMA-402-REVIEW-2019.pdf).
- **Roller diameters (bulk-handling reference):** commonly ~63.5 / 89 / 108 / 133 / 159 mm. **For this tool's unit/tote-handling use case, expect actual diameters closer to ~40–50mm** — verify against a package-handling catalog rather than trusting the bulk figure directly. Source: [MMSTACKER — metric roller dimensions](https://www.mmstacker.com/blog/conveyor-roller-metric-dimensions.html).
- **Roller pitch/spacing (bulk-handling reference):** ~1000–1500 mm for carrying idlers, 2000–3000 mm for return idlers on bulk belt conveyors — **again, unit-handling roller conveyors for totes/cartons use much tighter pitch** (commonly on the order of tens of millimeters up to ~150mm, driven by the rule-of-thumb that at least ~3 rollers must be under the smallest item at all times — verify this specific rule and exact figures against a real catalog before treating it as fact; flag it as an assumption in code comments until confirmed). Roller length typically exceeds belt/frame width by ~100–200 mm for mounting. Source: [MMSTACKER](https://www.mmstacker.com/blog/conveyor-roller-metric-dimensions.html).
- **Maximum incline angles:** smooth belt ~18–20° dry (less for round/unstable loads); cleated/chevron belts usable up to roughly 25–35° depending on material. Roller and chain conveyors generally cannot self-convey on any real incline without cleats or a positive-drive attachment — treat plain gravity/powered roller as flat-to-slight-decline only in the path-constraint logic from §3.2. Source: [Remcon — conveyor incline angle guide](https://www.remconequipment.com/guide-conveyor-incline-angle).
- **Right-Angle Transfer mechanism:** a powered head (chain- or belt-driven) rises to lift product and drive it sideways off the main conveying surface, rather than the conveyor path itself curving. Sources: [Innoveyance RAT](https://innoveyance.com/product/right-angle-transfer-rat-conveyor-innoveyance/), [Hytrol Transfers](https://hytrol.com/products/accessories/transfers/).
- **Manufacturers/terms worth pulling further reference geometry from during implementation:** Interroll (rollers, MDR — motor-driven rollers), Hytrol, FlexLink (modular chain/belt), Dematic, [Ultimation's MDR](https://www.ultimationinc.com/products-conveyor-systems/24v-motorized-roller-conveyors-mdr/) and [gravity roller](https://www.ultimationinc.com/products-conveyor-systems/gravity-roller-conveyor/) product pages, [iQS Directory's roller conveyor types overview](https://www.iqsdirectory.com/articles/conveyors/roller-conveyors.html).

**Width UI:** offer the standard preset widths above per conveyor type as a dropdown, plus an explicit "Custom width" numeric override — never force the user into only the standard list.

---

## 6. Materials & rendering

Ship a small set of ready-to-render PBR materials so a freshly generated conveyor looks good with zero extra work: brushed/galvanized steel (frame, rollers), black rubber (belt surface, with a subtle worn/grip normal map), painted steel or safety-yellow accents (guides, supports), and a neutral plastic (modular belt links, roller end caps). These should be real Blender material node groups shipped with the extension (not just flat viewport colors), usable directly in both EEVEE and Cycles. Keep them as separate, swappable material slots so the user can restyle without touching geometry.

---

## 7. Performance & level of detail

The tool must stay responsive both for a single short conveyor run and for long, multi-branch warehouse-scale layouts. Build a **High Detail / Low Detail toggle per conveyor module** (and ideally a global scene-level override), where Low Detail collapses individual roller/chain-link/belt-loop geometry into simplified proxy shapes (fewer instances, merged/decimated cross-sections) suitable for fast viewport work on large layouts, and High Detail realizes the full instanced geometry for final renders. Implementation notes from current Geometry Nodes best practice:

- Resample the path curve to even arc-length segments (Resample Curve by Length, not by Count) so roller/link pitch stays physically correct regardless of curve length or curvature — instance components (rollers, chain links) via **Instance on Points** at that fixed real-world pitch rather than a fixed instance count.
- Derive a stable per-point orientation from the curve tangent (with a controlled "up" vector, e.g. via Align Rotation to Vector combined with curve tilt) so the cross-section (frame + belt/rollers) sweeps cleanly through curves and inclines without twisting.
- Model merges/branches as **separate curve networks joined by an explicit module object at the junction** — Geometry Nodes curves don't natively branch, so the junction module (§3.4/§4) is what actually joins two distinct paths, not a single forked spline.
- Use a Switch/Menu node (or a boolean "Realize for Render" toggle wired through a modifier input) to gate the expensive high-poly geometry, and consider the newer **Repeat Zone** / **Bake** node functionality (introduced in Blender 4.2 and extended since) to cache expensive instancing results rather than recomputing every frame during animation playback.
- Target the current Blender feature set — verify the exact latest stable version at build time (this was Blender 5.2 LTS as of Sept 2026; check `blender.org/releases` for anything newer) — and use current Geometry Nodes capabilities (Bundles & Closures, native geometry import nodes, GN-based Curve to Tube / Array / Scatter-on-Surface modifiers where they simplify this system) rather than working around older limitations unnecessarily.

---

## 8. Units

Support both metric (mm/m) and imperial (in/ft), ideally following Blender's own scene unit settings automatically, with an explicit override in the extension's own preferences/N-panel if the user wants the conveyor tool's unit display to differ from the scene's grid units. All stored dimensional data (§5) should be kept in one canonical unit internally (recommend metric mm) and converted for display only.

---

## 9. Technical architecture summary

- **Package format:** Blender Extension using `blender_manifest.toml` (schema v1) — required fields: `schema_version`, `id`, `version`, `name`, `tagline`, `maintainer`, `type = "add-on"`, `license` (SPDX identifier — pick a placeholder GPL-compatible license now, e.g. `GPL-3.0-or-later`, since Blender's own extension platform requires GPL-compatible licensing if this is ever published, even though public release isn't committed yet); optional but relevant fields: `blender_version_min`, `website`, `tags`, `permissions` (declare `files`/`network` etc. only if actually used — this tool likely needs none). Source: [Blender manifest template](https://fossies.org/linux/blender/scripts/templates_toml/blender_manifest.toml), [Extension license requirements](https://docs.blender.org/manual/en/latest/advanced/extensions/licenses.html).
- **Geometry Nodes-driven**, with Python operators/modal tools handling the interactive parts (path drawing, point-click module insertion, populate operator, speed/animation controls) and driving Geometry Nodes modifier inputs rather than building meshes directly in Python.
- **Data layer:** a clear, separate config module (JSON or Python dataclasses) holding conveyor-type presets, standard widths, roller/pitch defaults, and incline limits from §5 — keep this decoupled from the node-tree logic so specs can be corrected/extended without touching the Geometry Nodes setups.
- **UI:** a dedicated "Conveyor" tab in the 3D viewport N-panel for per-path settings (type, width, speed, LOD, populate controls), plus a modal draw tool and a click-to-insert-module popup as described in §3.

---

## 10. Suggested build order (propose a more detailed plan before writing code)

1. Scaffold the extension (manifest, addon registration, empty N-panel tab).
2. Build the core path→cross-section Geometry Nodes system for one conveyor type (start with gravity roller — simplest cross-section) with width presets and arc-length-correct roller instancing.
3. Add belt, powered roller, and chain/modular-belt as additional presets of the same system.
4. Add incline/elevation handling and curve-radius constraints per type.
5. Add the click-to-insert module system, starting with one module (RAT), then merge/transfer junction with auto-detect.
6. Add width-driven item populate operator with a couple of placeholder tote/carton meshes.
7. Add animation (speed parameter → belt/roller/item motion) with play/pause.
8. Add default PBR materials.
9. Add High/Low Detail LOD toggle and verify performance on a long, multi-branch test layout.
10. Polish UI, write brief in-repo documentation of the config data format so specs can be extended later.

Before writing any code, restate your understanding of this spec back to me in your own words, flag anything ambiguous or any place you had to make an assumption, and propose the concrete file/module structure you intend to build — then proceed once that's confirmed.
