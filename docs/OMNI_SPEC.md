# Omni conveyors: redesign spec for approval (2026-10-27, paper only)

**The problem.** The "Omni-wheel sorter deck" looks nothing like a real omni conveyor, and it does not
work like one.
- **Wheels:** the wheels are plain 40 mm cylinders that only roll along the line.
- **Shape:** the deck is an ordinary line, a strip swept along a path.
- **Motion:** goods follow the spine like on any straight. On omni lines the transfer stops are even
  switched off (`operators/stream.py`, `_transfers`), so a RAT on an omni line turns its goods
  instantly at one point.

Real omni conveyors are different machines. They are surfaces that move every item in any direction,
lines dock on any edge, and the wheels visibly drive and reverse.

## What real omni conveyors look like (research, sources at the end)

**Three families**

| | A. Hex-cell field (celluveyor) | B. Square omni table (OMNIA / Rotacaster) | C. Swivel-wheel sorter (FORTNA, Hytrol, Transnorm) |
|---|---|---|---|
| Cell / module | Hexagons; "150" and "200" cells [1][5]; about 155–215 mm across flats (inferred from table sizes [6][33]) | 595/910 × 495/595/695 mm, 140 mm high [12] | Cassettes 300/400/500 × 200 mm [18] |
| Wheels | 3 driven double omni wheels per cell at 120°, axles radial, tops in one plane [3]; about 50 mm (inferred from photos) | Omni wheels on shafts in a checkerboard of two orientations [11]; 2 × 24 V MDR per module [12] | PU wheels on turntables, steered −90…+90° [18] |
| Drive | One motor per wheel; each cell gets a speed and a direction [34] | One (vx, vy) per module (inferred) | Each cassette gets a speed and an angle [18] |
| Speed / load | ≤ 1.15 m/s [1]; ≤ 400 kg/m², 18 kg per wheel [5] | < 2 m/s; 0.4–30 kg; 2,880–4,800 /h [12] | ≤ 2 m/s (1.0 at 90°); 50 kg [18] |
| Use | Big surfaces: singulate, crossdock N→M, depal, rotate [43][44][35] | Inline: 90° divert/merge, spurs, rotate, U-turn [12] | Inline divert at 20–90° |

**The wheel:** a hub with barrel-shaped passive rollers. Conveyor wheels are double-row, with 3
rollers per row offset 60° [3][9]. Common sizes are Ø48 and Ø80 mm (Interroll: black housing, grey
rollers [7]) and 50/125 mm (Rotacaster [10]). Colours: celluveyor orange [2], OMNIA blue [11].

**The deck:**
- A: light-grey plates with seams, the wheel tops showing about 10–15 mm through slots (inferred
  from photos [2]).
- B: a perforated aluminium plate with rounded-square cut-outs [11].
- Frames have sheet-metal skirts, tube guard rails on posts, and aluminium-profile legs [2].
- Big areas have an overhead 3D camera on a gantry [5].

**Motion:** each wheel's rim speed is the item's velocity at the wheel, projected on the wheel's drive
direction: s = (v + ω × r) · t [27] (inferred adaptation).
- In a hex cell the three speeds add up to zero. When an item moves along one wheel, that wheel
  runs at +v and the other two at −v/2: **wheels visibly reverse**.
- Goods slide sideways ("crab") without turning, unless they are rotated on purpose.
- A direction change takes about 0.2 s [34].

**What already exists:** family C, the steered-wheel divert inside a line, is already in the add-on as
a diverter technology (the swivel-roller cassettes in `model/transfer_parts.py`). This spec covers A
and B.

## Proposal

### 1. A real omni wheel and decks (all omni geometry)
- **The wheel:** a hub plus two rows of 3 barrel rollers, offset 60°, roller axes tangent.
  - Sizes 48 / 60 / 80 mm.
  - Rollers take the Rollers material, the hub the Frame material.
  - Built once as instances, so 300 wheels on 100 cells stay light.
- **Hex deck:** hex plates with seam lines and dark slots where the wheel tops show.
- **Square deck:** a plate with rounded-square cut-outs, wheels in a two-orientation checkerboard.
- **Frame:** skirts, plus tube guard rails on edges where nothing docks.

### 2. Omni Area (family A, and B as a grid of modules): a surface, not a line
- **New object:** a rectangle the user draws and resizes.
  - Settings: cell type (Hex 150 / Hex 200 / Square module), deck height, speed.
  - It has its own stand grid: legs under the skirts at most every Support Spacing, with the same
    bevelled posts and Floor/Ceiling rules as lines.
- **Connections anywhere:**
  - An in-feed docks by aiming its end at any edge; an out-feed docks by its origin on any edge.
  - The dock point is wherever the line meets the edge: today's dock flow with a new kind of target.
  - Each connection publishes a port, as junction faces do (R22.1). Panel labels stay ≤ 36 chars.
