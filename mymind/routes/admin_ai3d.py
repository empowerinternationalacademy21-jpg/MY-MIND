"""Admin → AI 3D: create jobs from allow-listed choices, watch them, review, publish."""
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, current_app
from database.db import Session
from database.models import Asset3D
from routes.helpers import admin_required
from services import auth_service, settings_service
from services.ai3d import islands, library, optimize, pipeline, providers, safe_prompts

bp = Blueprint("admin_ai3d", __name__, url_prefix="/admin/3d")


def _job_or_404(job_id):
    job = Session.get(Asset3D, job_id)
    if not job:
        abort(404)
    return job


@bp.route("/")
@admin_required
def jobs():
    rows = Session.query(Asset3D).filter(Asset3D.status != islands.TRASH).order_by(Asset3D.id.desc()).limit(100).all()
    return render_template("admin/ai3d.html", jobs=rows, catalog=safe_prompts.catalog(), colors=list(safe_prompts.COLORS), styles=list(safe_prompts.STYLES),
                           moods=list(safe_prompts.MOODS), accessories=list(safe_prompts.ACCESSORIES), archetypes=safe_prompts.ARCHETYPES, kit=safe_prompts.kit_catalog(),
                           provider_ready={n: c.configured() for n, c in providers.PROVIDERS.items()}, concept_ready=providers.concept_configured(),
                           optimizer=optimize.available(), folder_max_files=current_app.config["AI3D_FOLDER_MAX_FILES"], nav="3d",
                           island_bases=library.island_bases(), island_choice=(settings_service.get("default_island_id") or "").strip(),
                           island_locked=settings_service.get("island_lock") == "1",
                           island_summary={"total": len(islands.all_islands()), "trash": len(islands.trashed()), "state": islands.default_state()})


@bp.route("/island", methods=["POST"])
@admin_required
def set_island():
    """One island for every user's My World, on every device. With the lock on, personal island choices are ignored."""
    choice = (request.form.get("island") or "auto").strip()
    valid = {"auto", "classic"} | {str(a.id) for a in library.island_bases()}
    if choice not in valid:
        flash("Please choose one of the published islands.", "error")
        return redirect(url_for("admin_ai3d.jobs"))
    lock = "lock" in request.form
    settings_service.set_value("default_island_id", "" if choice == "auto" else choice)
    settings_service.set_value("island_lock", "1" if lock else "0")
    auth_service.audit(g.user.id, "world_island_set", "setting", choice, "locked for everyone" if lock else "default only")
    Session.commit()
    flash("Every user's My World now uses this island." if lock else "Saved. This is the default island for everyone who has not chosen another.", "success")
    return redirect(url_for("admin_ai3d.jobs"))


@bp.route("/<int:job_id>/island-for-everyone", methods=["POST"])
@admin_required
def island_for_everyone(job_id):
    job = _job_or_404(job_id)
    if job.status != "published" or job.kind != "landmark" or job.category != "island":
        flash("Only a published island base can be used for everyone's world.", "error")
        return redirect(url_for("admin_ai3d.detail", job_id=job_id))
    settings_service.set_value("default_island_id", str(job.id))
    settings_service.set_value("island_lock", "1")
    auth_service.audit(g.user.id, "world_island_set", "asset3d", job.id, "locked for everyone")
    Session.commit()
    flash("Done. Every user's My World now uses this island, on every device.", "success")
    return redirect(url_for("admin_ai3d.detail", job_id=job_id))


# ---------------------------------------------------------------- 3D WORLD & ISLAND MANAGEMENT
def _confirmed():
    """Destructive or world-wide changes need an explicit confirmation field (the page's dialog sets it)."""
    return request.form.get("confirm") == "yes"


def _island_ids():
    out = []
    for raw in request.form.getlist("ids"):
        try:
            out.append(int(raw))
        except ValueError:
            continue
    return out


def _islands_back():
    return redirect(url_for("admin_ai3d.island_manager"))


