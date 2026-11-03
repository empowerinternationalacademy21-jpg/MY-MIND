"""Web optimisation of a GLB with @gltf-transform/cli (optional): Meshopt geometry compression + WebP texture resize.
Provider parameters already set the polygon budget, so simplification is OFF here (it can damage skinned/animated meshes).
Without the CLI the file is kept exactly as delivered. A result that fails validation is discarded in favour of the original."""
import os
import shutil
import subprocess
import tempfile
from flask import current_app
from services.ai3d import glb


def available():
    return bool(shutil.which("gltf-transform"))


def optimize(data):
    """-> (bytes, info). Never raises for tool problems: falls back to the original bytes and says so."""
    exe = shutil.which("gltf-transform")
    if not exe:
        return data, {"optimizer": "none", "note": "gltf-transform CLI not installed; kept as delivered"}
    size = str(current_app.config["AI3D_TEXTURE_SIZE"])
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "in.glb"), os.path.join(tmp, "out.glb")
        with open(src, "wb") as fh:
            fh.write(data)
        try:
            proc = subprocess.run([exe, "optimize", src, dst, "--compress", "meshopt", "--texture-compress", "webp",
                                   "--texture-size", size, "--simplify", "false"],
                                  capture_output=True, timeout=300, check=False, stdin=subprocess.DEVNULL)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return data, {"optimizer": "failed", "note": f"optimiser did not run ({type(exc).__name__}); kept as delivered"}
        if proc.returncode != 0 or not os.path.exists(dst):
            return data, {"optimizer": "failed", "note": "optimiser reported an error; kept as delivered"}
        with open(dst, "rb") as fh:
            out = fh.read()
    try:
        glb.parse(out)
    except glb.GlbError:
        return data, {"optimizer": "failed", "note": "optimised file did not validate; kept as delivered"}
    return out, {"optimizer": "gltf-transform", "bytes_before": len(data), "bytes_after": len(out)}
