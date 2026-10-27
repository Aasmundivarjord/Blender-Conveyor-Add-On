# Path-Driven Conveyor System 2.26.4 (test release)

Lay out warehouse conveyor lines in Blender in minutes: draw a line piece by piece and the add-on
builds a render-ready conveyor with Geometry Nodes (frame, rollers or belt, guide rails, legs) and
goods that move along it.

## Install

1. Download `conveyor_system-2.26.4.zip` below (do not unzip it).
2. Blender 5.2 or newer: Edit > Preferences > Get Extensions > the arrow menu (top right) > Install from Disk, and pick the zip.
3. 3D Viewport > Sidebar (N) > **Conveyor** tab > **New Line at Cursor**, then press the arrow keys:
   up a straight, left / right a curve, down the piece library, Shift + arrows adjust the last
   piece, Ctrl + up / down (Cmd on a Mac) its height, Backspace removes the last piece, Enter or Esc
   when done. Tick **Populate** and press Play for moving goods.

## What to try

- Build a line with the arrow keys, dock a second line onto it (it snaps in as a merge or diverter).
- Right-angle transfers with lines on several sides, spirals, vertical conveyors, buffers.
- Legs: **Edit stands** in the Line panel, then − on a stand takes it out, + in a gap adds one.
- Pick your own model as the goods with the eyedropper.

## Feedback

Please open an issue (Bug report or Feedback) on this repository: what you built, what worked,
what was confusing, what you are missing. Screenshots help.

## Known limits

- The omni-wheel deck is hidden while it is redesigned; files that use it still open.
- Tested on Blender 5.2.3 LTS and 5.3 (macOS). Windows and Linux reports are especially welcome.

Free and open source (GPL-3.0-or-later).