- **Goods across it:**
  - Every in-feed → out-feed pair gets a path across the surface: straight, or an S between offset
    docks.
  - It joins the in-feed's stream to the out-feed's, like a junction's continuation, so the 1D stream
    contract, shares (simple flow), arrivals (R22.4) and ports keep working.
  - Several in-feeds are merges and several out-feeds are a split, using the existing flow model.
  - Goods crab across without turning. "Rotate 90°" per path is an option, with timing from the
    turntable spec.
- **Wheel animation (stateless, scrub-safe, R5):**
  - Each cell takes the direction of the path over it. The first one wins where paths cross.
  - Its wheels spin at their projected speed s·t/R from the scene clock, so reversals show.
  - Cells under no path stand still.
  - Real cells only run under an item. Spinning along the path is the readable, stateless version
    (no simulation zone), and that is the trade-off.
- **Capacity:**
  - The panel shows the area's rate. The basis is about 6,000 /h for a crossdock-sized field [44],
    to be confirmed as a catalogue figure.
  - It warns when goods are smaller than one cell, because real fields need items of at least one
    cell size [5].

### 3. Inline omni module (family B): a piece in a line
- **The piece:** a square omni table, 600 × 600 mm by default, in the piece library. Appended to the
  module list (enum order rule).
- **Junction behaviour:** it works like a 90° junction on any face but **without a stop**. Goods slide
  diagonally to the branch at any angle from 0 to 90° (the left or right face, like a RAT's faces).
- **Animation:** the wheel checkerboard runs at (vx, vy) for the path in use.

### 4. Today's "Omni-wheel sorter deck" line type
A straight line of omni wheels has no real-world counterpart. Proposal:
- Retire it from the type list, as the cleated belt was retired in 2.26.1.
- Saved omni lines open as the inline module where they carry a RAT or junction, and as rollers
  elsewhere, with a one-time note.
- **Until the redesign ships:** hide the type in the public release, so the first impression on
  extensions.blender.org is not the old deck (Question 4).

## Effort
- **1. Wheel + decks:** about 3 d.
- **3. Inline module, plus retiring the line type:** about 4 d.
- **2. Omni Area:** about 10–12 d.
  - Object and UI: 2 d
  - Docking and ports: 3 d
  - Paths, stream and flow: 3 d
  - Wheel field and legs: 2 d
  - Tests, both Blender series, node libraries: 2 d
- **Total:** about 3½ weeks.
- **Suggested order:** 1 + 4 first (2.27, with or after the turntable), then 3, then 2.

## Risks
- A new object kind touches ports, stream, flow and docking: the biggest change since the 2.22 flow.
- Cell, wheel and item counts on big areas affect viewport speed. Instances throughout; a
  per-area wheel detail switch.
- The stateless wheel field is a simplification. Wheels under an empty part of a path keep turning.

## Questions for Åsmund
1. **Scope:** big surfaces (A) and inline modules (B), or one of them first? Recommended: B inline
   first (smaller), then A.
2. **Default look:** hex cells (celluveyor-like) or square tables? Wheel colour: orange, blue or
   grey?
3. **Goods rotation on the surface in v1,** or crab-only first?
4. **Public release 2.26.1:** hide the current omni type until the redesign (recommended), or ship it
   as is?

## Sources
1. https://cellumation.com/products/celluveyor/
2. cellumation product images (celluveyor cell, omni wheels, singulation, cv.GO), cellumation.com/wp-content/uploads
3. https://patents.google.com/patent/EP2874923A1/en
5. https://cellumation.com/faq/
6. https://factory-innovation.de/artikel/celluveyor-zellulare-foerdertechnik/
7. https://www.interroll.com/fileadmin/products/product_data/Wheels-series-2500/Series_2500_DE.pdf
9. https://trends.directindustry.com/omnitrack/project-54147-121834.html (search snippet)
10. https://og.mhi.org/media/members/17513/133180414725703656.pdf
11. https://www.omniawheel.com/conveyor-systems
12. https://og.mhi.org/media/members/17513/133180491039599115.pdf
18. https://fortna.com/wp-content/uploads/2025/01/DS-FORTNA-Wheel-Sorter-1-EN.pdf
27. https://modernrobotics.northwestern.edu/nu-gm-book-resource/13-2-omnidirectional-wheeled-mobile-robots-part-1-of-2/
33. https://www.ifoy.org/bewerbungen/2013/882/ (system description, search snippet)
34. https://cellumation.com/products/go/
35. https://beschaffung-aktuell.industrie.de/artikel/foerdertechnik-auf-kleinstem-raum/
43. https://cellumation.com/products/cv-singulate/
44. https://cellumation.com/products/cv-crossdock/