@bp.route("/islands")
@admin_required
def island_manager():
    islands.repair_default()                                            # the page never shows a default that points at a deleted island
    rows = islands.all_islands()
    state = islands.default_state()
    return render_template("admin/islands.html", islands=rows, trash=islands.trashed(), state=state, usage={a.id: islands.usage_summary(a) for a in rows},
                           confirm_phrase=islands.CONFIRM_PHRASE, nav="3d")


@bp.route("/islands/default", methods=["POST"])
@admin_required
def island_set_default():
    if not _confirmed():
        flash("Please confirm before changing the default world.", "error")
        return _islands_back()
    try:
        row = islands.set_default(g.user, int(request.form.get("id", "0") or 0))
    except (islands.IslandError, ValueError) as exc:
        flash(str(exc) if isinstance(exc, islands.IslandError) else "Please choose an island.", "error")
        return _islands_back()
    flash(f"“{row.name or 'Island ' + str(row.id)}” is now the default world for every child account.", "success")
    return _islands_back()


@bp.route("/islands/delete", methods=["POST"])
@admin_required
def island_delete():
    """One island or a selection. Soft delete: it moves to 'Recently deleted' and can be restored."""
    if not _confirmed():
        flash("Please confirm before deleting.", "error")
        return _islands_back()
    try:
        n = islands.soft_delete(g.user, _island_ids())
    except islands.IslandError as exc:
        flash(str(exc), "error")
        return _islands_back()
    flash(f"{n} island{'s' if n != 1 else ''} deleted. You can restore {'them' if n != 1 else 'it'} from Recently deleted.", "success")
    return _islands_back()


@bp.route("/islands/delete-all", methods=["POST"])
@admin_required
def island_delete_all():
    if not _confirmed():
        flash("Please confirm before deleting all islands.", "error")
        return _islands_back()
    try:
        n = islands.delete_all(g.user, request.form.get("phrase", ""))
    except islands.IslandError as exc:
        flash(str(exc), "error")
        return _islands_back()
    flash(f"All {n} island{'s' if n != 1 else ''} deleted and the default world was reset. Children now see the built-in map until you choose a new default.", "success")
    return _islands_back()


@bp.route("/islands/restore", methods=["POST"])
@admin_required
def island_restore():
    try:
        row = islands.restore(g.user, int(request.form.get("id", "0") or 0))
    except (islands.IslandError, ValueError) as exc:
        flash(str(exc) if isinstance(exc, islands.IslandError) else "Please choose an island.", "error")
        return _islands_back()
    flash(f"“{row.name or 'Island ' + str(row.id)}” restored.", "success")
    return _islands_back()


@bp.route("/islands/purge", methods=["POST"])
@admin_required
def island_purge():
    if not _confirmed():
        flash("Please confirm before removing permanently.", "error")
        return _islands_back()
    ids = _island_ids()
    if request.form.get("all") == "yes":
        ids = [a.id for a in islands.trashed()]
    try:
        removed, kept = islands.purge(g.user, ids)
    except islands.IslandError as exc:
        flash(str(exc), "error")
        return _islands_back()
    msg = f"{removed} island{'s' if removed != 1 else ''} removed permanently."
    if kept:
        msg += f" {kept} shared file{'s' if kept != 1 else ''} kept because another 3D model still uses {'them' if kept != 1 else 'it'}."
    flash(msg, "success")
    return _islands_back()


@bp.route("/new", methods=["POST"])
@admin_required
def create():
    f = request.form
    try:
        job = pipeline.create_job(g.user, f.get("archetype", ""), {k: f.get(k) for k in ("color", "style", "mood", "accessory") if f.get(k)},
                                  f.get("provider", ""), f.get("name", ""), f.get("caption", ""))
        flash("Job queued. The worker (or the Refresh button) will move it along.", "success")
        return redirect(url_for("admin_ai3d.detail", job_id=job.id))
    except pipeline.PipelineError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_ai3d.jobs"))


@bp.route("/kit", methods=["POST"])
@admin_required
def kit():
    if "confirm" not in request.form:
        flash("Please tick the box to confirm this will use provider credits.", "error")
        return redirect(url_for("admin_ai3d.jobs"))
    try:
        created, skipped, capped = pipeline.create_kit(g.user, request.form.get("provider", ""))
    except pipeline.PipelineError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_ai3d.jobs"))
    msg = f"Queued {len(created)} island-kit model{'s' if len(created) != 1 else ''}."
    if skipped:
        msg += f" Skipped {len(skipped)} that already have a model in progress or published."
    if capped:
        msg += " Stopped at the daily limit; run it again tomorrow for the rest."
    flash(msg, "success")
    return redirect(url_for("admin_ai3d.jobs"))


