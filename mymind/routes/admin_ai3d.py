"""Admin → AI 3D: create jobs from allow-listed choices, watch them, review, publish."""
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from database.db import Session
from database.models import Asset3D
from routes.helpers import admin_required
from services import auth_service
from services.ai3d import library, optimize, pipeline, providers, safe_prompts

bp = Blueprint("admin_ai3d", __name__, url_prefix="/admin/3d")


def _job_or_404(job_id):
    job = Session.get(Asset3D, job_id)
    if not job:
        abort(404)
    return job


@bp.route("/")
@admin_required
def jobs():
    rows = Session.query(Asset3D).order_by(Asset3D.id.desc()).limit(100).all()
    return render_template("admin/ai3d.html", jobs=rows, catalog=safe_prompts.catalog(), colors=list(safe_prompts.COLORS), styles=list(safe_prompts.STYLES),
                           moods=list(safe_prompts.MOODS), accessories=list(safe_prompts.ACCESSORIES), archetypes=safe_prompts.ARCHETYPES, kit=safe_prompts.kit_catalog(),
                           provider_ready={n: c.configured() for n, c in providers.PROVIDERS.items()}, concept_ready=providers.concept_configured(),
                           optimizer=optimize.available(), nav="3d")


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
