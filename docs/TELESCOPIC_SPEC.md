# Telescopic dock conveyor — one-page spec for approval (2026-10-12, paper only)

**What it is.** A new conveyor type `telescopic`: a fixed base at a dock door with 2–5 nested
belt booms that extend into the trailer. For cartons, parcels and totes loaded or unloaded by
hand at the tip; never pallets. One machine per line (no segment list); an ordinary line docks
behind its base as the takeaway or feed.

**What the user sees and clicks.**
- Type "Telescopic belt" in the Type list, or *New Line at 3D cursor* with the cursor on a dock
  door port (places it docked, as for any port today).
- Panel: **Booms** 2–5 · **Retracted length** (catalogue) · **Extension** 0–100 % (slider; the
  booms slide out outermost first) · **Tip hinge** −15…+15° (the last boom tilts down to the
  trailer floor or up to a high stack) · **Belt width** 600 / 800 / 1000 mm (EU), 30" / 36" (NA)
  · Speed · Populate as today.
- Look: base on fixed legs at 0.8 m belt height, nested box sections with the belt on top, a
  hinged nose with an operator platform at the tip, belt scroll animated like the belt type.
  Goods ride tip → base (unloading) or base → tip (loading).

**What it docks to.** Floorplan dock-door ports (`doorN`, `z_free`, informational
`handling: "telescopic"`). The base's door-side end takes the port's XY and heading and keeps
its own height (R16). Direction follows the door's role automatically: an inbound door (port
role `out`) = unloading, flow from the tip into the hall; an outbound door (role `in`) =
loading, flow from the hall to the tip. `handling: "telescopic"` only shows "telescopic
recommended" on the dock row and on a plain line docked there; never a requirement. The line
publishes `line_in` / `line_out` at its hall end only (the tip is inside the trailer).

**Goods direction and rates.** Rate from the door port (`rate_ph`) capped by manual handling:
default 900 parcels/h per conveyor, editable, with the bottleneck shown as for junction
technologies (vendor figures: 1,200/h per conveyor; 1,800–2,500/h peak per operator). A pallet
load on the port is refused with a hint ("telescopic belts carry cartons").

**Catalogue defaults (vendor and distributor pages; verify with the supplier before quoting).**

| | EU | NA |
|---|---|---|
| Belt width | 600 / 800 / 1000 mm (range 600–1000; used Caljan units 600, 785, 820 mm) | 30" (762 mm), 36" (914 mm) |
| Booms, retracted / extended | 2: 5.0 / 12.0 m · 3: 6.5 / 16 m · 4–5: 8–10 / 21–24 m | 3: 16 m, 4: 21 m (reaches within 5–6 ft of a 53 ft trailer nose) |
| Tip | elevation ±10° typical (UI allows ±15°), head height 1.1–2.4 m | same |
| Belt speed | 0.3–0.6 m/s | same |
| Width of the machine | belt + 250 mm (used unit: 820 mm belt, 1,050 mm overall) | same |

Sources: [Caljan Performer](https://caljan.com/we-offer/telescopic-conveyors/caljan-performer)
(configurable, 5-section greatest reach, into a 53 ft trailer), [used Performer listing](https://www.machineseeker.ie/caljan-performer/i-22282622)
(15.7 m, 1,050 mm wide), [RKLoad / Parcel+Post Expo](https://parcelandpostexpo.com/exhibitor-news/best-telescopic-belt-conveyor-manufacturers-for-truck-loading-docks)
(belt 600–1000 mm, reach 8–24 m, 1,800–2,500 parcels/h per operator), [third-party spec table](https://hoj.net/pages/telescopic-conveyor)
(Caljan up to 21 m, "Classic" 16 m, 1,200 pieces/h, elevation 10°), [UniTel TBC datasheet](https://unitelegypt.com/images/catalog_pdf/TBC%20Telescopic%20Belt%20Conveyor.pdf)
(2-boom 12.0 m extended, head 1,100–2,400 mm), [MaxxReach FAQ](https://raymondwest.com/-/media/dealers/handling-systems/literature/telescopic-faq.pdf)
(53 ft trailer reach, articulating snout), [Spudnik 1300](https://www.spudnik.com/es/producto-spudnik/1300-van-unloader/) (30" belt).

**Effort.** M–L, about 3 days: 1 d geometry (base, nested booms, extension, hinge in Geometry
Nodes), 1 d docking and flow (door roles both ways, R16, the takeaway dock at the base,
`wh_ports`), ½ d catalogue and panel, ½ d headless tests with a real Floorplan dock row.

**Left for later.** Extension animated over time (boom travel 15–25 m/min) and an operator
figure; the tip following a stack height automatically; robotic unloaders (Caljan
AutoUnloader, Körber ErgoUnload class); imperial lengths in the UI beyond the width presets.
