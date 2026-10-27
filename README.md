# Path-Driven Conveyor System

Design catalog-accurate warehouse conveyor lines inside Blender in
minutes: chain real segments (straights, curves, inclines, modules), pick a
type and width, get a render-ready line with rails, rollers or belt or
chain, legs, guide rails and animated goods.

- **Requires** Blender 5.2 LTS or newer. Everything is Geometry Nodes built
  by the add-on: no external software, no network access.
- **Install**: Edit > Preferences > Get Extensions (search "Conveyor"), or
  Install from Disk with the downloaded .zip.
- **Quick start**: 3D Viewport > Sidebar (N) > **Conveyor** tab > **New Line
  at Cursor** (a cursor on the floor starts the line at a 0.8 m bed height),
  then just press the arrow keys: **↑** a straight, **← / →** a curve, **↓**
  the piece library, **Shift + arrows** adjust the piece just added,
  **Ctrl + ↑ / ↓** (**⌘** on a Mac) its height, **Backspace** takes the last
  piece off, **Enter** or **Esc** when done. Tick **Populate** for moving
  goods and press Play.
- **License**: GPL-3.0-or-later.

Some features talk to two optional companion add-ons by the same author,
Racks and Floorplan (rack ports, building floors and doors). Without them
those features simply stay out of the way.

## Use

