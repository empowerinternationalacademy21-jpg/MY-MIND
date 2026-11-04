"""Build stylised low-poly floating island BASES for My World and export each one as a .glb. Free: needs only Blender 3.6 or newer.

ONE RUN MAKES A WHOLE SET OF THEMES (tropical, snowy, desert, autumn, candy, volcano, meadow...). Upload each file in
Admin > AI 3D > "Upload your own model" and the people using My World choose the look they like in World settings > Island look.

Two ways to run it:
  1. In Blender: open the "Scripting" tab > Open this file > press "Run Script". Files like island_tropical.glb are saved in a
     folder called "islands" next to your .blend file (or in your home folder if the scene is unsaved).
  2. From a terminal:  blender --background --python tools/blender_island.py -- /full/path/to/output_folder
     (add a theme name after the folder to make just one:  ... -- /out tropical)

IMPORTANT (how the app places the model): My World scales the model so its width fits the island, and the HIGHEST point of the
model becomes the island's walking surface. So the top must be the flat grass disc, with NOTHING standing above it
(no trees, houses or rocks). Put those in separate landmark models.

Tweak the settings below, run again, and re-export as often as you like.
"""
import math
import os
import random
import sys

import bmesh
import bpy

# ------------------------------------------------------------------ settings you can change
RADIUS = 5.0          # width does not matter (the app rescales it), only the proportions
SEGMENTS = 72         # more = smoother outline (72 is ~1,000 triangles, perfect for phones)

# One entry per island look. name -> the label people see comes from the name you type in the upload form.
#   grass = the flat top, sand = the beach ring, rock / rock_dark = the underside (rock_dark is used for the lowest part)
#   wiggle = how irregular the shoreline is (0 = circle), depth = how far the underside hangs, seed = random shape
THEMES = {
    "meadow":   dict(grass=(0.36, 0.72, 0.28, 1), sand=(0.95, 0.84, 0.56, 1), rock=(0.46, 0.38, 0.33, 1), rock_dark=(0.30, 0.25, 0.23, 1), wiggle=1.0, depth=3.6, seed=7),
    "tropical": dict(grass=(0.20, 0.78, 0.38, 1), sand=(1.00, 0.90, 0.62, 1), rock=(0.55, 0.42, 0.32, 1), rock_dark=(0.34, 0.26, 0.20, 1), wiggle=1.4, depth=3.2, seed=11),
    "snowy":    dict(grass=(0.96, 0.98, 1.00, 1), sand=(0.74, 0.88, 0.97, 1), rock=(0.52, 0.58, 0.68, 1), rock_dark=(0.32, 0.37, 0.46, 1), wiggle=0.8, depth=4.2, seed=3),
    "desert":   dict(grass=(0.93, 0.76, 0.42, 1), sand=(0.98, 0.88, 0.62, 1), rock=(0.78, 0.45, 0.26, 1), rock_dark=(0.52, 0.28, 0.17, 1), wiggle=1.1, depth=3.8, seed=21),
    "autumn":   dict(grass=(0.82, 0.52, 0.18, 1), sand=(0.88, 0.74, 0.50, 1), rock=(0.45, 0.33, 0.27, 1), rock_dark=(0.28, 0.20, 0.17, 1), wiggle=1.0, depth=3.6, seed=5),
    "candy":    dict(grass=(1.00, 0.62, 0.80, 1), sand=(1.00, 0.88, 0.94, 1), rock=(0.74, 0.55, 0.95, 1), rock_dark=(0.48, 0.34, 0.74, 1), wiggle=1.2, depth=3.0, seed=13),
    "volcano":  dict(grass=(0.26, 0.24, 0.25, 1), sand=(0.95, 0.40, 0.12, 1), rock=(0.20, 0.17, 0.17, 1), rock_dark=(0.10, 0.09, 0.09, 1), wiggle=0.9, depth=4.0, seed=9),
    "ocean":    dict(grass=(0.45, 0.82, 0.85, 1), sand=(0.96, 0.92, 0.78, 1), rock=(0.22, 0.45, 0.62, 1), rock_dark=(0.13, 0.27, 0.42, 1), wiggle=1.3, depth=3.4, seed=17),
}
DEFAULT_THEMES = list(THEMES)          # which themes a plain "Run Script" makes; remove names to make fewer
# ------------------------------------------------------------------


def make_material(name, color, roughness=0.9):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    mat.diffuse_color = color
    return mat


