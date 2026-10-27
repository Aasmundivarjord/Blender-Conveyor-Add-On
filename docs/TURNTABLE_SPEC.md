# Turntable — one-page spec for approval (2026-10-26, paper only)

**The problem.** A 90° sideways transfer (a right-angle transfer, a 90° pop-up merge or divert)
moves the goods across without turning them, so on the next line a pallet rides crosswise and the
line publishes it turned (EUR1: `length_m` 1.2, `forward_axis` "Y"; tests/headless/test_goods_turned.py).
The decision: the turn happens ON THE CONVEYOR, stop → turn → go, timed like the 2.18 transfers, with
a pallet and a tote duration; after the turn the line publishes the load as it now rides (EUR1 back
to `length_m` 0.8, `forward_axis` "X"); R22.4 `delay_s` includes the turn time.

**What it is.** One mechanism, a stop with a turn, offered in two places:
1. **Turntable as the transfer technology** wherever goods already stop at 90°: the corner of a
   right-angle transfer, its side faces, and a 90° merge or divert (the "90° divert with turntable").
   The goods stand, the table turns 90° with them and they leave sideways riding exactly as they
   came in. Nothing arrives turned.
2. **Turntable piece** (piece library, under ↓ More): a square unit IN a straight run. The goods
   stop, a plate rises between the rollers, turns them 90° and sets them down, and they carry on
   straight. Turn: **Auto** (back to how they rode before the last sideways transfer, the default)
   or Left / Right 90°. For lines whose goods arrive turned from elsewhere.

Under the hood both are the right-angle transfer module (`RAT`) with a new **Transfer: Belt /
Turntable** setting; the piece is a RAT with exit Straight and Turntable preset. So docking, faces,
widths, the square footprint and the stop pipeline are reused: no new module kind, no enum or spine
code, no saved-file migration.

