"""Suite UI rules (2026-10-13): contrast in both themes and multi-edit.
Headless: the viewport background is read from the theme, the side-panel
pictograms switch ink with the theme, and a side-panel edit on the active
line applies to every selected line (never a script's or an operator's edit).
The overlays themselves need a GPU: see tests/gui/screenshots.py and previews/.
Blender -b --python tests/headless/test_ui_theme.py"""
import bpy, traceback
from mathutils import Vector
PKG = "bl_ext.user_default.conveyor_system"
bpy.ops.wm.read_homefile(use_empty=True)
if PKG not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module=PKG)
from bl_ext.user_default.conveyor_system.operators.new_line import create_line
from bl_ext.user_default.conveyor_system.props import line_settings as LS
from bl_ext.user_default.conveyor_system.ui import theme, line_map
from bl_ext.user_default.conveyor_system._wh import contrast  # (moved to warehouse_common 0.3)
ctx = bpy.context; fails = []
def check(c, m):
    print(("ok   " if c else "FAIL ") + m)
    if not c: fails.append(m)
grad = ctx.preferences.themes[0].view_3d.space.gradients
saved = (grad.background_type, tuple(grad.high_gradient), tuple(grad.gradient))
try:
    # ---- the viewport background comes from the theme (no 3D view in -b: the theme's gradient)
    grad.background_type = 'SINGLE_COLOR'; grad.high_gradient = (0.95, 0.95, 0.95)
    check(abs(theme.viewport_background(ctx)[0] - 0.95) < 1e-3 and theme.palette(ctx)["light"], "a 0.95 background reads as a light theme")
    check(theme.palette(ctx)["stroke"] == contrast.INK_DARK and theme.palette(ctx)["halo"][0] == 1.0, "light theme: dark strokes, a white halo")
    grad.high_gradient = (0.188, 0.188, 0.188)
    check(not theme.palette(ctx)["light"] and theme.palette(ctx)["halo"][:3] == (0.0, 0.0, 0.0), "a 0.19 background reads as dark: light strokes, a black halo")
    grad.background_type = 'LINEAR'; grad.high_gradient = (0.9, 0.9, 0.9); grad.gradient = (0.8, 0.8, 0.8)
    check(abs(theme.viewport_background(ctx)[0] - 0.85) < 1e-3, "a gradient background is read as its middle")
    # ---- pictograms: dark ink on a light side panel, light ink on a dark one, redrawn when the theme flips
    def ink_of(icon_key):
        pv = line_map._pcoll[line_map._current[icon_key]]
        px = list(pv.image_pixels_float)
        lum = [contrast.luminance(px[i:i + 3]) for i in range(0, len(px), 4) if px[i + 3] > 0.9]
        return sum(lum) / max(1, len(lum))
    t = ctx.preferences.themes[0]
    def set_sidebar(rgb):
        for owner, name in ((t.user_interface, "panel_back"), (getattr(t.view_3d.space, "panelcolors", None), "back"), (t.view_3d.space, "button")):
            if owner is not None and hasattr(owner, name):
                cur = tuple(getattr(owner, name)); setattr(owner, name, tuple(rgb) + ((1.0,) if len(cur) == 4 else ()))
    set_sidebar((0.16, 0.16, 0.16))
    dark_id = line_map.picto("STRAIGHT"); dark_ink = ink_of("picto:STRAIGHT")
    check(dark_ink > 0.6, f"dark side panel: light pictogram ink (luminance {dark_ink:.2f})")
    check(line_map.picto("STRAIGHT") == dark_id, "the same theme reuses the drawn pictogram")
    set_sidebar((0.88, 0.88, 0.88))
    light_id = line_map.picto("STRAIGHT"); light_ink = ink_of("picto:STRAIGHT")
    check(line_map._signatures.get("picto:STRAIGHT") == "light" and light_ink < 0.05, f"light side panel: redrawn in dark ink (luminance {light_ink:.3f})")
    # ---- multi-edit
    lines = []
    for k in range(3):
        o = create_line(ctx, Vector((0.0, 4.0 * k, 0.0)), 0.0); o.name = f"Multi {k}"; lines.append(o)
    for o in ctx.view_layer.objects: o.select_set(False)
    for o in lines: o.select_set(True)
    ctx.view_layer.objects.active = lines[0]
    same = LS.selected_lines(ctx, lines[0])
    check([o.name for o in same] == ["Multi 0", "Multi 1", "Multi 2"], "the multi-edit set: the active line first, then the other selected lines")
    a = lines[0].conveyor_line
    a.speed_m_s = 0.8  # from a script (no side-panel region): only this line
    check(abs(lines[1].conveyor_line.speed_m_s - 0.8) > 1e-6, "a script's edit on the active line stays on that line")
    changed = LS.share_setting(a, "speed_m_s", same[1:])
    check(len(changed) == 2 and all(abs(o.conveyor_line.speed_m_s - 0.8) < 1e-6 for o in lines), "shared: speed on every selected line")
    a.conveyor_type = 'belt'; LS.share_setting(a, "conveyor_type", same[1:])
    check(all(o.conveyor_line.conveyor_type == 'belt' for o in lines), "shared: the conveyor type")
    a.width_preset = 'iso_800'; LS.share_setting(a, "width_preset", same[1:])
    check(all(o.conveyor_line.width_preset == 'iso_800' for o in lines), "shared: the width")
    a.guide_rails = not lines[1].conveyor_line.guide_rails; LS.share_setting(a, "guide_rails", same[1:])
    check(all(o.conveyor_line.guide_rails == a.guide_rails for o in lines), "shared: the fences")
    check(LS.share_setting(a, "speed_m_s", same[1:]) == [], "sharing an equal value changes nothing")
    lines[2].conveyor_line.conveyor_type = 'gravity_roller'
    a.roller_pitch_mm = a.roller_pitch_mm  # (belt: no rollers)
    before = lines[2].conveyor_line.roller_pitch_mm
    LS.share_setting(a, "roller_pitch_mm", same[1:])
    check(lines[2].conveyor_line.roller_pitch_mm == before, "a type-specific setting only goes to lines of the same type")
    check(all(n in LS.SHARED_SETTINGS for n in ("conveyor_type", "width_preset", "speed_m_s", "guide_rails")) and "throughput_ph" not in LS.SHARED_SETTINGS
          and "reverse" not in LS.SHARED_SETTINGS, "rates and direction stay per line (other add-ons set them through the operators)")
except Exception:
    traceback.print_exc(); fails.append("exception")
finally:
    grad.background_type, grad.high_gradient, grad.gradient = saved[0], saved[1], saved[2]
print("RESULT", "PASS" if not fails else f"FAIL {fails}")
