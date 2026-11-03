"""Minimal, dependency-free GLB (binary glTF 2.0) reader: validation and statistics."""
import json
import struct

MAGIC = b"glTF"


class GlbError(ValueError):
    pass


def parse(data):
    """-> glTF JSON dict. Raises GlbError unless `data` is a well-formed GLB container."""
    if len(data) < 20 or data[:4] != MAGIC:
        raise GlbError("The file is not a GLB model.")
    version, length = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise GlbError("Only glTF 2.0 models are supported.")
    if length != len(data):
        raise GlbError("The model file is truncated or corrupt.")
    pos, doc = 12, None
    while pos + 8 <= len(data):
        clen, ctype = struct.unpack_from("<I4s", data, pos)
        body = data[pos + 8: pos + 8 + clen]
        if len(body) != clen:
            raise GlbError("The model file is truncated or corrupt.")
        if ctype == b"JSON":
            try:
                doc = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise GlbError("The model's description could not be read.")
            break
        pos += 8 + clen + ((4 - clen % 4) % 4)
    if not isinstance(doc, dict) or "asset" not in doc:
        raise GlbError("The model's description is missing.")
    return doc


def stats(data):
    doc = parse(data)
    accessors = doc.get("accessors", [])
    tris = 0
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            if prim.get("mode", 4) != 4:
                continue
            try:
                if "indices" in prim:
                    tris += accessors[prim["indices"]]["count"] // 3
                else:
                    tris += accessors[prim["attributes"]["POSITION"]]["count"] // 3
            except (KeyError, IndexError, TypeError):
                continue
    return {"triangles": tris, "bytes": len(data), "meshes": len(doc.get("meshes", [])), "textures": len(doc.get("textures", [])),
            "animations": len(doc.get("animations", [])), "skins": len(doc.get("skins", [])),
            "extensions": sorted(doc.get("extensionsUsed", []))}