**Timing (catalogue defaults, vendor figures; verify with the supplier before quoting).**
- Totes / cartons: 2.5 s per 90° ([Robotunits R5R powered roller turntable](https://www.directindustry.com/prod/robotunits-gmbh/product-4566560-2550502.html)),
  settle and lift as the belt transfer (0.2 s + 0.3 s).
- Pallets: 4.0 s per 90° ([Marceau pallet turntable, "90° every 4 s"](https://www.directindustry.com/prod/marceau/product-24875-60767.html)),
  settle and lift as the chain transfer (0.5 s + 1.0 s). Slower tables run at 2.8–3.75 rpm (≈4–5.4 s per 90°).
- The goods class picks the duration (pallet loads vs. everything else). The panel shows it
  ("Turns 90° in 4.0 s"); a per-piece override is possible but not planned for v1.

**What changes in the flow (all existing hooks).**
- Stop: `model/transfer_motion` gets a `TURNTABLE` timing; the stop's `hold` = speed × (settle +
  lift + turn). `stream._transfers` adds it like every 2.18 stop, so pitch, extra slots and the
  `max_population` cap follow, and R22.4 `delay_s` includes the turn with no change to
  `arrivals_record` (it already adds the lag of every stop with `hold` > 0).
- The table must turn back empty before the next load (a corner table's rollers point the wrong
  way after the turn): the minimum pitch adds speed × turn time. That lowers the cap, which is
  published as `max_population`, as for any 90° stop today.
- Publishing: `goods_turned()` becomes "the yaw of the goods relative to travel at this port"
  (from the spine's `yaw_offset`, as the overhang check already does). So `line_in` can publish the
  load turned and `line_out` publish it straight. Today one load goes on every port of a line; the
  record format already has a load per port, so no warehouse_common change. **For the PM:** confirm
  that Racks / Floorplan read the load of the port they dock to.
- Branches: `branch_keep_yaw` is 0 behind a turntable (the goods turned with the table).
- Which load each reader takes (the PM's check, 2026-10-26):
  - Racks (`load_turned` / `arrives_turned`) reads the docking link's `load` first, else the
    line's end-port load at that dock. Our dock links carry no `load` (`ports._entries`), so Racks
    gets `line_out`, the post-turn load. v1 keeps links load-free and pins that in the test.
  - Floorplan and warehouse_common take a port node's item from that port's `load`, and a line's
    sections from `line_in`. Different `line_in` / `line_out` loads are fine for them.
- Only the INLINE piece makes `line_in` and `line_out` differ:
  - The RAT turntable (corner, sides, junctions) leaves the goods as they came.
  - Belt RAT corners keep today's whole-line rule (`goods_turned`: every port turned), so no
    existing scene changes.
- **Edge case (inline piece only).** An inline turntable is no section boundary, so
  warehouse_common sizes every section of that line with `line_in`'s item. A junction or a cap
  DOWNSTREAM of it on the same line is computed with the pre-turn length (e.g. turn the pallets,
  then a 90° divert into rack lanes on that line).
  - Our own drawn pitch is safe either way: `populate_item_length` takes the longer side along
    travel on a line with any turn.
  - v1: the inline piece shows "Caps after it use the pre-turn size" (35 characters) when a
    junction or a stop follows it on the same line. The README says to end the line at the
    turntable and carry on with New Line from End.
  - The clean fix, later: a boundary port `t:<uuid>` carrying the post-turn load (like the R22.6
    buffer ports). That is a contract and warehouse_common change.

**Animation.**
- Goods: a new per-transfer input `Transfer k Yaw`. During the stand the populate tree turns the
  item by Yaw × the stop's existing 0→1 progress, then the spine carries the new yaw onward.
  Populate `TREE_VERSION` +1.
- Table: the deck (disc, rollers or chains) visibly turns with the goods and back. The line trees'
  parts can only rise today, so every line tree gets a rotate-about-the-table-centre step and a
  `TREE_VERSION` +1. Then the node libraries are rebuilt in 5.2 AND 5.3.
- Geometry: new `model/turntable_parts.py` (square frame, round table on a slewing ring, roller
  deck for totes, chain deck for pallets, drive box, lift-and-turn plate for the inline piece),
  pure and unit-tested like `wrapper_parts.py`.

**UI.**
- RAT Details: "Transfer: Belt / Turntable", and the turn time as a dim note.
- The 90° merge/divert technology picker gets a Turntable picture.
- Piece library: "Turntable", with a pictogram and a 256 px icon.
- Inline piece: Turn Auto / Left / Right.
- All labels ≤ 36 characters.

**Tests.**
- Pure: timings and pitch with the return turn; the corner keeps the goods' yaw; the inline step;
  turntable_parts.
- Headless `test_turntable.py`, modelled on `test_rat_transfer` B, `test_goods_turned` and
  `test_arrivals_r22_4` D:
  - the stop holds for settle + lift + turn;
  - the goods' yaw goes 0 → 90° during the stand and they leave turned / un-turned as designed;
  - the EUR1 line publishes `length_m` 0.8 / `forward_axis` "X" after a turntable, and `line_in`
    still publishes turned;
  - measured arrivals == `delay_s` with the turn;
  - `max_population` drops by the return turn;
  - `run_sync` writes nothing per frame.
- GUI smoke adds the piece. Gates on 5.2.3 and 5.3.

**Effort.** About 5 days (4–6):
- ¾ d: catalogue, timings, settings → model;
- 1 d: geometry and pure tests;
- 1 d: stream, publishing per port, branches;
- 1 d: both node trees and the libraries in 5.2 + 5.3;
- ½ d: UI and icon;
- ¾ d: headless tests, gates, docs.

A **lean v1 of about 3 days** is possible: the RAT corner and the inline piece only (no 90° junction
technology), with the goods turning but the table drawn still (no line-tree change). Not
recommended: a deck that does not turn under a turning pallet looks wrong.

**Risks.**
- Turntables count toward the 6 stops per stream group (`TRANSFER_SLOTS`).
- Separate `line_in` / `line_out` loads need the readers' check above.
- The return turn can make a turntable corner the bottleneck: that is real, and shown.

**Questions for Åsmund.**
1. Scope: all 90° stops + the inline piece (recommended), or the lean v1?
2. Inline piece default Auto (undo the last sideways transfer)?
3. Durations: totes 2.5 s, pallets 4.0 s per 90°: OK as defaults?
