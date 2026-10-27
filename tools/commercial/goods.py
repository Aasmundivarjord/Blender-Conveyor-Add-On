"""Real goods for the promo shots, each one object a line carries through the add-on's own Pick
(populate_item): a blue stacking bin, a lidded tote, taped cartons, an envelope, a EUR pallet and a
pallet load. Built from bevelled boxes with bmesh, origin at the base centre, the long side along X.
The sources sit 20 m under the studio floor, out of sight: the lines instance them.
Not shipped. Imported by tools/commercial/shots.py."""
import bmesh
import bpy
from mathutils import Matrix, Vector

HIDE = (0.0, 0.0, -20.0)  # under the studio floor

BLUE = (0.02, 0.30, 0.90)
TOTE_GREY = (0.30, 0.32, 0.35)
KRAFT = (0.50, 0.33, 0.17)
TAPE = (0.70, 0.56, 0.36)
WHITE = (0.88, 0.88, 0.86)
INK = (0.08, 0.08, 0.09)
STAMP = (0.75, 0.10, 0.08)
WOOD = (0.60, 0.46, 0.30)


def material(name, color, roughness=0.5, metallic=0.0):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
    return mat


class Parts:
    """Boxes (bevelled, each with its material slot) gathered into one mesh object."""

    def __init__(self):
        self.bm = bmesh.new()
        self.mats = []

    def slot(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def box(self, centre, size, mat, bevel=0.004, rot_z=0.0):
        m = Matrix.Translation(Vector(centre)) @ Matrix.Rotation(rot_z, 4, 'Z') @ Matrix.Diagonal((*size, 1.0))
        before = set(self.bm.faces)  # not face tags: bmesh's bevel clears them on every face
        geom = bmesh.ops.create_cube(self.bm, size=1.0, matrix=m)
        if bevel > 0:
            edges = list({e for v in geom["verts"] for e in v.link_edges})
            bmesh.ops.bevel(self.bm, geom=edges, offset=min(bevel, min(size) * 0.45), segments=2, affect='EDGES', profile=0.5)
        idx = self.slot(mat)
        for f in self.bm.faces:
            if f not in before:
                f.material_index = idx
        return self

    def mesh_part(self, verts, faces, mat):
        """Raw polygons (a hollow bin)."""
        vs = [self.bm.verts.new(v) for v in verts]
        idx = self.slot(mat)
        for f in faces:
            self.bm.faces.new([vs[i] for i in f]).material_index = idx
        return self

    def build(self, name):
        me = bpy.data.meshes.new(name)
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
        self.bm.to_mesh(me)
        self.bm.free()
        for mat in self.mats:
            me.materials.append(mat)
        for p in me.polygons:
            p.use_smooth = True
        o = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(o)
        o.location = HIDE
        return o


def _ring(hx, hy, z):
    return [(-hx, -hy, z), (hx, -hy, z), (hx, hy, z), (-hx, hy, z)]


def bin_(name="Blue bin", size=(0.60, 0.40, 0.28), color=BLUE):
    """An open stacking bin: tapered walls, a thick rim, ribs on the long sides, handle slots."""
    L, W, H = size
    t, draft = 0.012, 0.018
    blue = material("Goods bin", color, roughness=0.42)
    dark = material("Goods bin slot", (0.01, 0.03, 0.10), roughness=0.6)
    ob, ot = _ring(L / 2 - draft, W / 2 - draft, 0.0), _ring(L / 2, W / 2, H)
    it, ib = _ring(L / 2 - t, W / 2 - t, H), _ring(L / 2 - draft - t, W / 2 - draft - t, t)
    verts = ob + ot + it + ib
    faces = [(3, 2, 1, 0)]  # outer bottom
    for i in range(4):
        j = (i + 1) % 4
        faces.append((i, j, 4 + j, 4 + i))           # outer wall
        faces.append((4 + i, 4 + j, 8 + j, 8 + i))   # rim
        faces.append((8 + i, 8 + j, 12 + j, 12 + i))  # inner wall
    faces.append((12, 13, 14, 15))  # inner floor
    p = Parts().mesh_part(verts, faces, blue)
    rim = 0.035
    for sy in (-1, 1):  # the stacking rim and the ribs on the long sides
        p.box((0, sy * (W / 2 + 0.004), H - rim / 2), (L + 0.008, 0.012, rim), blue, bevel=0.003)
        for k in range(-2, 3):
            p.box((k * L / 5.2, sy * (W / 2 - draft / 2 + 0.002), H * 0.45), (0.014, 0.012, H * 0.78), blue, bevel=0.003)
    for sx in (-1, 1):
        p.box((sx * (L / 2 + 0.004), 0, H - rim / 2), (0.012, W + 0.008, rim), blue, bevel=0.003)
        p.box((sx * (L / 2 - 0.002), 0, H - 0.075), (0.012, 0.13, 0.035), dark, bevel=0.008)  # handle slot
    return p.build(name)


def tote(name="Tote", size=(0.60, 0.40, 0.32), color=TOTE_GREY):
    """A lidded distribution tote: the body, the lid's lip, two lid flaps and a label holder."""
    L, W, H = size
    body = material("Goods tote", color, roughness=0.5)
    seam = material("Goods tote seam", (0.12, 0.13, 0.14), roughness=0.6)
    label = material("Goods label", WHITE, roughness=0.7)
    p = Parts()
    p.box((0, 0, (H - 0.03) / 2), (L - 0.02, W - 0.02, H - 0.03), body, bevel=0.012)
    p.box((0, 0, H - 0.04), (L, W, 0.012), seam, bevel=0.004)  # the lid's lip
    for sy in (-1, 1):  # two flaps meeting in the middle
        p.box((0, sy * W / 4, H - 0.015), (L - 0.01, W / 2 - 0.006, 0.03), body, bevel=0.006)
    p.box((L / 2 - 0.004, 0, H * 0.55), (0.006, 0.16, 0.09), label, bevel=0.002)
    return p.build(name)


def carton(name="Carton", size=(0.50, 0.35, 0.30), color=KRAFT, label=True):
    """A taped shipping carton with a label on top."""
    L, W, H = size
    kraft = material("Goods carton", color, roughness=0.85)
    tape = material("Goods tape", TAPE, roughness=0.35)
    white = material("Goods label", WHITE, roughness=0.7)
    p = Parts()
    p.box((0, 0, H / 2), (L, W, H), kraft, bevel=0.005)
    p.box((0, 0, H + 0.0008), (L + 0.002, 0.05, 0.002), tape, bevel=0.0)  # along the top seam ...
    for sx in (-1, 1):  # ... and down the ends
        p.box((sx * (L / 2 + 0.0008), 0, H - 0.04), (0.002, 0.05, 0.08), tape, bevel=0.0)
    if label:
        p.box((-L * 0.22, W * 0.22, H + 0.0012), (0.10, 0.07, 0.002), white, bevel=0.0)
    return p.build(name)


def envelope(name="Letter", size=(0.229, 0.162, 0.005)):
    """A C5 envelope: white, an address block and a stamp."""
    L, W, H = size
    paper = material("Goods envelope", WHITE, roughness=0.8)
    ink = material("Goods ink", INK, roughness=0.8)
    red = material("Goods stamp", STAMP, roughness=0.7)
    p = Parts()
    p.box((0, 0, H / 2), (L, W, H), paper, bevel=0.001)
    for k in range(3):  # three address lines
        p.box((0.01, -0.012 - k * 0.012, H + 0.0004), (0.08, 0.005, 0.0008), ink, bevel=0.0)
    p.box((L / 2 - 0.022, W / 2 - 0.022, H + 0.0004), (0.022, 0.026, 0.0008), red, bevel=0.0)
    return p.build(name)


def pallet(p=None, z=0.0):
    """A EUR pallet (1200 x 800 x 144): top boards, stringers, blocks, bottom boards."""
    wood = material("Goods pallet", WOOD, roughness=0.9)
    own = p is None
    p = p or Parts()
    for y, w in ((-0.3275, 0.145), (-0.16, 0.1), (0.0, 0.145), (0.16, 0.1), (0.3275, 0.145)):
        p.box((0, y, z + 0.144 - 0.011), (1.2, w, 0.022), wood, bevel=0.002)
    for x in (-0.5275, 0.0, 0.5275):
        p.box((x, 0, z + 0.1), (0.145, 0.8, 0.022), wood, bevel=0.002)
        for y in (-0.35, 0.0, 0.35):
            p.box((x, y, z + 0.0225 + 0.039), (0.145, 0.1, 0.078), wood, bevel=0.002)
    for y in (-0.35, 0.0, 0.35):
        p.box((0, y, z + 0.011), (1.2, 0.1, 0.022), wood, bevel=0.002)
    return p.build("EUR pallet") if own else p


def pallet_load(name="Pallet load", layers=3):
    """A EUR pallet with three layers of 400 x 400 cartons, the joints staggered by colour."""
    p = pallet(Parts())
    tones = [material("Goods carton", KRAFT, roughness=0.85), material("Goods carton light", (0.58, 0.40, 0.22), roughness=0.85)]
    tape = material("Goods tape", TAPE, roughness=0.35)
    h = 0.3
    for layer in range(layers):
        for i, x in enumerate((-0.4, 0.0, 0.4)):
            for j, y in enumerate((-0.2, 0.2)):
                z = 0.144 + layer * h + h / 2
                p.box((x, y, z), (0.395, 0.395, h - 0.004), tones[(i + j + layer) % 2], bevel=0.004)
                if layer == layers - 1:
                    p.box((x, y, 0.144 + layers * h + 0.0008), (0.395, 0.05, 0.002), tape, bevel=0.0)
    return p.build(name)