@bp.route("/upload", methods=["POST"])
@admin_required
def upload():
    """Free path: upload a .glb you made yourself (Blender etc.). It goes to review; publish it from its page."""
    f = request.files.get("model")
    if not f or not (f.filename or "").lower().endswith(".glb"):
        flash("Please choose a .glb file (in Blender: File > Export > glTF 2.0 and pick 'glTF Binary (.glb)').", "error")
        return redirect(url_for("admin_ai3d.jobs"))
    try:
        publish = "publish" in request.form
        job = pipeline.add_manual(g.user, request.form.get("archetype", ""), f.read(), request.form.get("name", ""), request.form.get("caption", ""),
                                  publish=publish, make_default="make_default" in request.form)
    except pipeline.PipelineError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_ai3d.jobs"))
    flash("Uploaded and live in My World. Check how it looks below." if publish else "Uploaded. Check how it looks below, then press Publish to show it in My World.", "success")
    return redirect(url_for("admin_ai3d.detail", job_id=job.id))


@bp.route("/upload-folder", methods=["POST"])
@admin_required
def upload_folder():
    """Option 2 of the Blender upload: a whole folder of .glb models at once."""
    files = [(x.filename, x) for x in request.files.getlist("models") if x and x.filename]
    publish = "publish" in request.form
    try:
        result = pipeline.add_manual_folder(g.user, files, request.form.get("archetype", ""), publish=publish,
                                            max_files=current_app.config["AI3D_FOLDER_MAX_FILES"])
    except pipeline.PipelineError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_ai3d.jobs"))
    n, skipped = len(result["added"]), result["skipped"]
    if n:
        live = "and live in My World" if publish else "and waiting for your review (open each one, then press Publish)"
        flash(f"{n} model{'s' if n != 1 else ''} uploaded {live}." + (f" {len(skipped)} skipped." if skipped else ""), "success")
    else:
        flash("No models were added.", "error")
    for name, reason in skipped[:10]:
        flash(f"Skipped {name}: {reason}", "error")
    if len(skipped) > 10:
        flash(f"...and {len(skipped) - 10} more skipped.", "error")
    return redirect(url_for("admin_ai3d.jobs"))


@bp.route("/<int:job_id>")
@admin_required
def detail(job_id):
    job = _job_or_404(job_id)
    return render_template("admin/ai3d_detail.html", job=job, stats=json.loads(job.stats_json or "{}"), options=json.loads(job.options_json or "{}"),
                           clip_names=library.clip_names(job), nav="3d")


@bp.route("/<int:job_id>/<action>", methods=["POST"])
@admin_required
def act(job_id, action):
    job = _job_or_404(job_id)
    if action == "delete" and islands.is_island(job):                    # islands are never hard-deleted from here: soft delete, default protected
        try:
            islands.soft_delete(g.user, [job.id])
            flash("Island deleted. You can restore it from 3D World & Island Management.", "success")
        except islands.IslandError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin_ai3d.detail", job_id=job_id))
        return redirect(url_for("admin_ai3d.island_manager"))
    fn = {"publish": pipeline.publish, "unpublish": pipeline.unpublish, "reject": pipeline.reject, "retry": pipeline.retry, "delete": pipeline.delete}.get(action)
    try:
        if action == "refresh":
            pipeline.advance(job)
            flash("Checked the provider.", "success")
        elif fn:
            fn(g.user, job)
            flash({"publish": "Published. Children can now meet this friend in My World.", "unpublish": "Taken down from My World.", "reject": "Rejected.",
                   "retry": "Retrying.", "delete": "Deleted."}[action], "success")
        else:
            abort(404)
    except pipeline.PipelineError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_ai3d.jobs") if action == "delete" else url_for("admin_ai3d.detail", job_id=job_id))
