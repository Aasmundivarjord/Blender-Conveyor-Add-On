"""The keys of build mode (operators/build_mode.py), pure so they are unit-tested: the PLAIN arrow keys
build -- up a straight, left / right a curve, down the piece library (the modules) -- Backspace or
Delete takes the last piece off, Enter or Esc ends. Shift + arrows tune the piece just added (a
straight's length, a curve's radius and turn) and Ctrl + up / down its height (Cmd on a Mac, where
macOS keeps Ctrl + up / down for Mission Control). Alt + arrows have their own keymap
(ui/segment_edit), Ctrl + Z is undo. Every other key and every mouse or trackpad event passes
through, so the view still orbits, zooms and pans."""
from __future__ import annotations

ADD = {'UP_ARROW': 'STRAIGHT', 'LEFT_ARROW': 'CURVE_LEFT', 'RIGHT_ARROW': 'CURVE_RIGHT'}
MORE = 'DOWN_ARROW'
REMOVE = ('BACK_SPACE', 'DEL')
END = ('RET', 'NUMPAD_ENTER', 'ESC')
TUNE = {'UP_ARROW': "longer", 'DOWN_ARROW': "shorter", 'LEFT_ARROW': "left", 'RIGHT_ARROW': "right"}  # with Shift
HEIGHT = {'UP_ARROW': "up", 'DOWN_ARROW': "down"}  # with Ctrl or Cmd

LENGTH_STEP_MM = 150.0  # the catalogue's straight increment
MIN_LENGTH_MM = 150.0
ANGLE_STEP_DEG = 15
MAX_TURN_DEG = 180  # a U-turn
RADIUS_STEP_MM = 100.0  # a custom radius (the standard ones step through the catalogue)
MIN_RADIUS_MM = 100.0
RISE_STEP_MM = 100.0
MIN_CLIMB_MM = 100.0  # a spiral or a lift climbs (or descends) at least this much

# The status bar while building (Blender draws it across the window's bottom).
HINT = ("Build mode:  ↑ Straight   ← Curve L   → Curve R   ↓ More   Shift+arrows Adjust last   "
        "Ctrl/⌘+↑↓ Height   Backspace Remove last   Enter / Esc Done")


def key_action(event_type: str, value: str, alt: bool = False, ctrl: bool = False, shift: bool = False,
               oskey: bool = False) -> str | None:
    """What an event does in build mode: 'add:<kind>' (a segment_add kind), 'more', 'remove', 'end',
    'adjust:<step>' (longer, shorter, left, right, up, down), or None (pass it through)."""
    if value != 'PRESS':
        return None
    if shift and not (alt or ctrl or oskey):
        return "adjust:" + TUNE[event_type] if event_type in TUNE else None
    if (ctrl or oskey) and not (alt or shift):
        return "adjust:" + HEIGHT[event_type] if event_type in HEIGHT else None
    if alt or ctrl or shift or oskey:
        return None
    if event_type in ADD:
        return "add:" + ADD[event_type]
    if event_type == MORE:
        return "more"
    if event_type in REMOVE:
        return "remove"
    if event_type in END:
        return "end"
    return None


def _next_radius(radius_id: str, radii, bigger: bool):
    """The next standard inside radius of the same system (metric / imperial), or None at the end."""
    current = next((r for r in radii if r[0] == radius_id), None)
    if current is None:
        return None
    same = sorted((r for r in radii if r[2] == current[2]), key=lambda r: r[1])
    k = [r[0] for r in same].index(radius_id) + (1 if bigger else -1)
    return same[k] if 0 <= k < len(same) else None


