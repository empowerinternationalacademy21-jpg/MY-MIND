"""My World art library: admin-uploaded art (island art, stop interiors, backgrounds, characters/stars).

Every upload is untrusted input. It is opened with Pillow (so only real images pass), size- and pixel-limited, orientation-fixed,
re-encoded to WebP (which drops all metadata, EXIF/GPS included) and stored under a random name. The original bytes are never kept or served.
"""
import io
import os
import secrets
from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError
from database.db import Session
from database.models import WorldAsset
from services import auth_service

KINDS = ("island", "interior", "character", "background")
STOPS = ("home", "sports", "music", "food", "colors", "pictures", "videos", "shots", "nature", "animals", "vehicles", "art")
ZONES = ("football", "basketball", "swimming", "athletics", "cycling")
THEMES = ("football", "basketball", "music", "food", "colors", "animals", "nature", "vehicles", "art", "mixed")
MAX_SIDE = 2048
MAX_PIXELS = 40_000_000
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
Image.MAX_IMAGE_PIXELS = MAX_PIXELS          # Pillow raises DecompressionBombError beyond ~2x this


class WorldError(Exception):
    pass


def asset_dir():
    d = current_app.config["WORLD_ASSET_DIR"]
    os.makedirs(d, exist_ok=True)
    return d


def _clean(value, allowed, field, blank_ok=False):
    value = (value or "").strip().lower()
    if value == "" and blank_ok:
        return ""
    if value not in allowed:
        raise WorldError(f"Please choose a valid {field}.")
    return value


def reencode(raw):
    """-> (webp_bytes, width, height). Raises WorldError for anything that is not a normal PNG/JPEG/WebP image."""
    try:
        probe = Image.open(io.BytesIO(raw))
        if probe.format not in ALLOWED_FORMATS:
            raise WorldError("Please upload a PNG, JPEG or WebP image.")
        probe.verify()                                   # structural check (verify() invalidates the object)
        img = Image.open(io.BytesIO(raw))
        if getattr(img, "n_frames", 1) > 1:
            img.seek(0)                                  # animated files: keep the first frame only
        img = ImageOps.exif_transpose(img)
        img.load()
    except WorldError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise WorldError("That file could not be read as an image.")
    if img.width < 16 or img.height < 16:
        raise WorldError("That image is too small.")
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    img = img.convert("RGBA" if ("A" in img.getbands() or img.mode == "P") else "RGB")
    out = io.BytesIO()
    img.save(out, "WEBP", quality=88, method=4)          # no exif/icc passed: metadata is dropped
    return out.getvalue(), img.width, img.height


def add_asset(admin, raw, kind, stop, zone, theme, name, caption, is_real_person, rights_confirmed, source_note):
    kind = _clean(kind, KINDS, "kind")
    stop = _clean(stop, STOPS, "stop", blank_ok=(kind == "background"))
    zone = _clean(zone, ZONES, "sports zone", blank_ok=True)
    theme = _clean(theme, THEMES, "theme", blank_ok=True)
    if zone and stop != "sports":
        raise WorldError("A sports zone only applies to the Sports stop.")
    name, caption, source_note = (name or "").strip()[:80], (caption or "").strip()[:240], (source_note or "").strip()[:300]
    if not rights_confirmed:
        raise WorldError("Please confirm you have the right to use this image.")
    if is_real_person and len(source_note) < 5:
        raise WorldError("Pictures of real people need a source or licence note.")
    if not raw:
        raise WorldError("Please choose an image file.")
    data, w, h = reencode(raw)
    filename = secrets.token_hex(16) + ".webp"
    with open(os.path.join(asset_dir(), filename), "wb") as fh:
        fh.write(data)
    row = WorldAsset(kind=kind, stop=stop, zone=zone, theme=theme, name=name, caption=caption, filename=filename, width=w, height=h,
                     is_real_person=bool(is_real_person), rights_confirmed=True, source_note=source_note, uploaded_by=admin.id)
    Session.add(row)
    Session.flush()
    auth_service.audit(admin.id, "world_asset_added", "world_asset", row.id, f"{kind}/{stop or '-'}{'/real-person' if is_real_person else ''}")
    Session.commit()
    return row


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def _name_from_filename(filename):
    """'my_red-fox.PNG' -> 'my red fox'. Only the last path part is used; the name is a label and never touches the disk."""
    base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = os.path.splitext(base)[0]
    return " ".join(stem.replace("_", " ").replace("-", " ").split())[:80]


