"""Admin → 2D World: preview the children's 2D map and rooms, upload artwork for each stop and room, switch stops on/off and set their order."""
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from routes.helpers import admin_required
from services import world2d_service as w2d
from services import world_library_service as wl

bp = Blueprint("admin_world2d", __name__, url_prefix="/admin/world2d")


@bp.route("/")
@admin_required
def manage():
    hidden = w2d.admin_hidden()
    rows = []
    for pos, key in enumerate([k for k in w2d.ordered_keys() if k != "journey"] + ["journey"], 1):
        d = w2d.STOPS[key]
        rows.append({"key": key, "label": d["label"], "icon": d["icon"], "pos": pos, "on": key not in hidden, "sign": key == "journey",
                     "stop_art": w2d.admin_art("stop2d", key), "room_art": w2d.admin_art("room2d", key)})
    return render_template("admin/world2d.html", rows=rows, ct_active="world2d")


@bp.route("/layout", methods=["POST"])
@admin_required
def layout():
    keys = [k for k in w2d.STOPS if k != "journey"]
    on = set(request.form.getlist("on"))
    hidden = [k for k in keys if k not in on]

    def pos(k):
        try:
            return int(request.form.get(f"pos_{k}", "99"))
        except ValueError:
            return 99
    order = sorted(keys, key=lambda k: (pos(k), keys.index(k)))
    try:
        w2d.set_layout(g.user, hidden, order)
        flash("The 2D map is updated for everyone.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_world2d.manage"))


@bp.route("/art/<kind>/<key>", methods=["POST"])
@admin_required
def art(kind, key):
    if kind not in w2d.ART_KINDS or key not in w2d.STOPS:
        abort(404)
    if request.form.get("action") == "reset":
        w2d.reset_art(g.user, kind, key)
        flash("Back to the built-in drawing.", "success")
        return redirect(url_for("admin_world2d.manage"))
    file = request.files.get("image")
    try:
        raw = file.read(current_app.config["WORLD_UPLOAD_MAX_BYTES"] + 1) if file else b""
        if len(raw) > current_app.config["WORLD_UPLOAD_MAX_BYTES"]:
            raise wl.WorldError("That file is too large.")
        if "rights_confirmed" not in request.form:
            raise wl.WorldError("Please confirm you have the right to use this image.")
        w2d.set_art(g.user, kind, key, raw)
        flash("Artwork saved. Children see it now.", "success")
    except wl.WorldError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_world2d.manage"))


@bp.route("/preview")
@admin_required
def preview():
    scene = w2d.preview_scene(lambda k: url_for("admin_world2d.preview_room", key=k))
    return render_template("my_world_2d.html", scene=scene, preview=True, active="world")


@bp.route("/preview/<key>")
@admin_required
def preview_room(key):
    data = w2d.preview_room(key)
    if data is None:
        abort(404)
    return render_template("world_room.html", room=data, key=key, preview=True, back_url=url_for("admin_world2d.preview"), active="world")