def adjust(piece: dict, step: str, radii=()) -> tuple[dict | None, str]:
    """What a Shift / Ctrl key does to the piece just added: ({field: new value}, what it now is) or
    (None, why not). `piece`: kind ('STRAIGHT', 'CURVE', 'SPIRAL', 'MODULE'), module (a MODULE's kind),
    length_mm, angle_deg, direction ('LEFT' / 'RIGHT'), radius_id ('CUSTOM' or a catalogue id),
    custom_radius_mm, rise_mm. `radii`: the catalogue's inside radii as (id, mm, system).
    - longer / shorter: a straight by the catalogue step, a curve to the next standard radius;
    - left / right: steer a curve, 15 degrees at a time (left turns it further left; through
      straight it flips side), at most a U-turn;
    - up / down: a straight's rise or drop, a spiral's or a lift's climb (which keeps its way)."""
    kind = piece.get("kind")
    if step in ("longer", "shorter"):
        sign = 1.0 if step == "longer" else -1.0
        if kind == 'STRAIGHT':
            length = max(round(float(piece["length_mm"]) / LENGTH_STEP_MM) * LENGTH_STEP_MM + sign * LENGTH_STEP_MM, MIN_LENGTH_MM)
            if abs(length - float(piece["length_mm"])) < 0.5:
                return None, f"The shortest straight is {MIN_LENGTH_MM:.0f} mm"
            return {"length_mm": length}, f"Straight {length / 1000.0:.2f} m"
        if kind == 'CURVE':
            if piece.get("radius_id") == 'CUSTOM':
                radius = max(float(piece["custom_radius_mm"]) + sign * RADIUS_STEP_MM, MIN_RADIUS_MM)
                if abs(radius - float(piece["custom_radius_mm"])) < 0.5:
                    return None, f"The tightest radius is {MIN_RADIUS_MM:.0f} mm"
                return {"custom_radius_mm": radius}, f"Curve radius {radius:.0f} mm"
            nxt = _next_radius(piece.get("radius_id"), radii, sign > 0)
            if nxt is None:
                return None, f"No {'larger' if sign > 0 else 'smaller'} standard radius: type one in the panel"
            return {"curve_radius": nxt[0]}, f"Curve radius {nxt[1]:.0f} mm"
        return None, "Shift+↑/↓ lengthen a straight or widen a curve"
    if step in ("left", "right"):
        if kind != 'CURVE':
            return None, "Shift+←/→ steer a curve"
        turn = int(round(float(piece["angle_deg"]))) * (1 if piece.get("direction") == 'LEFT' else -1)
        turn += ANGLE_STEP_DEG if step == "left" else -ANGLE_STEP_DEG
        if turn == 0:  # through straight: the other side
            turn = ANGLE_STEP_DEG if step == "left" else -ANGLE_STEP_DEG
        if abs(turn) > MAX_TURN_DEG:
            return None, f"A curve turns {MAX_TURN_DEG}° at most"
        side = 'LEFT' if turn > 0 else 'RIGHT'
        return {"curve_angle_deg": abs(turn), "curve_direction": side}, f"Curve {abs(turn)}° {side.lower()}"
    if step in ("up", "down"):
        sign = 1.0 if step == "up" else -1.0
        rise = float(piece.get("rise_mm", 0.0))
        if kind == 'STRAIGHT':
            new = round(rise / RISE_STEP_MM) * RISE_STEP_MM + sign * RISE_STEP_MM
            return {"rise_mm": new}, ("Level" if abs(new) < 0.5 else f"Rise {'+' if new > 0 else '-'}{abs(new):.0f} mm")
        if kind == 'SPIRAL' or (kind == 'MODULE' and piece.get("module") == 'LIFT'):
            what = "Spiral" if kind == 'SPIRAL' else "Lift"
            new = rise + sign * RISE_STEP_MM
            if abs(new) < MIN_CLIMB_MM or (new > 0.0) != (rise > 0.0):
                return None, f"{what}s climb at least {MIN_CLIMB_MM:.0f} mm (flip it in the panel to go the other way)"
            return {"rise_mm": new}, f"{what} {'up' if new > 0 else 'down'} {abs(new) / 1000.0:.2f} m"
        return None, "Ctrl+↑/↓ raise a straight, a spiral or a lift"
    return None, ""