def shore(theta, w):
    """Natural-looking radius multiplier for an angle (smooth, repeatable). w = shoreline irregularity."""
    return 1.0 + w * (0.060 * math.sin(3 * theta + 1.3) + 0.040 * math.sin(5 * theta + 0.4) + 0.022 * math.sin(9 * theta + 2.1))


def build(theme_name):
    t = THEMES[theme_name]
    rnd = random.Random(t["seed"])
    depth = t["depth"]
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    # (radius factor, height, ring name): from the grass edge, down the sandy beach, then the rocky underside to a point.
    rings = [
        (0.86, 0.00, "grass"),     # flat grass top ends here
        (1.00, -0.14, "sand"),     # gently sloping beach
        (0.97, -0.45, "rock"),
        (0.84, -1.10, "rock"),
        (0.64, -1.90, "rock"),
        (0.40, -2.70, "rock"),
        (0.16, -3.30, "rock"),
    ]
    mesh = bpy.data.meshes.new(f"Island_{theme_name}")
    obj = bpy.data.objects.new(f"Island_{theme_name}", mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()

    top = bm.verts.new((0.0, 0.0, 0.0))
    grid = []
    for ri, (rf, h, kind) in enumerate(rings):
        row = []
        for i in range(SEGMENTS):
            th = 2 * math.pi * i / SEGMENTS
            r = RADIUS * rf * shore(th, t["wiggle"])
            z = h
            if kind == "rock":                         # rough, uneven rock (never the top ring, so the top stays flat)
                r *= 1.0 + rnd.uniform(-0.07, 0.07)
                z += rnd.uniform(-0.18, 0.18)
            row.append(bm.verts.new((r * math.cos(th), r * math.sin(th), z)))
        grid.append(row)
    tip = bm.verts.new((0.0, 0.0, -depth))

    slot = {"grass": 0, "sand": 1, "rock": 2, "dark": 3}                   # material slot per part

    def add_face(kind, *verts):
        f = bm.faces.new(verts)
        f.material_index = slot[kind]
        f.smooth = kind in ("grass", "sand")                                        # flat-shaded rock gives the crisp low-poly look
        return f

    for i in range(SEGMENTS):                                              # grass: a flat fan from the centre
        j = (i + 1) % SEGMENTS
        add_face("grass", top, grid[0][i], grid[0][j])
    for ri in range(len(rings) - 1):                                       # bands between neighbouring rings
        kind = rings[ri + 1][2]
        if kind == "rock" and ri + 1 >= len(rings) - 3:                    # the lowest rock bands use the darker colour
            kind = "dark"
        for i in range(SEGMENTS):
            j = (i + 1) % SEGMENTS
            add_face(kind, grid[ri][i], grid[ri + 1][i], grid[ri + 1][j], grid[ri][j])
    for i in range(SEGMENTS):                                              # close the bottom to a point
        j = (i + 1) % SEGMENTS
        add_face("dark", grid[-1][i], tip, grid[-1][j])
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))                # outward-facing
    bmesh.ops.triangulate(bm, faces=list(bm.faces))                        # keeps each face's material and shading
    bm.to_mesh(mesh)
    bm.free()

    for name, col in (("Grass", t["grass"]), ("Sand", t["sand"]), ("Rock", t["rock"]), ("Dark", t["rock_dark"])):
        obj.data.materials.append(make_material(f"{theme_name}_{name}", col, 0.95 if name != "Sand" else 1.0))
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def export(path):
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=True,
                              export_yup=True, export_materials="EXPORT", export_cameras=False, export_lights=False)
    print("Exported island to:", path)


def settings_from_command_line():
    """-> (output folder, [theme names]). Terminal use:  blender -b -P blender_island.py -- /out [theme]"""
    folder = None
    names = list(DEFAULT_THEMES)
    if "--" in sys.argv:
        extra = sys.argv[sys.argv.index("--") + 1:]
        if extra:
            folder = os.path.abspath(extra[0])
        if len(extra) > 1:
            names = [n for n in extra[1:] if n in THEMES]
    if not folder:
        base = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.path.expanduser("~")
        folder = os.path.join(base, "islands")
    return folder, names


if __name__ == "__main__":
    out_dir, theme_names = settings_from_command_line()
    os.makedirs(out_dir, exist_ok=True)
    for theme_name in theme_names:
        build(theme_name)
        export(os.path.join(out_dir, f"island_{theme_name}.glb"))
    print(f"Done: {len(theme_names)} island(s) in {out_dir}")