1. Sidebar (N) → **Conveyor** tab (the version sits in its header) →
   **New Line at Cursor**. **Build mode** starts right away: the plain arrow
   keys build the new line -- **↑** adds a straight, **←** / **→** a curve,
   **↓** opens the piece library -- **Backspace** takes the last piece off
   again and **Enter** or **Esc** ends it (the status bar shows the keys).
   **Shift + arrows** adjust the piece just added: **Shift + ↑ / ↓** make a
   straight 150 mm longer or shorter (a curve's radius one catalogue size
   wider or tighter), **Shift + ← / →** steer a curve 15° further left or
   right (through straight it changes side, up to a U-turn). **Ctrl + ↑ / ↓**
   raise or lower the end of the piece 100 mm (a straight's rise, a spiral's
   or a lift's climb); on a Mac use **⌘ + ↑ / ↓**, since macOS keeps Ctrl +
   ↑ / ↓ for Mission Control. Hold a key to repeat it.
   Everything else works as usual meanwhile: orbit, zoom, pan, Ctrl + Z
   (one key a step). A line started on a junction's **+** or with **New
   Line from End** starts in build mode too, and **Build with Arrow Keys**
   (under the piece keys) builds the selected line again any time.
2. **Build.** The panel is ordered by what you do most, top to bottom:
   - the **piece keys**, laid out like a keyboard's arrow cluster:
     **Straight** above (forward), **Curve L** / **Curve R** left and right,
     **More** below -- the **piece library**, every piece type as a small
     rendered picture (Spiral, Right-angle transfer, Vertical lift, Buffer,
     angled-roller turn, Merge junction, Diverter, and the basics). The same keys
     work from the keyboard with the mouse over the viewport: **Alt +
     arrows**. With the LAST piece selected the keys extend the end (Curve
     L four times is a full circle); with any other piece selected they
     replace that piece;
   - right under them, the value for the piece you just made: a curve's
     angle (30/45/60/90/180) with its direction and radius, a straight's
     length with presets, a spiral's turn and height, a buffer's length and
     gap;
   - **Type** and **Width** of the line (the picture button beside Type
     opens the types as pictures; the transfer pull-down of a docked line
     has one too);
   - **Line** (direction, roller pitch, fences, nose-over, and how the line
     is docked), **Details** (the selected piece's exact values and module
     settings), **Populate**, **Pieces** (the list: reorder, duplicate,
     remove; closed by default) and **Scene**.
   **The viewport is the drawing.** Every piece of the selected line
   carries its dimension, CAD style: a dimension line with the length (and
   rise) beside each straight and module, the angle and radius at each
   curve, the turn and height at a spiral. **Click a dimension to type the
   value** (Enter applies; the straight snaps to the 150 mm catalog step).
   Hovering a piece outlines it; a click selects it; a **drag changes
   it**: a straight's length (150 mm steps) or a curve's angle (15° steps,
   1° with Shift); Esc or right-click cancels. The round **+** past the
   line's end opens the piece keys right there; a **+ outside a free face
   of a merge or diverter** starts another conveyor docked on that face
   (a one-sided junction becomes two-sided). Elevation: drag the blue arrow
   at a straight's end (nose-overs are added automatically). The ruler
   button in the panel's header (also Scene → Dimensions) switches the
   whole drawing layer off, like a CAD layer; it shows in Solid and
   Wireframe shading only and disappears by itself in Material Preview and
   Rendered shading. Zoomed out, pieces too short on screen for their
   figure keep it to themselves (the selected piece always shows its
   own); zoom in to read them all.
   **Growing backwards**: the keys add at the end; set **Add at → Start**
   (or press the round **+** before the line's start) and they add in
   front of the first piece instead -- the line grows backwards and
   everything already built stays exactly where it is. While Start is
   set, editing the first piece (its length, its angle) also keeps the
   rest in place; with End set the origin stays and the rest follows, as
   before. A line whose origin sits on a junction cannot grow backwards
   (its start IS the junction face): detach it first.
   The selected piece always wears an orange band, in Material Preview
   and Rendered shading too (only the measurements hide there).
   **Main line and connected lines.** With a line selected, the main line
   it hangs on gets an orange band and a "Main line" tag; the lines docked
   on it (feeders, branches) a blue band and their role. Hover one to light
   it, click it to select it.
3. **Attach a line to another by its origin** (the line's start, where
   the object's origin sits). Put the 3D cursor on a line and click **New
   Line at 3D Cursor**: the new line comes out square off it as a 90°
   merge. Or move any line (G) so its origin lands on or next to another
   line: it snaps onto that line's side right there, a junction module is
   added to the other line, its fence opens and the goods are linked.
   - **The junction icon** (a round gear button floating over the
     junction while the attached line or the main line is selected) opens
     the chooser: angle buttons 15-90°, the transfer type (angled roller
     merge, pop-up belt RAT, pop-up wheels, pop-up chain, high-performance
     divert, angled-roller belt, pusher -- the ones that need another angle show it and switch to
     it), Goods IN / OUT and Detach. The same chooser sits in the Builder
     panel. An angle button swings the whole line about its junction to
     exactly that angle (like R); the junction stays where it is.
   - **R rotates about the junction** in 15° steps (15/30/45/60/75/90°).
     When a line first attaches, the rotation decides the flow: the body
     swung UPSTREAM is a merge (goods run to the origin and into the other
     line), swung DOWNSTREAM an outfeed (goods leave the other line into
     it). From then on **you choose**: the Populate section of an attached
     line shows **Goods in / Goods out** -- pick the role there (below 90°
     the line swings to the mirrored angle; at 90° it stays and only the
     flow flips).
   - A junction needs room on one straight: where the end of a line aims
     at a piece joint, or a wider line needs a bigger junction, the
     junction slides along the other line (up to 1 m) and the line follows
     it.
   - **G slides the junction** along the other line; pull the origin away
     (more than the Dock Distance off its edge) to detach. An origin put on
     a junction's face (the + at a face, or by hand) attaches whatever the
     Dock Distance is: the faces of an angled merge sit well outside the
     edge. A two-sided junction is as wide as the wider of its two lines.
   - Attached lines follow the line they sit on when it is moved, rotated
     or edited, and lines can attach to attached lines (chains). Reversing
     the main line keeps them in place and swaps their roles.
   - A junction needs a level straight: on a curve or an incline the panel
     says so (it may slide up to 1 m along the line to fit).
   - **Rack ports** (the Racks add-on): put a line's origin on a rack's
     "out" port and it snaps there, as wide as the port, carrying the
     rack's load the way it travels, at the flow the port publishes (its
     Population at the line's speed), with its goods starting at the
     hand-over point; a reversed line on an "in" port, or a forward line
     whose end reaches one, feeds the rack. The Line section reads "Starts
     at Rack · aisle0_out" or "Feeds Rack · aisle0_in". New Line at Cursor
     with the cursor on a port starts the line on it. The rack's own panel
     and crane animation read the line's flow from the link the line
     writes, and the line takes the
     port's roller speed on docking so the hand-over has no speed step. A
     line can hold two ports at once (out of one rack, into another); a
     port takes one line (a second one sees "taken by …" with a Take over
     button); a rack that moves pulls its docked lines along, and a port
     that goes out of reach or disappears leaves "lost Rack · port" on the
     line until it is re-docked or dismissed. A free end within 2 m of a
     free port gets a hint and a Dock button. A rack that stores fewer
     pallets than the line brings holds the stream back, silently. A line
     feeding a rack also tells it exactly when each item arrives -- behind
     a divert too, where a 30 % branch gets items 3, 6, 9, 13 ... -- so the
     crane meets the real goods; with a merge on the way it tells the
     average.
     Every line also publishes its own ends as ports, its outline and its
     centreline, so stations and other add-ons can dock onto conveyors --
     and where lines join: every merge, divert and right-angle-transfer face
     a line docks on, with the share a branch takes, so Floorplan's goods
     flow and Racks see the same streams and splits as the animation.
   - **Lines laid out by another add-on**: Floorplan (or a script) can lay
     a line along a path of points. The line starts on the first point and
     ends on the last, with a standard curve at every corner (a smaller
     catalogue radius where a leg is short) and an incline where the height
     changes. A path the type cannot follow (a climb on rollers, a slope over
     the belt's limit, a leg too short for its curves) is refused with the
     reason and nothing is created. The Line panel says "Laid out by
     Floorplan along 6 points"; the pieces edit like any others.
   - **Buffer before a rack in-feed**: a crane stores only so many pallets
     an hour; a Buffer whose Output % lets out what the crane takes shows
     the pile-up on the conveyor side ("Full after 6 min, then holds 4").
   - **A right-angle transfer is a four-way node**: a RAT shows a + on each
     side face the line itself does not leave through. Click one and a
     conveyor of the RAT's own type and width starts there -- a branch
     taking its share of the goods (Goods in makes it a feeder instead).
     Drop a line of another width or type on a face and the face takes
     that width (the RAT grows, the line is never resized): a 1200 mm
     pallet line in on one face, an 800 mm roller line out on the next,
     the pallet leaving sideways without turning. A standalone RAT stands
     on its own legs under every free face with guards across them; a
     line may itself start with a RAT and dock on a face (a sorter grid).
     With Exit set to Straight both sides are free, and a second + beside
     the piece keys at its start and end starts a SEPARATE line there (a
     feeder the transfer carries on from, the takeaway after it). A corner
     transfer (Exit Left / Right) also offers its far face: a + there docks
     a line straight through, with its own width and goods -- two
     differently sized pallet lines on one transfer. A line docked on a face
     keeps its dock when it is renamed or made wider or narrower: the face
     follows its new width and the RAT grows or shrinks with it; a face
     whose line is deleted is its own width again. New Line from End keeps
     the line's type and width; make that takeaway wider or narrower after
     a transfer that turns and the transfer's exit side follows it. A
     transfer unit on its own (a line made only of the RAT) is as wide as
     the line feeding it, else as its takeaway; a RAT inside a longer line
     keeps that line's width at its start and end. Goods STOP on a
     right-angle transfer: they slow down onto its centre, stand while the
     belts rise under them (0.3 s for totes and cartons, as Interroll's
     RM 8731; slower for pallets), go out sideways on the raised belts and
     are set down at the deck's edge; on a reversed line they come in
     raised and are set down standing. The same happens wherever goods
     cross sideways: at a 90° pop-up divert, and on a branch off a straight
     transfer's side face, every item that leaves there stops on the
     centre, is lifted and goes out sideways; a 90° pop-up merge, or a
     feeder on a side face, brings its goods in raised and sets them down
     standing on the centre before they roll on. Goods that go straight on
     do not stop. The goods on a line through such a
     transfer keep far enough apart for it (length + width + the stop). A line whose end is moved up to a RAT's
     start face (within 8 cm, pointing on) feeds it: the RAT carries its
     goods on and snaps onto that end. A docked RAT end has no floor stand
     of its own -- the frame it docks on carries it. A standalone unit is
     guarded all round (side guards and guards across its start and end,
     each opening when a line docks there), and its pop-up belts show in
     their slots between the rollers at rest, so the unit reads as a
     transfer in a still picture.
   - **Pouch sorter** (Type: Pouch sorter (overhead)): an overhead rail on
     portal frames with trolleys carrying hanging pouches, one item per
     pouch, sorted by rail switches (the line's junctions, which keep the
     rail and nothing else). Place the line at the rail height -- its
     frames reach the floor. The pouch is a standard 400 × 600 mm bag
     (300 × 450 and 500 × 700 too, or a custom width × height), with its
     depth along the rail and the trolley pitch set per line. The goods
     are spaced one per pouch (a throughput below that leaves pouches
     empty) and ride inside them, turned across the rail.
   - Attaching links the goods: a merge onto a populated line starts
     populating, and populating a main line later switches on every line
     feeding into it; a branch (outfeed) takes its share of the main line's
     goods as soon as that line is populated (Route on the junction
     narrows it to one item class).
   - **Flow markers**: while a line is selected, every line shows where
     its goods come in and go out -- a disc, a join bar across the line
     and a 1 m arrow along the goods' travel at the flow start and the
     flow end, drawn like the Racks add-on's delivery points (orange = free,
     blue = docked) with a tag saying how full the stream is there
     ("in · 50 % · from Rack"). The round button on a disc opens that
     line's flow: direction, Population or Share, speed, populate. A RAT's
     faces are set one by one through the lines docked on them. A line's
     start or end dropped inside a marker's outer ring docks there (the
     same ring the racks draw). Scene panel: the Flow switch.
   - **A line that starts where another ends carries its goods on** (New
     Line from End: the takeaway conveyor after a right-angle transfer, the
     next floor after a lift): same goods, same speed, handed over at the
     end. It shows "Carries on from ..." in Populate. It follows that end
     when the first line is moved or edited; move it off the end yourself
     and it is its own line again.
   The far end of a line still docks the classic way: aim it at another
   line within the Dock Distance and it merges in (or, reversed, becomes an
   outfeed). On a line whose origin is attached, the far end only docks
   when drawn right up to the other line.
   Lines that dock onto each other share one stream of goods: one spacing
   and speed, every item slot owned by exactly one line, so merged goods
   never overlap, whatever item each line carries. 15-75° goods are turned
   onto the main line by the taper; a 90° (right-angle transfer) merge
   slides them across without rotating them.
   An outfeed with an eyedropped item takes every item of that kind off the
   main line automatically (cones out, cylinders stay).
   **Population and Speed** set the stream (Populate): its master -- the
   most upstream line, or the one **pinned as master** -- sets both, the lines
   connected to it follow; a branch takes its **Share of the master**, a
   feeder adds its own Population where it merges, all at the master's
   speed. A line that leaves a main line and merges back into it further
   on (a bypass) takes its share and gives it back; its goods keep pace
   with the main's, so they merge back into the very gaps they left.
   **Pallet wrapper** (More → Pallet wrapper): a conveyorised turntable
   stretch wrapper in the line, scaled to the line's width (a 1200 mm
   pallet line gets a 2 m turntable, a tote line the smallest 1.65 m unit):
   the chain conveyor across the table, the mast with the film carriage
   and roll, the control cabinet. Mode Wrap or Unwrap (a knife arm instead
   of the roll). Goods pass straight through at line speed. Modelled on the
   Handle It FA-4000 and Lantech Q Automatic class.
   **Buffer**: Module → Buffer / Accumulation: a zero-pressure
   accumulation zone with a blade stop at its end. Each zone is one item
   plus the Queue Gap (150 mm by default), with a black photo-eye on the
   right rail at the front of every zone (and its reflector opposite).
   It takes what the line before brings; its **Output** (0-100 %) is the
   share that leaves. The rest piles up over the animation -- the goods
   roll in, stop behind each other with their fronts at the sensors and
   step forward a zone at a time as the front one leaves -- until every
   zone is full; then it takes only what it lets out, the line before runs
   at that, and the queue holds ("Lets out 40 % of what arrives", "Full
   after 4 min, then holds 4"; "(after scene end)" when the scene's last
   frame comes first: playback never shows it full). Output 100 % lets the
   goods pass. Release Slug lets the zones go
   together. A buffer from before 2.24 with an Out rate of its own gets
   the Output % that rate was of what arrived; Auto becomes 100 %.
   **Junction technology**: every merge and divert has a Technology
   (angled roller merge, pop-up belt / wheel / chain transfer,
   high-performance divert, angled-roller belt, pusher), drawn the way the real units
   are built; its tooltip says what it suits.
   **Angled-roller align / turn**: Module → Angled-roller align / turn: Centre drifts the goods
   onto the centre lane; Turn left/right rotates them 90° in motion
   (tick Fixed pivot for the cheap pin variant).
   **Checks** appear only when something is off: a
   speed above the type's typical window, an item resting on fewer than
   three rollers (after a right-angle transfer its short side counts), a
   buffer on a belt line (a plain belt cannot accumulate), a 90° branch
   narrower than the item is long.
   **Legs** stand flush with both ends of every run (the end stand's outer
   face is the conveyor's end face, so a line butts cleanly against the
   next machine) and evenly in between, never further apart than the
   line's **Legs every** spacing (Line panel). **Supports: Floor / Ceiling**
   -- any line can hang from the ceiling instead: a cross member under the
   frame at every stand and two drop rods up to the first surface above
   (a mezzanine deck, a roof slab), else the clear height of the hall it
   stands in (Floorplan's Building publishes it), else the Scene panel's
   Ceiling level. The Line panel says which: "Hangs from 10.50 m ·
   Building clear height".
   A piece with **Legs** (or **Hangers**) off gets none, with a stand flush
   at each edge of the gap -- a tunnel or a walkway under the line. **Edit
   stands** puts buttons on the active line: a **−** on every stand (click:
   take that stand out), a **+** where one was taken out (click: put it
   back), and a smaller **+** in the middle of every gap between two stands
   (click: add a stand there -- under a heavy load, a joint, a long span;
   gaps under 0.6 m get none). An added stand's **−** takes it away again,
   and **Reset** in the Line panel brings back the plain spacing. Stands
   taken out or added stay when the line changes: they are kept on their
   piece; after a new spacing the planned stand nearest a removed spot
   goes, and an added one stays where it is. Spans over 3 m without a
   support get an alert.
   **Routing**: attach a line by its origin with its body swung downstream
   (an outfeed) and a **Diverter** module is added there. By default every
   such branch takes its **share** of the goods: the slots are dealt round
   robin over the branches and the main line's end (three branches: every
   fourth item carries on), so a sorter with many branches animates as one
   stream -- the branches' goods, speed and spacing follow the main line.
   In the diverter's box, **Route** = Carton / Tote (the placeholder items)
   sends one item class there instead; with a Route anywhere in a group
   the whole group routes by class. At a **90° divert** the goods ride to
   the transfer's centre, slide straight out on the raised belts without
   turning, and ride the branch sideways -- like off a real pop-up
   transfer; at 15-75° they are led onto the branch by the taper.
   **Detach** below the segment list undocks a line and keeps it where it
   is; **Dock** turns docking back on.
   **Fences** (guide rails) can be switched off per line next to Nose-over.
4. **New Line from End** starts a separate line exactly where the active
   one ends.
   **Spiral**: the Spiral button adds a helix; set the rotation in degrees
   (90/180/360/720/1080 buttons or any value), inside radius, direction and
   height (negative height winds DOWN, from an upper floor to a lower one). It hangs on its centre drum with cantilever arms every 45°; no
   floor stands around it.
   **Vertical conveyor (S / C)**: Module → Vertical conveyor, set the
   height, S (through: out on the opposite side, e.g. through a mezzanine)
   or C (same side), and which side the column stands on. It is a fork-column continuous
   vertical conveyor (Qimarox / Unitfine style): the line runs across the
   front of a flat column; tined forks come out of the column's opening,
   rise through the roller comb at the infeed, lift the goods off it
   without stopping, carry them level over the top wheel and set them
   down on the comb at the outfeed.
   S carries on in the same direction, C comes back out above the entry.
   (Also called an S-/C-conveyor or continuous vertical conveyor, about
   1,000-1,400 items/h; a cycle-based platform lift is a different, slower
   machine.)
   Forks ride the whole loop at the **Fork pitch** you set (400 mm by
   default, rounded so the goods land on every n-th fork), in step with the
   populated goods, and the column stands on the floor below. The column
   and the forks' bottom turn reach 0.56 m under the infeed: a line laid
   on the floor gets a "Raise the line" warning and hides the forks that
   would be underground. A new lift is 3 m tall. Works on any line type.
   **Floors / mezzanines**: legs and columns land on the first mesh below
   them automatically (a ground plane, a deck placed under a raised line),
   else on the Scene panel's Floor Level. Floorplan's slabs and Racks'
   walkway decks are always floors. With a mesh selected, the Scene panel
   offers **Floor / Not a floor / Auto**: mark a table or a machine top Not
   a floor and the legs pass through it. **Marked only** limits the floors
   to marked ones; **Floors** (a collection) restricts them to that
   collection and overrides the rest.
   Types: Roller (MDR -- motor-driven rollers, the workhorse for totes and
   cartons, 0.3-1.0 m/s), Belt (soft, small, fragile goods, inclines,
   0.5-2.0 m/s, transport only), Modular plastic belt and the overhead
   Pouch sorter (below).
   Straight lengths are typed in metres, any length.
   **Right-angle transfers move.** A RAT corner and every 90° pop-up belt /
   wheel / chain junction works like the real unit when the line is
   populated: the goods ride in on the rollers and stop on the transfer,
   the belts (blades, pulleys, wheel rows or chain strands) rise under
   them, carry them out sideways 12 mm above the rollers and lower again;
   goods coming in from the side are set down standing and roll on --
   timed to the item stream, so scrubbing the timeline works and nothing
   is simulated. The goods keep their orientation through a 90° transfer,
   so the line after one must take their long side: Populate says when
   goods are wider than the line they ride on ("Goods 600 mm across, line
   500 mm", and "Sideways after the 90° transfer" when that is why; a
   feeder says it about the main line it merges onto).
5. **Populate**: everything about the goods. The first row is the flow:
   Forward / Reverse on a free line, **Goods in / Goods out** on a line
   attached to another. Tick the checkbox -- it opens an eyedropper straight
   away: click the object the line should carry in the viewport (Esc keeps
   the placeholder totes and cartons). Click a **rack or other warehouse
   system** (the Racks add-on) instead and the line carries what that
   system delivers at the port nearest the line's start: its load object,
   the way it travels (a EUR pallet goes 0.8 m side first) and the flow
   its port publishes. A docked line without an item of its own carries
   what the main line carries: its goods ARE the main line's goods.
   **Population** (0-100 %) says how full the stream is: 100 % = the goods
   nose to tail with a 50 mm gap, 50 % = one item every two such places.
   **Speed** (m/s) drives rollers, belt and goods. The stream's **master**
   (its most upstream line, or the line pinned with "Pin as master") sets both; every
   line connected to it follows and says so ("30 % of Main", "Stream of
   Main", "Speed 0.50 m/s, from Main"; the master says "Master (first on
   the stream)" or "Master (pinned)"). A line carrying its master's goods
   shows its Populate box ticked and greyed, "goods from Main". A branch's
   **Share of the master**
   is the part of the master's goods it takes (0 = an equal split with the
   goods riding on); a feeder keeps its own Population, at the master's
   speed, and its goods add where it merges. The goods are dealt out
   evenly, item by item, the way the Racks and Floorplan add-ons count
   them, so every add-on sees the same items leave at a divert. Where a
   right-angle transfer's stop (or a pouch) cannot take the goods any
   closer, the stream runs as full as it can ("Runs at 72 % (capped)").
   A line starting at a rack's or door's delivery point follows it: the
   rack's Population leads the stream ("100 % of Rack · out0"; an older
   rate counts only where no Population is published), the line
   keeps its own Speed and shows the same goods as many per hour; a rack's
   in-feed that takes less holds the line back. Every line publishes the
   population it shows (a master its slider), its speed and its master pick,
   so the Racks and Floorplan panels show the same numbers. Other add-ons
   may set it (set_line_flow or the older set_line_rate, "Set by Racks"). A file from
   before 2.22 keeps its look: each line's Population is taken from its
   old Throughput or Spacing and Fill, once. The Placement sub-section
   holds forward axis, rotation and lane offset.
