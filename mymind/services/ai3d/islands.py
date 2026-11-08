"""Administrator island management: list, choose the default world, delete (one, several, all), restore, purge.

An "island" is an Asset3D with kind='landmark' and category='island' (the 3D base every child's My World stands on).

Rules this module enforces (the routes only call it; nothing here trusts the page):
* Deleting is SOFT: the island moves to status 'deleted' (recoverable from "Recently deleted"). Its files are kept until it is
  purged on purpose. Children's activity is never touched: it is keyed by child and content, not by island.
* The default island is protected. It cannot be deleted (alone or in a selection) until another default is chosen. The only way to
  remove it is the explicit "delete all / start fresh" workflow, which also resets the setting so nothing points at a deleted island.
* Only island bases are touched. Place landmarks (home.glb ...), friends, art, accounts and activity are never deleted here.
* A file is physically removed only when no other 3D asset still references it.
* Every change is one database transaction (all or nothing) and is written to the audit log.
"""
import json
import os
import re
from datetime import datetime

from database.db import Session
from database.models import Asset3D, utcnow
from services import auth_service, settings_service
from services.ai3d import library

TRASH = "deleted"
CONFIRM_PHRASE = "DELETE ALL"
_FILE_OK = re.compile(r"^[A-Za-z0-9._-]+$")


class IslandError(ValueError):
    """A refusal with a message that is safe and useful to show the administrator."""


def _islands():
    return Session.query(Asset3D).filter(Asset3D.kind == "landmark", Asset3D.category == "island")


def is_island(asset):
    return bool(asset) and asset.kind == "landmark" and asset.category == "island"


def all_islands():
    """Every island the administrator can manage (any status except deleted), newest first."""
    return _islands().filter(Asset3D.status != TRASH).order_by(Asset3D.id.desc()).all()


def trashed():
    return _islands().filter(Asset3D.status == TRASH).order_by(Asset3D.id.desc()).all()


def default_state():
    """{'island': Asset3D|None, 'mode': 'set'|'automatic'|'none', 'locked': bool, 'stale': bool}.

    'set' = the administrator chose it; 'automatic' = nothing valid is chosen so the newest published island is used;
    'none' = no published island exists (children see the built-in look; show the setup state)."""
    published = library.island_bases()
    wanted = (settings_service.get("default_island_id") or "").strip()
    chosen = next((a for a in published if str(a.id) == wanted), None)
    island = chosen or (published[-1] if published else None)
    return {"island": island, "mode": "set" if chosen else ("automatic" if island else "none"),
            "locked": settings_service.get("island_lock") == "1", "stale": bool(wanted) and not chosen}


def _normalize():
    """Never let the stored default point at an island that is gone, unpublished or in the trash."""
    wanted = (settings_service.get("default_island_id") or "").strip()
    if wanted and not any(str(a.id) == wanted for a in library.island_bases()):
        settings_service.set_value("default_island_id", "")


def repair_default():
    """Fix (and save) a stored default that points at an island that is gone, unpublished or deleted. True if something was repaired."""
    before = (settings_service.get("default_island_id") or "").strip()
    _normalize()
    if (settings_service.get("default_island_id") or "").strip() != before:
        Session.commit()
        return True
    return False


def _audit(admin, action, asset_id, detail=None):
    auth_service.audit(admin.id, action, "asset3d", asset_id, detail)


def _get_island(asset_id):
    row = Session.get(Asset3D, asset_id)
    if not is_island(row):
        raise IslandError("That island does not exist.")
    return row


def set_default(admin, asset_id):
    """Make one published island the shared world for EVERY child account (and stop personal island choices overriding it)."""
    try:
        row = _get_island(asset_id)
        if row.status != "published":
            raise IslandError("Only a published island can be the default world. Publish it first.")
        settings_service.set_value("default_island_id", str(row.id))
        settings_service.set_value("island_lock", "1")
        _audit(admin, "world_island_set", row.id, "set as default world for everyone")
        Session.commit()
        return row
    except Exception:
        Session.rollback()
        raise


def _stamp(row, note=None):
    stats = {}
    try:
        stats = json.loads(row.stats_json or "{}")
        stats = stats if isinstance(stats, dict) else {}
    except ValueError:
        stats = {}
    stats["deleted_from"] = row.status
    stats["deleted_at"] = utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    row.stats_json = json.dumps(stats)


