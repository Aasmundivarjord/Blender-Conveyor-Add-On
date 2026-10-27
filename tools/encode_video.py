"""Encodes the frames tools/showcase_capture.py wrote into an H.264 MP4 at
1920 x 1080, 24 fps, with Blender's own FFmpeg (headless, CPU). Not shipped.
  Blender -b --factory-startup --python tools/encode_video.py -- <out dir> [name.mp4]
"""
import os, sys
import bpy

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = ARGS[0]
NAME = ARGS[1] if len(ARGS) > 1 else "conveyor_showcase.mp4"
FRAMES = os.path.join(OUT, "frames")
files = sorted(f for f in os.listdir(FRAMES) if f.endswith(".png"))
if not files:
    print("ENCODE no frames in", FRAMES)
    sys.exit(1)

sc = bpy.context.scene
se = sc.sequence_editor_create()
strip = se.strips.new_image(name="capture", filepath=os.path.join(FRAMES, files[0]), channel=1, frame_start=1)
for f in files[1:]:
    strip.elements.append(f)
sc.frame_start, sc.frame_end = 1, len(files)
sc.render.fps, sc.render.fps_base = 24, 1.0
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1920, 1080, 100
im = sc.render.image_settings
if hasattr(im, "media_type"):
    im.media_type = 'VIDEO'
im.file_format = 'FFMPEG'
ff = sc.render.ffmpeg
ff.format = 'MPEG4'
ff.codec = 'H264'
ff.constant_rate_factor = 'HIGH'
ff.ffmpeg_preset = 'GOOD'
ff.gopsize = 24
ff.audio_codec = 'NONE'
sc.render.use_sequencer = True
sc.render.filepath = os.path.join(OUT, NAME)
bpy.ops.render.render(animation=True)
print("ENCODE wrote", sc.render.filepath, len(files), "frames", f"{len(files) / 24:.1f} s")