def add_folder(admin, files, kind, stop, zone, theme, is_real_person, rights_confirmed, source_note, max_files=60, max_file_bytes=10 * 1024 * 1024):
    """Add many images at once. `files` is a list of (filename, raw_bytes) from a chosen folder.

    The shared settings are checked once up front, so a bad form adds nothing. After that each image is checked and re-encoded on its own,
    exactly like a single upload; one bad image is skipped and reported, it never blocks the others.
    -> {"added": [WorldAsset, ...], "skipped": [(filename, reason), ...]}
    """
    _clean(kind, KINDS, "kind")                                    # fail early with the same messages as a single upload
    kind_v = (kind or "").strip().lower()
    _clean(stop, STOPS, "stop", blank_ok=(kind_v == "background"))
    _clean(zone, ZONES, "sports zone", blank_ok=True)
    _clean(theme, THEMES, "theme", blank_ok=True)
    if not rights_confirmed:
        raise WorldError("Please confirm you have the right to use these images.")
    if is_real_person and len((source_note or "").strip()) < 5:
        raise WorldError("Pictures of real people need a source or licence note.")
    if not files:
        raise WorldError("Please choose a folder that has images in it.")
    added, skipped = [], []
    candidates = []
    for filename, raw in files:
        shown = (filename or "").replace("\\", "/").rsplit("/", 1)[-1] or "(no name)"
        if shown.startswith(".") or not shown.lower().endswith(IMAGE_EXTENSIONS):
            skipped.append((shown, "not a PNG, JPEG or WebP image"))
            continue
        candidates.append((shown, filename, raw))
    if not candidates:
        raise WorldError("That folder has no PNG, JPEG or WebP images in it.")
    if len(candidates) > max_files:
        raise WorldError(f"That folder has {len(candidates)} images. Please add at most {max_files} at a time.")
    for shown, filename, raw in candidates:
        if len(raw) > max_file_bytes:
            skipped.append((shown, "file is too large"))
            continue
        try:
            row = add_asset(admin, raw, kind, stop, zone, theme, _name_from_filename(filename), "", is_real_person, True, source_note)
            added.append(row)
        except WorldError as exc:
            skipped.append((shown, str(exc)))
    auth_service.audit(admin.id, "world_folder_added", "world_asset", None, f"{len(added)} added, {len(skipped)} skipped")
    Session.commit()
    return {"added": added, "skipped": skipped}


def set_active(admin, asset_id, active):
    row = Session.get(WorldAsset, asset_id)
    if not row:
        return None
    row.active = bool(active)
    auth_service.audit(admin.id, "world_asset_shown" if active else "world_asset_hidden", "world_asset", row.id, None)
    Session.commit()
    return row


def delete(admin, asset_id):
    row = Session.get(WorldAsset, asset_id)
    if not row:
        return False
    path = os.path.join(asset_dir(), row.filename)
    Session.delete(row)
    auth_service.audit(admin.id, "world_asset_deleted", "world_asset", asset_id, row.kind)
    Session.commit()
    try:
        os.remove(path)
    except OSError:
        pass
    return True


def all_assets():
    return Session.query(WorldAsset).order_by(WorldAsset.kind, WorldAsset.stop, WorldAsset.sort_order, WorldAsset.id).all()


def visible(show_real_people=False, kind=None, stop=None, zone=None, theme=None):
    """Active art a caregiver's child may see. Real-person pictures only when the caregiver switched them on."""
    q = Session.query(WorldAsset).filter(WorldAsset.active.is_(True))
    if not show_real_people:
        q = q.filter(WorldAsset.is_real_person.is_(False))
    for col, val in ((WorldAsset.kind, kind), (WorldAsset.stop, stop), (WorldAsset.zone, zone)):
        if val:
            q = q.filter(col == val)
    if theme:
        q = q.filter(WorldAsset.theme.in_(("", theme)))
    return q.order_by(WorldAsset.sort_order, WorldAsset.id).all()


def as_dict(a):
    return {"id": a.id, "kind": a.kind, "stop": a.stop, "zone": a.zone, "theme": a.theme, "name": a.name, "caption": a.caption,
            "url": f"/world-assets/{a.filename}", "width": a.width, "height": a.height, "real_person": a.is_real_person,
            "disclaimer": "Not affiliated with or endorsed by the person shown." if a.is_real_person else ""}
