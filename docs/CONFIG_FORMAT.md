# Config format

All catalog data lives in `config/presets/*.json`, loaded once per session
by `config/loader.py` into the dataclasses in `config/specs.py`. Lengths
are millimeters. Every file carries `source`/`note` fields and a
`verified` flag where a value is an estimate; keep them honest.

## conveyor_types.json

`types[]`: `id`, `label`, `category` (CET taxonomy), `cross_section`
(`roller` | `belt` | `chain` | `module_*`), `default_duty_class` (key into
roller_specs), `width_groups` (keys into conveyor_widths groups),
`supports_continuous_curve`, `min_bend_radius_mm` (placeholder),
`angle_snap_deg`, `notes`. Types whose `cross_section` starts with
`module_` are not offered as line types.

## conveyor_widths.json

`groups.<group_id>`: `system` and `widths[]` of `{id, label, width_mm}`.
The width dropdown offers every group listed by the line's type plus
`Custom...`.

## roller_specs.json

`duty_classes.<class>`: `diameter_mm`, `pitch_mm`, `source`, `verified`,
`note`. The roller tree draws rollers at `pitch × 0.5` (visual density the
user asked for), floored at `diameter + 4 mm` so rollers never touch; Low
Detail uses `pitch × 2`.

## incline_limits.json

`limits[]`: `conveyor_type`, `max_angle_deg`, `note`, `verified`. Used for
the non-blocking warning under an incline segment.

## segments.json (new in v2)

- `straight`: `min_mm`, `max_mm`, `increment_mm` (length snap), `default_mm`.
- `curve`: `angles_deg[]`, `default_angle_deg`, `inside_radii[]` of
  `{id, label, radius_mm, system}`, `default_radius_id`. Centerline radius =
  inside radius + width/2.
- `incline`: `angles_deg[]`, `default_angle_deg`, `default_length_mm`,
  `nose_over_radius_mm` keyed by cross-section id plus `default`,
  `rules_of_thumb`.
- `modules.<KIND>`: `label`, `length_mm` (footprint along travel, fixed
  per kind), `allows_exit` (RAT only), `note`. Adding a kind also needs a
  builder in `geonodes/modules/` and an entry in
  `geonodes/cross_sections/common.build_modules`.
- `junction_snap_tolerance_mm`: how close a line's end must land to
  another line's body to auto-merge.
