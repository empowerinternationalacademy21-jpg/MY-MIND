"""Caregiver-side access to the World Library: image files and a small JSON API. Everything is behind the full access gate."""
import os
import re
from flask import Blueprint, g, jsonify, request, send_from_directory, abort
from routes.helpers import subscribed_required
from services import settings_service, world_library_service as wl
from services.ai3d import library as a3d_library
from routes.helpers import login_required

bp = Blueprint("world", __name__)
_FILE_RE = re.compile(r"^[0-9a-f]{32}\.webp$")


@bp.route("/world-assets/<name>")
@subscribed_required
def asset_file(name):
    if not _FILE_RE.match(name):                               # also blocks any path tricks
        abort(404)
    from database.db import Session
    from database.models import WorldAsset
    row = Session.query(WorldAsset).filter_by(filename=name, active=True).first()
    if not row or (row.is_real_person and not settings_service.caregiver_settings(g.user.id)["show_real_people"]):
        abort(404)
    resp = send_from_directory(wl.asset_dir(), name, mimetype="image/webp", max_age=3600)
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@bp.route("/api/world-assets")
@subscribed_required
def api_assets():
    show = settings_service.caregiver_settings(g.user.id)["show_real_people"]
    kind, stop, zone, theme = (request.args.get(k, "")[:20] for k in ("kind", "stop", "zone", "theme"))
    return jsonify(assets=[wl.as_dict(a) for a in wl.visible(show, kind or None, stop or None, zone or None, theme or None)])


@bp.route("/assets3d/<int:asset_id>/<which>")
@login_required
def asset3d_file(asset_id, which):
    """GLB / clip / concept files. An administrator sees any job; a caregiver only sees PUBLISHED models (never the concept image)."""
    from database.db import Session
    from database.models import Asset3D
    from services import verification_service
    row = Session.get(Asset3D, asset_id)
    if not row:
        abort(404)
    if g.user.role != "admin":
        if g.user.role != "caregiver" or verification_service.needs_verification(g.user) or row.status != "published" or which == "concept":
            abort(404)
    name = a3d_library.filename_for(row, which)
    if not name or not re.match(r"^[A-Za-z0-9._-]+$", name):
        abort(404)
    mime = "image/png" if name.endswith(".png") else "model/gltf-binary"
    resp = send_from_directory(a3d_library.private_dir(), name, mimetype=mime)
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


# ---------------------------------------------------------------- adaptive island world API
from flask import request
from services import world_service as ws


@bp.route("/api/world")
@subscribed_required
def api_world():
    return jsonify(ws.payload(g.user, g.child))


@bp.route("/api/world/stop/<key>")
@subscribed_required
def api_world_stop(key):
    d = ws.stop_detail(g.user, g.child, key)
    if d is None:
        abort(404)
    return jsonify(d)


@bp.route("/api/world/settings", methods=["POST"])
@subscribed_required
def api_world_settings():
    try:
        ws.update_settings(g.user.id, request.get_json(silent=True))
    except ws.WorldError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(ws.payload(g.user, g.child))


@bp.route("/api/world/reset-theme", methods=["POST"])
@subscribed_required
def api_world_reset_theme():
    ws.reset_theme(g.user.id, g.child)
    return jsonify(ws.payload(g.user, g.child))
