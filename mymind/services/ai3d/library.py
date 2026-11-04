"""Read-side helpers for AI 3D assets (what caregivers' children may see, and where files live)."""
import json
import os
import re
from flask import current_app
from database.db import Session
from database.models import Asset3D

_NAME_RE = re.compile(r"^[a-z0-9_]{1,24}$")


def private_dir():
    d = current_app.config["AI3D_PRIVATE_DIR"]
    os.makedirs(d, exist_ok=True)
    return d


def published():
    """Friends children can meet in places (island-kit pieces are used by the map itself, not listed as friends)."""
    return Session.query(Asset3D).filter(Asset3D.status == "published", Asset3D.kind != "landmark").order_by(Asset3D.id.desc()).limit(24).all()


def landmarks():
    """-> {category: newest published island-kit asset}. category is a map stop key, or "island" for the shared island base."""
    out = {}
    for a in Session.query(Asset3D).filter(Asset3D.status == "published", Asset3D.kind == "landmark").order_by(Asset3D.id.asc()).all():
        out[a.category] = a                      # ascending order: the newest wins
    return out


def island_bases():
    """Every published island base (the island 'looks' a caregiver can choose from), oldest first. Newest is the default."""
    return Session.query(Asset3D).filter(Asset3D.status == "published", Asset3D.kind == "landmark", Asset3D.category == "island").order_by(Asset3D.id.asc()).all()


def default_island():
    """The island base everyone sees until they choose another: the one the administrator marked as default,
    otherwise the newest published one, otherwise None (the built-in look)."""
    from services import settings_service
    bases = island_bases()
    wanted = (settings_service.get("default_island_id") or "").strip()
    for a in bases:
        if str(a.id) == wanted:
            return a
    return bases[-1] if bases else None


def clips(asset):
    try:
        d = json.loads(asset.clips_json or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def clip_names(asset):
    return sorted(k for k in clips(asset) if _NAME_RE.match(k))


def filename_for(asset, which):
    """Stored file name for 'glb', 'concept' or a clip name; None if unknown."""
    if which == "glb":
        return asset.glb_filename or None
    if which == "concept":
        return asset.concept_filename or None
    if _NAME_RE.match(which or ""):
        return clips(asset).get(which)
    return None


def remove_files(asset):
    names = [asset.glb_filename, asset.concept_filename, *clips(asset).values()]
    for n in names:
        if n and re.match(r"^[A-Za-z0-9._-]+$", n):
            try:
                os.remove(os.path.join(private_dir(), n))
            except OSError:
                pass