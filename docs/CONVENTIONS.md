# Conventions: frame, heading, incline

These conventions are shared by `model/segments.py`, `model/spine.py`,
`geonodes/frame.py` and every builder. Change all of them or none.

## The one frame

A point on a line carries two scalars:

| symbol | attribute | meaning |
|---|---|---|
| `h` | `heading` | yaw about +Z in radians, counter-clockwise from above. `h = 0` travels along +Y. Turning LEFT increases `h`. Cumulative, never wrapped. |
| `p` | `incline` | pitch in radians, positive = nose up. |

The rotation at that point is Blender Euler XYZ `(p, 0, h)`, i.e.
`R = Rz(h) · Rx(p)`. Consequences:

- `forward = R·(0,1,0)` follows the slope.
- `right   = R·(1,0,0) = (cos h, sin h, 0)` is always horizontal, so roll is zero by construction.
- `up      = R·(0,0,1)` is the conveying-surface normal.

`geonodes/frame.py` is the only node group that turns `(heading, incline)`
into a Rotation. Rollers, legs, modules and transported items all use it.
Nothing samples a curve tangent for orientation.

## Swept geometry

`Curve to Mesh` orients its profile from the curve normal: profile X maps
onto the normal, profile Y onto `tangent × normal`. The line trees feed
`Set Curve Normal` (Free) with the frame's LEFT vector, so profile X = left
of travel and profile Y = up. This was probed live on 5.3: a normal of
`(1,0,0)` along a +Y curve sends profile +Y to -Z.

## Item yaw

`yaw_offset` is the extra yaw a transported item carries relative to the
travel heading. It is 0 until the line passes a right-angle transfer; a
RAT pushes product sideways without turning it, so after a LEFT exit the
heading has gained +90° and `yaw_offset` has lost 90°. Extra yaw (RAT
offset, the item's forward-axis remap, the manual Rotation Offset) is
applied in the item's LOCAL frame after the tilt: `Rz(h)·Rx(p)·Rz(yaw)`.

## Vertical reference

The spine's z IS the conveying surface (top of rollers / belt). Items sit
on it with zero height offset; frame rails hang below it by `Rail Top
Drop`; legs run from the rail bottom to the world floor (`Floor Z`).

## Spine sampling

Straights, inclines and module footprints contribute their end point only
(linear interpolation of constant heading/incline is exact). Curves and
nose-over arcs are sampled every 2°. With a zero transition radius a pitch
change emits a zero-length duplicate point carrying the new incline.

## Units

Millimeters everywhere in config and PropertyGroups. `config/units.py`
converts to Blender units at the boundary (`mm_to_bu`, `bu_to_mm`) and
formats for display honoring the scene or the add-on preference.

## Object transform = start pose

A line object's location and Z rotation are its start pose. X/Y rotation
and scale are locked; a tilted object would reintroduce roll.
