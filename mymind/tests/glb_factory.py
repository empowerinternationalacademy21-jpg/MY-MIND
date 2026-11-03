"""Builds tiny valid GLB files in pure Python for tests (no 3D libraries needed)."""
import json
import struct


def make_glb(triangles=12, skinned=False, animated=False, textures=0):
    pos = []
    for i in range(triangles):
        x = float(i)
        pos += [x, 0.0, 0.0, x + 1.0, 0.0, 0.0, x, 1.0, 0.0]
    binary = struct.pack(f"<{len(pos)}f", *pos)
    count = triangles * 3
    xs = pos[0::3]; ys = pos[1::3]; zs = pos[2::3]
    doc = {"asset": {"version": "2.0", "generator": "mymind-test"},
           "scene": 0, "scenes": [{"nodes": [0]}],
           "nodes": [{"mesh": 0, "name": "body"}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "mode": 4}]}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": count, "type": "VEC3",
                          "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(binary), "target": 34962}],
           "buffers": [{"byteLength": len(binary)}]}
    if skinned:
        doc["nodes"].append({"name": "joint0"})
        doc["skins"] = [{"joints": [1]}]
    if animated:
        t = struct.pack("<2f", 0.0, 1.0); v = struct.pack("<6f", 0, 0, 0, 0, 1, 0)
        off = len(binary); binary += t + v
        doc["bufferViews"] += [{"buffer": 0, "byteOffset": off, "byteLength": 8}, {"buffer": 0, "byteOffset": off + 8, "byteLength": 24}]
        doc["accessors"] += [{"bufferView": 1, "componentType": 5126, "count": 2, "type": "SCALAR", "min": [0.0], "max": [1.0]},
                             {"bufferView": 2, "componentType": 5126, "count": 2, "type": "VEC3"}]
        doc["animations"] = [{"samplers": [{"input": 1, "output": 2}], "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}]}]
        doc["buffers"][0]["byteLength"] = len(binary)
    if textures:
        doc["textures"] = [{"source": 0}] * textures
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    binary += b"\x00" * ((4 - len(binary) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    return (b"glTF" + struct.pack("<II", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
            + struct.pack("<I4s", len(binary), b"BIN\x00") + binary)


def make_solid_glb(color=(0.25, 0.6, 1.0, 1.0), animated=False, radius=0.5, lat=12, lon=18):
    """A small coloured, smooth-shaded sphere with a PBR material (and optional bobbing animation) so a viewer has something real to draw."""
    import math
    pos, nrm, idx = [], [], []
    for i in range(lat + 1):
        th = math.pi * i / lat
        for j in range(lon + 1):
            ph = 2 * math.pi * j / lon
            x, y, z = math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph)
            pos += [x * radius, y * radius, z * radius]; nrm += [x, y, z]
    for i in range(lat):
        for j in range(lon):
            a, b = i * (lon + 1) + j, (i + 1) * (lon + 1) + j
            idx += [a, b, a + 1, b, b + 1, a + 1]
    pb = struct.pack(f"<{len(pos)}f", *pos); nb = struct.pack(f"<{len(nrm)}f", *nrm); ib = struct.pack(f"<{len(idx)}H", *idx)
    ib += b"\x00" * ((4 - len(ib) % 4) % 4)
    binary = pb + nb + ib
    n = len(pos) // 3
    xs, ys, zs = pos[0::3], pos[1::3], pos[2::3]
    doc = {"asset": {"version": "2.0", "generator": "mymind-test"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "ball"}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0, "mode": 4}]}],
           "materials": [{"pbrMetallicRoughness": {"baseColorFactor": list(color), "metallicFactor": 0.0, "roughnessFactor": 0.6}}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": n, "type": "VEC3", "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
                         {"bufferView": 1, "componentType": 5126, "count": n, "type": "VEC3"},
                         {"bufferView": 2, "componentType": 5123, "count": len(idx), "type": "SCALAR"}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pb), "target": 34962}, {"buffer": 0, "byteOffset": len(pb), "byteLength": len(nb), "target": 34962},
                           {"buffer": 0, "byteOffset": len(pb) + len(nb), "byteLength": len(idx) * 2, "target": 34963}],
           "buffers": [{"byteLength": len(binary)}]}
    if animated:
        t = struct.pack("<3f", 0.0, 0.5, 1.0); v = struct.pack("<9f", 0, 0, 0, 0, 0.25, 0, 0, 0, 0)
        off = len(binary); binary += t + v
        doc["bufferViews"] += [{"buffer": 0, "byteOffset": off, "byteLength": 12}, {"buffer": 0, "byteOffset": off + 12, "byteLength": 36}]
        doc["accessors"] += [{"bufferView": 3, "componentType": 5126, "count": 3, "type": "SCALAR", "min": [0.0], "max": [1.0]},
                             {"bufferView": 4, "componentType": 5126, "count": 3, "type": "VEC3"}]
        doc["animations"] = [{"name": "bob", "samplers": [{"input": 3, "output": 4}], "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}]}]
        doc["buffers"][0]["byteLength"] = len(binary)
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    binary += b"\x00" * ((4 - len(binary) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    return (b"glTF" + struct.pack("<II", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(binary), b"BIN\x00") + binary)


# ---- multi-part models (an island base, a house) so browser tests can see AI-kit swapping without any provider ----
def _mesh_box(w, h, d, cx=0.0, cy=0.0, cz=0.0):
    hw, hh, hd = w / 2, h / 2, d / 2
    faces = [((0, 0, 1), [(-hw, -hh, hd), (hw, -hh, hd), (hw, hh, hd), (-hw, hh, hd)]), ((0, 0, -1), [(hw, -hh, -hd), (-hw, -hh, -hd), (-hw, hh, -hd), (hw, hh, -hd)]),
             ((1, 0, 0), [(hw, -hh, hd), (hw, -hh, -hd), (hw, hh, -hd), (hw, hh, hd)]), ((-1, 0, 0), [(-hw, -hh, -hd), (-hw, -hh, hd), (-hw, hh, hd), (-hw, hh, -hd)]),
             ((0, 1, 0), [(-hw, hh, hd), (hw, hh, hd), (hw, hh, -hd), (-hw, hh, -hd)]), ((0, -1, 0), [(-hw, -hh, -hd), (hw, -hh, -hd), (hw, -hh, hd), (-hw, -hh, hd)])]
    pos, nrm, idx = [], [], []
    for n, quad in faces:
        base = len(pos) // 3
        for x, y, z in quad:
            pos += [x + cx, y + cy, z + cz]; nrm += list(n)
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return pos, nrm, idx


def _mesh_cyl(rt, rb, h, seg=24, cx=0.0, cy=0.0, cz=0.0):
    import math
    pos, nrm, idx = [], [], []
    slope = (rb - rt) / h if h else 0.0
    for i in range(seg + 1):
        a = 2 * math.pi * i / seg; c, s = math.cos(a), math.sin(a)
        ln = math.sqrt(1 + slope * slope)
        for r, y in ((rt, h / 2), (rb, -h / 2)):
            pos += [r * c + cx, y + cy, r * s + cz]; nrm += [c / ln, slope / ln, s / ln]
    for i in range(seg):
        a, b = i * 2, i * 2 + 2
        idx += [a, a + 1, b, b, a + 1, b + 1]
    for sign, r, y in ((1, rt, h / 2), (-1, rb, -h / 2)):
        if r <= 0:
            continue
        base = len(pos) // 3
        pos += [cx, y + cy, cz]; nrm += [0, sign, 0]
        for i in range(seg + 1):
            a = 2 * math.pi * i / seg
            pos += [r * math.cos(a) + cx, y + cy, r * math.sin(a) + cz]; nrm += [0, sign, 0]
        for i in range(seg):
            idx += [base, base + 1 + i + (0 if sign > 0 else 1), base + 1 + i + (1 if sign > 0 else 0)]
    return pos, nrm, idx


def make_parts_glb(parts):
    """parts: list of ((positions, normals, indices), (r, g, b, a) linear colour). One node and one material per part."""
    binary, views, accessors, meshes, nodes, mats = b"", [], [], [], [], []
    for (pos, nrm, idx), color in parts:
        offs = []
        for blob, target in ((struct.pack(f"<{len(pos)}f", *pos), 34962), (struct.pack(f"<{len(nrm)}f", *nrm), 34962), (struct.pack(f"<{len(idx)}H", *idx), 34963)):
            pad = b"\x00" * ((4 - len(blob) % 4) % 4)
            views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(blob), "target": target}); offs.append(len(views) - 1)
            binary += blob + pad
        n = len(pos) // 3; xs, ys, zs = pos[0::3], pos[1::3], pos[2::3]
        a0 = len(accessors)
        accessors += [{"bufferView": offs[0], "componentType": 5126, "count": n, "type": "VEC3", "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
                      {"bufferView": offs[1], "componentType": 5126, "count": n, "type": "VEC3"}, {"bufferView": offs[2], "componentType": 5123, "count": len(idx), "type": "SCALAR"}]
        mats.append({"pbrMetallicRoughness": {"baseColorFactor": list(color), "metallicFactor": 0.0, "roughnessFactor": 0.8}})
        meshes.append({"primitives": [{"attributes": {"POSITION": a0, "NORMAL": a0 + 1}, "indices": a0 + 2, "material": len(mats) - 1, "mode": 4}]})
        nodes.append({"mesh": len(meshes) - 1})
    doc = {"asset": {"version": "2.0", "generator": "mymind-test"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes,
           "materials": mats, "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(binary)}]}
    js = json.dumps(doc, separators=(",", ":")).encode(); js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    return b"glTF" + struct.pack("<II", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(binary), b"BIN\x00") + binary


def make_island_glb():
    """A flat-topped floating island with a sandy rim and a rocky underside (what the island-base prompt asks a provider for)."""
    return make_parts_glb([(_mesh_cyl(1.0, 0.95, 0.3, 40, cy=0.0), (0.12, 0.55, 0.15, 1)), (_mesh_cyl(1.06, 1.0, 0.12, 40, cy=-0.12), (0.78, 0.66, 0.35, 1)),
                           (_mesh_cyl(0.92, 0.05, 1.5, 12, cy=-0.9), (0.28, 0.2, 0.14, 1))])


def make_house_glb():
    return make_parts_glb([(_mesh_box(1.0, 0.7, 0.9, cy=0.35), (0.95, 0.85, 0.6, 1)), (_mesh_cyl(0.0, 0.85, 0.5, 4, cy=0.95), (0.8, 0.1, 0.08, 1)),
                           (_mesh_box(0.22, 0.4, 0.04, cy=0.2, cz=0.46), (0.3, 0.15, 0.07, 1)), (_mesh_box(0.16, 0.34, 0.16, cx=0.3, cy=1.1, cz=-0.1), (0.5, 0.2, 0.12, 1))])