def soft_delete(admin, asset_ids):
    """Move the chosen islands to 'Recently deleted'. Refuses if the default island is among them. Returns how many moved."""
    ids = sorted({int(i) for i in asset_ids})
    if not ids:
        raise IslandError("Please choose at least one island.")
    try:
        default = default_state()["island"]
        rows = []
        for i in ids:
            row = _get_island(i)
            if row.status == TRASH:
                continue
            if default is not None and row.id == default.id:
                raise IslandError(f"“{row.name or 'Island ' + str(row.id)}” is the default world. Choose another default island first, "
                                  "or use “Delete all islands” to start completely fresh.")
            rows.append(row)
        if not rows:
            raise IslandError("Those islands were already deleted.")
        for row in rows:
            _stamp(row)
            row.status = TRASH
            _audit(admin, "world_island_deleted", row.id, row.name)
        _normalize()
        Session.commit()
        return len(rows)
    except Exception:
        Session.rollback()
        raise


def delete_all(admin, phrase):
    """Start from a completely new world: every island (including the default) goes to the trash and the setting is reset, so the
    world falls back to the built-in look until a new default is chosen. Needs the typed phrase."""
    if (phrase or "").strip() != CONFIRM_PHRASE:
        raise IslandError(f"Type {CONFIRM_PHRASE} exactly to confirm.")
    try:
        rows = _islands().filter(Asset3D.status != TRASH).all()
        if not rows:
            raise IslandError("There are no islands to delete.")
        for row in rows:
            _stamp(row)
            row.status = TRASH
            _audit(admin, "world_island_deleted", row.id, "delete all")
        settings_service.set_value("default_island_id", "")
        settings_service.set_value("island_lock", "0")
        _audit(admin, "world_islands_cleared", None, f"{len(rows)} islands")
        Session.commit()
        return len(rows)
    except Exception:
        Session.rollback()
        raise


def restore(admin, asset_id):
    """Bring an island back from 'Recently deleted' with the status it had (published islands become available again)."""
    try:
        row = _get_island(asset_id)
        if row.status != TRASH:
            raise IslandError("That island is not in the deleted list.")
        try:
            before = (json.loads(row.stats_json or "{}") or {}).get("deleted_from")
        except ValueError:
            before = None
        row.status = before if before in ("published", "review", "rejected", "failed") else "review"
        _audit(admin, "world_island_restored", row.id, row.status)
        Session.commit()
        return row
    except Exception:
        Session.rollback()
        raise


def _files(asset):
    names = [asset.glb_filename, asset.concept_filename]
    try:
        names += list((json.loads(asset.clips_json or "{}") or {}).values())
    except (ValueError, AttributeError):
        pass
    return [n for n in names if n and _FILE_OK.match(n)]


def _still_used_elsewhere(asset, name):
    other = Session.query(Asset3D).filter(Asset3D.id != asset.id)
    return other.filter((Asset3D.glb_filename == name) | (Asset3D.concept_filename == name)
                        | Asset3D.clips_json.like(f"%{name}%")).first() is not None


def purge(admin, asset_ids):
    """Permanently remove islands that are already in the trash. A file is deleted only if no other asset uses it."""
    ids = sorted({int(i) for i in asset_ids})
    if not ids:
        raise IslandError("Please choose at least one island.")
    try:
        removed, kept = 0, 0
        to_unlink = []
        for i in ids:
            row = _get_island(i)
            if row.status != TRASH:
                raise IslandError("Only islands in the deleted list can be removed permanently.")
            for name in _files(row):
                if _still_used_elsewhere(row, name):
                    kept += 1
                else:
                    to_unlink.append(name)
            _audit(admin, "world_island_purged", row.id, row.name)
            Session.delete(row)
            removed += 1
        _normalize()
        Session.commit()                         # database first: a failure here leaves every file untouched
        for name in to_unlink:
            try:
                os.remove(os.path.join(library.private_dir(), name))
            except OSError:
                pass
        return removed, kept
    except Exception:
        Session.rollback()
        raise


def usage_summary(asset):
    """Small facts for the management card (never anything about children)."""
    try:
        stats = json.loads(asset.stats_json or "{}") or {}
    except ValueError:
        stats = {}
    return {"triangles": stats.get("triangles"), "mb": round((stats.get("bytes") or 0) / 1048576, 2) if stats.get("bytes") else None,
            "deleted_at": stats.get("deleted_at")}