6. **Colours / materials**: the Material tab of a line has five slots
   (Frame, Rollers, Belt, Modules, Links). Change or replace them there;
   duplicates keep their own copy, linked duplicates share them. Changing a
   material on the main line recolours every line docked onto it.
   (Pieces → Duplicate copies every setting of a piece: a spiral's turns,
   a lift's shape and fork pitch, a junction's technology.)
   The keys set to **Start** grow the line backwards and mirror left and
   right (and a RAT's exit) to what you see looking back along the line.
   The N sidebar opens on the Conveyor tab whenever a conveyor line becomes
   the active object.
7. **Scene**: floor level and floors, dock distance, the **time scale**
   (operation seconds per scene second, shared with the Racks add-on: the
   goods, belts and rollers move that much faster on screen while every
   speed and rate stays real, so a crane at 50 loads/h and a line at 50/h
   show the same count; a change takes on the goods at once and every time
   the line publishes follows), Dimensions / Spine overlays, Play, Rebuild all. Roller density is set per line with
   **Roller pitch** in the Line section (the catalog pitch beside it).
8. **Reading the node trees**: open a line's Geometry Nodes modifier. The
   tree is laid out as numbered, coloured frames read left to right (1 ·
   Spine, 2 · Frame rails, 3 · Fences, 4 · Legs, 5 · Rollers, 6 · Modules
   ... Goods, Output); every stage has its own Inputs node showing just
   what it reads, and the frame at the top left ("How to read this tree")
   walks through the stages.

## Performance

The node trees are shipped pre-built, one library per Blender series
(`geonodes/library/conveyor_nodes-<major>.<minor>.blend`), and appended on
first use (a fraction of a second). Building them from the Python builders
(about 20 s for the first roller line) only happens when no shipped
library matches the code, e.g. after editing a builder without
regenerating the libraries (once in each supported Blender series).
Editing a line costs ~0.2 s end to end.

## Develop

- Pure math: `model/` (no Blender needed), e.g. the line layout in
  `model/segments.py`.
- Structure: every node tree is built in numbered stages (open a line's
  tree in the Geometry Node editor to follow them); the catalog is plain
  JSON in `config/presets/`.
- Supported: Blender 5.2 LTS and 5.3 (`blender_manifest.toml`); every
  release is tested on both.
