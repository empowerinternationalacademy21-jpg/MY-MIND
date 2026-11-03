"""Admin → World Library."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from routes.helpers import admin_required
from services import world_library_service as wl
from database.db import Session
from database.models import WorldAsset
from flask import send_from_directory

bp = Blueprint("admin_world", __name__, url_prefix="/admin/world")


@bp.route("/")
@admin_required
def library():
    return render_template("admin/world.html", assets=wl.all_assets(), kinds=wl.KINDS, stops=wl.STOPS, zones=wl.ZONES, themes=wl.THEMES, nav="world")


@bp.route("/upload", methods=["POST"])
@admin_required
def upload():
    f = request.form
    file = request.files.get("image")
    try:
        wl.add_asset(g.user, file.read() if file else b"", f.get("kind"), f.get("stop"), f.get("zone"), f.get("theme"), f.get("name"),
                     f.get("caption"), "is_real_person" in f, "rights_confirmed" in f, f.get("source_note"))
        flash("Art added to the library.", "success")
    except wl.WorldError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_world.library"))


@bp.route("/<int:asset_id>/<action>", methods=["POST"])
@admin_required
def change(asset_id, action):
    if action in ("show", "hide"):
        ok = wl.set_active(g.user, asset_id, action == "show")
    elif action == "delete":
        ok = wl.delete(g.user, asset_id)
    else:
        abort(404)
    if not ok:
        abort(404)
    flash({"show": "Art is visible again.", "hide": "Art hidden from children.", "delete": "Art deleted."}[action], "success")
    return redirect(url_for("admin_world.library"))


@bp.route("/<int:asset_id>/preview")
@admin_required
def preview(asset_id):
    row = Session.get(WorldAsset, asset_id)
    if not row:
        abort(404)
    resp = send_from_directory(wl.asset_dir(), row.filename, mimetype="image/webp")
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp
