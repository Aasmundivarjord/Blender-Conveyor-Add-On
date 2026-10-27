"""The hand-over clock between a conveyor stream and a rack's crane
(the same clock the Racks add-on uses for that hand-over), pure Python.

Scene time t (seconds, frame / fps). Operation time T = (t - t_start) x
scale, t_start = frame_start / fps, scale = the scene's wh_time_scale.
The stream's slot j has its centre at (j A + v_s (t - phi)) mod W + inset
(A = the slot pitch, v_s = speed x scale on screen, phi = Stream Phase in
scene seconds, W = the wrap, a multiple of A). A rack publishes the
operation times its loads cross an "out" port: phase_s + k period_s; the
line sets phi so a slot centre is at the port then. A line ending at an
"in" port publishes the same for its own goods.
"""
from __future__ import annotations


def stream_phase_scene_s(t_start: float, phase_op_s: float, scale: float, inset_m: float, u_port_m: float,
                         speed_m_s: float, pitch_m: float) -> float:
    """phi (scene seconds, in [0, slot period)) so a slot centre sits at
    stream coordinate `u_port_m` at operation time `phase_op_s`."""
    v_s = speed_m_s * scale
    if v_s <= 1e-9 or pitch_m <= 1e-9:
        return 0.0
    period_scene = pitch_m / v_s
    t0 = t_start + phase_op_s / scale
    return (t0 + (inset_m - u_port_m) / v_s) % period_scene


def crossing_phase_op_s(phase_scene_s: float, t_start: float, scale: float, inset_m: float, u_port_m: float,
                        speed_m_s: float, pitch_m: float) -> tuple[float, float]:
    """(phase_s, period_s) in operation seconds: a slot centre crosses
    `u_port_m` at phase_s + k period_s for every integer k."""
    v_s = speed_m_s * scale
    if v_s <= 1e-9 or pitch_m <= 1e-9:
        return 0.0, 0.0
    period_op = pitch_m / speed_m_s
    t = phase_scene_s + (u_port_m - inset_m) / v_s
    return ((t - t_start) * scale) % period_op, period_op
