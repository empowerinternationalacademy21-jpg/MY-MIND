"""Resumable AI 3D pipeline. All state lives in the `assets3d` row, so a restart or a crash loses nothing.

items:       text -> 3D (Meshy preview -> refine PBR, or Tripo text_to_model)           -> fetch -> REVIEW
characters:  safe prompt -> 2D concept (OpenAI/Stability) -> image-to-3D -> auto-rig
             (Meshy: walk/run come with the rig; Tripo: animate_retarget walk + run)   -> fetch -> REVIEW
REVIEW -> an administrator approves (published: visible to caregivers' children) or rejects. Nothing is ever published automatically.
"""
import json
import logging
import os
import secrets
from datetime import timedelta
from sqlalchemy import or_
from flask import current_app
from database.db import Session
from database.models import Asset3D, utcnow
from services import auth_service
from services.ai3d import download, glb, library, optimize, providers, safe_prompts

log = logging.getLogger("mymind.ai3d")
POLL_SECONDS = 8
LIVE = ("queued", "running")


class PipelineError(Exception):
    """Safe to show to an administrator."""


def create_job(admin, archetype, options, provider_name, name="", caption="", flow=None):
    try:
        info = safe_prompts.archetype_info(archetype)
        name = safe_prompts.check_label(name, "name")[:80]
        caption = safe_prompts.check_label(caption, "caption")[:240]
        prompt, opts = safe_prompts.build_prompt(archetype, options)
        provider = providers.get(provider_name)
    except (safe_prompts.PromptRefused, providers.ProviderError) as exc:
        raise PipelineError(str(exc))
    if not provider.configured():
        raise PipelineError(f"{provider_name.capitalize()} isn't set up yet (its API key is missing on the server).")
    if flow is None:                       # landmarks use concept image -> image-to-3D when a concept provider exists, else plain text-to-3D
        flow = "image" if (info["kind"] == "landmark" and providers.concept_configured()) else ("char" if info["kind"] == "character" else "text")
    if flow in ("image", "char") and not providers.concept_configured():
        raise PipelineError("Characters need a concept-image provider (OPENAI_API_KEY or STABILITY_API_KEY) which isn't set up yet.")
    since = utcnow() - timedelta(days=1)
    if Session.query(Asset3D).filter(Asset3D.created_at >= since).count() >= current_app.config["AI3D_MAX_JOBS_PER_DAY"]:
        raise PipelineError("The daily limit for generated models has been reached. This protects your provider credits.")
    job = Asset3D(category=info["category"], archetype=archetype, kind=info["kind"], name=name or info["label"], caption=caption,
                  provider=provider_name, options_json=json.dumps(opts), prompt=prompt, stage="start", status="queued",
                  tasks_json=json.dumps({"flow": flow}), next_poll_at=utcnow(), created_by=admin.id)
    Session.add(job)
    Session.flush()
    auth_service.audit(admin.id, "ai3d_job_created", "asset3d", job.id, f"{archetype}/{provider_name}")     # the prompt is kept on the row, not in the log
    Session.commit()
    return job


MANUAL_MAX_TRIANGLES = 400_000          # hard stop: far beyond what a phone can draw


def add_manual(admin, archetype, raw, name="", caption="", publish=False, make_default=False):
    """An administrator's OWN model (made in Blender or any free tool), exported as a self-contained .glb. It is validated,
    optionally web-optimised and stored privately. With publish=True (the admin upload form's default) it goes live in My World at once;
    otherwise it waits in REVIEW like an AI model. An island base can also become the default island everyone sees until they choose another."""
    try:
        info = safe_prompts.archetype_info(archetype)
        name = safe_prompts.check_label(name, "name")[:80]
        caption = safe_prompts.check_label(caption, "caption")[:240]
    except safe_prompts.PromptRefused as exc:
        raise PipelineError(str(exc))
    limit = current_app.config["AI3D_MANUAL_MAX_BYTES"]
    if not raw:
        raise PipelineError("Please choose a .glb file to upload.")
    if len(raw) > limit:
        raise PipelineError(f"That file is {len(raw) // (1024 * 1024)} MB. The limit is {limit // (1024 * 1024)} MB: shrink the textures or use Draco/Meshopt compression when exporting.")
    try:
        doc = glb.parse(raw)
        stats = glb.stats(raw)
    except glb.GlbError as exc:
        raise PipelineError(str(exc))
    for item in list(doc.get("buffers", [])) + list(doc.get("images", [])):
        uri = item.get("uri") if isinstance(item, dict) else None
        if uri and not str(uri).startswith("data:"):
            raise PipelineError("This model points to outside files. In Blender export as 'glTF Binary (.glb)' so the textures are packed inside it.")
    if stats["meshes"] == 0 or stats["triangles"] == 0:
        raise PipelineError("The model has no mesh in it. Select your objects and tick 'Selected Objects' only if they are all selected, then export again.")
    if stats["triangles"] > MANUAL_MAX_TRIANGLES:
        raise PipelineError(f"{stats['triangles']:,} triangles is too heavy for phones (limit {MANUAL_MAX_TRIANGLES:,}). Use Blender's Decimate modifier and export again.")
    data, opt = optimize.optimize(raw)
    final = {**glb.stats(data), **opt}
    budget = current_app.config["AI3D_TARGET_POLYS"] * (8 if info["kind"] == "landmark" else 2)
    warnings = [opt["note"]] if opt.get("optimizer") == "failed" else []
    if final["triangles"] > budget:
        warnings.append(f"{final['triangles']:,} triangles is above the {budget:,} suggested for this piece; it may be slow on older phones.")
    if final["bytes"] > 8 * 1024 * 1024:
        warnings.append(f"The file is {final['bytes'] // (1024 * 1024)} MB; large files load slowly on mobile data.")
    job = Asset3D(category=info["category"], archetype=archetype, kind=info["kind"], name=name or info["label"], caption=caption,
                  provider="manual", options_json="{}", prompt="Uploaded by an administrator", stage="done", status="review",
                  tasks_json=json.dumps({"flow": "manual"}), created_by=admin.id)
    Session.add(job)
    Session.flush()
    fname = f"{job.id}-glb-{secrets.token_hex(6)}.glb"
    with open(os.path.join(library.private_dir(), fname), "wb") as fh:
        fh.write(data)
    job.glb_filename = fname
    job.stats_json = json.dumps({**final, "clip_bytes": {}, "warnings": warnings})
    job.rigged = info["kind"] == "character" and final["skins"] > 0
    auth_service.audit(admin.id, "ai3d_manual_upload", "asset3d", job.id, archetype)
    if publish:
        job.status, job.reviewed_by = "published", admin.id
        auth_service.audit(admin.id, "ai3d_published", "asset3d", job.id, archetype)
        if info["category"] == "island":
            from services import settings_service
            have_default = any(str(a.id) == (settings_service.get("default_island_id") or "") for a in library.island_bases() if a.id != job.id)
            if make_default or not have_default:                                    # the first island is always the default
                settings_service.set_value("default_island_id", str(job.id))
    Session.commit()
    return job


def _fail(job, message):
    job.status, job.error, job.next_poll_at = "failed", (message or "Something went wrong.")[:400], None


def _schedule(job, seconds=POLL_SECONDS):
    job.next_poll_at = utcnow() + timedelta(seconds=seconds)


def _stages(job, prov, tasks):
    flow = tasks.get("flow") or ("char" if job.kind == "character" else "text")
    return prov.CHAR_STAGES if flow == "char" else prov.IMG_STAGES if flow == "image" else prov.ITEM_STAGES


def _concept(job, tasks):
    png = providers.make_concept(job.prompt)
    name = f"{job.id}-concept-{secrets.token_hex(6)}.png"
    with open(os.path.join(library.private_dir(), name), "wb") as fh:
        fh.write(png)
    job.concept_filename = name
    stages = _stages(job, providers.get(job.provider), tasks)
    job.stage = stages[stages.index("concept") + 1]
    job.next_poll_at = utcnow()


def _concept_png(job):
    path = os.path.join(library.private_dir(), job.concept_filename or "missing")
    if not job.concept_filename or not os.path.exists(path):
        raise PipelineError("The concept image is missing. Retry the job.")
    with open(path, "rb") as fh:
        return fh.read()


def _provider_stage(job, tasks, prov, stage, stages):
    tid = tasks.get(stage)
    if not tid:
        parent = {"refine": "preview", "rig": "image3d", "anim_walk": "rig", "anim_run": "rig"}.get(stage)
        kw = {"prompt": job.prompt}
        if parent:
            kw["parent"] = tasks.get(parent)
            if not kw["parent"]:
                raise PipelineError(f"An earlier step ({parent}) has no task. Retry the job.")
        if stage == "image3d":
            kw["image_png"] = _concept_png(job)
        tasks[stage] = prov.start(stage, **kw)
        _schedule(job)
        return
    res = prov.poll(stage, tid)
    if res.status == "failed":
        raise PipelineError(res.error or "The provider could not finish this step.")
    if res.status != "success":
        _schedule(job)
        return
    tasks.setdefault("urls", {})[stage] = res.urls
    job.stage = stages[stages.index(stage) + 1]
    job.next_poll_at = utcnow()


def _sources(job, tasks):
    """-> {'glb': url, 'walk': url, ...} the files to download for this job."""
    urls = tasks.get("urls", {})
    if job.kind != "character":
        stage = "image3d" if tasks.get("flow") == "image" else ("refine" if job.provider == "meshy" else "text3d")
        return {"glb": (urls.get(stage) or {}).get("glb")}
    if job.provider == "meshy":
        rig = urls.get("rig") or {}
        return {"glb": rig.get("glb"), "walk": rig.get("walk"), "run": rig.get("run")}
    return {"glb": (urls.get("rig") or {}).get("glb"), "walk": (urls.get("anim_walk") or {}).get("glb"), "run": (urls.get("anim_run") or {}).get("glb")}


def _fetch(job, tasks):
    sources = {k: v for k, v in _sources(job, tasks).items() if v}
    if "glb" not in sources:
        raise PipelineError("The provider returned no model to download.")
    token = secrets.token_hex(6)
    files, sizes, primary_stats, notes = {}, {}, None, []
    for key, url in sources.items():
        data = download.fetch_glb(url)
        data, info = optimize.optimize(data)
        fname = f"{job.id}-{key}-{token}.glb"
        with open(os.path.join(library.private_dir(), fname), "wb") as fh:
            fh.write(data)
        files[key], sizes[key] = fname, len(data)
        if key == "glb":
            primary_stats = {**glb.stats(data), **info}
        if info.get("optimizer") == "failed":
            notes.append(f"{key}: {info.get('note')}")
    budget = current_app.config["AI3D_TARGET_POLYS"]
    warnings = list(notes)
    if primary_stats["triangles"] > budget * 2:
        warnings.append(f"{primary_stats['triangles']:,} triangles is well over the {budget:,} budget; it may be slow on phones.")
    if job.kind == "character" and primary_stats["skins"] == 0:
        warnings.append("No skeleton was found in this character.")
    job.glb_filename = files.pop("glb")
    job.clips_json = json.dumps(files)
    job.stats_json = json.dumps({**primary_stats, "clip_bytes": {k: v for k, v in sizes.items() if k != "glb"}, "warnings": warnings})
    job.rigged = job.kind == "character" and primary_stats["skins"] > 0
    job.status, job.stage, job.error, job.next_poll_at = "review", "done", "", None


def advance(job):
    """Do one step of work for a job. Never raises: failures are recorded on the job (admin-safe text) and logged."""
    if job.status not in LIVE:
        return job
    prov = providers.get(job.provider)
    tasks = json.loads(job.tasks_json or "{}")
    stages = _stages(job, prov, tasks)
    try:
        if job.stage == "start":
            job.stage = stages[0]
        job.status = "running"
        if job.stage == "concept":
            _concept(job, tasks)
        elif job.stage == "fetch":
            _fetch(job, tasks)
        else:
            _provider_stage(job, tasks, prov, job.stage, stages)
    except (providers.ProviderError, download.DownloadError, PipelineError, glb.GlbError) as exc:
        _fail(job, str(exc))
    except Exception:                                                              # a bug must not stall the whole worker
        log.exception("ai3d job %s crashed", job.id)
        _fail(job, "Unexpected error. See the server log.")
    job.tasks_json = json.dumps(tasks)
    Session.commit()
    return job


def run_due(limit=10):
    now = utcnow()
    jobs = (Session.query(Asset3D).filter(Asset3D.status.in_(LIVE), or_(Asset3D.next_poll_at.is_(None), Asset3D.next_poll_at <= now))
            .order_by(Asset3D.id).limit(limit).all())
    for j in jobs:
        advance(j)
    return len(jobs)


# ---- admin decisions ----
def publish(admin, job):
    if job.status != "review" or not job.glb_filename:
        raise PipelineError("Only a finished model waiting for review can be published.")
    job.status, job.reviewed_by = "published", admin.id
    auth_service.audit(admin.id, "ai3d_published", "asset3d", job.id, job.archetype)
    Session.commit()


def unpublish(admin, job):
    if job.status != "published":
        raise PipelineError("This model is not published.")
    job.status, job.reviewed_by = "review", admin.id
    auth_service.audit(admin.id, "ai3d_unpublished", "asset3d", job.id, job.archetype)
    Session.commit()


def reject(admin, job):
    if job.status not in ("review", "published", "failed"):
        raise PipelineError("This job is still running.")
    job.status, job.reviewed_by = "rejected", admin.id
    auth_service.audit(admin.id, "ai3d_rejected", "asset3d", job.id, job.archetype)
    Session.commit()


def retry(admin, job):
    if job.status != "failed":
        raise PipelineError("Only failed jobs can be retried.")
    tasks = json.loads(job.tasks_json or "{}")
    tasks.pop(job.stage, None)                                                      # restart the step that failed, keep earlier results
    job.tasks_json = json.dumps(tasks)
    job.status, job.error, job.next_poll_at = "queued", "", utcnow()
    auth_service.audit(admin.id, "ai3d_retry", "asset3d", job.id, job.stage)
    Session.commit()


def delete(admin, job):
    library.remove_files(job)
    jid = job.id
    Session.delete(job)
    auth_service.audit(admin.id, "ai3d_deleted", "asset3d", jid, None)
    Session.commit()


def create_kit(admin, provider_name):
    """Queue the whole island kit (base + one landmark per place), skipping pieces that already have a live or published model.
    Returns (created, skipped, stopped_by_cap)."""
    existing = {}
    for j in Session.query(Asset3D).filter(Asset3D.kind == "landmark", Asset3D.status.in_(("queued", "running", "review", "published"))).all():
        existing[j.archetype] = j
    created, skipped = [], []
    for key in safe_prompts.KIT_ORDER:
        if key in existing:
            skipped.append(key)
            continue
        try:
            created.append(create_job(admin, key, {}, provider_name, name=safe_prompts.LANDMARKS[key][2]))
        except PipelineError as exc:
            if "daily limit" in str(exc) and created:
                return created, skipped, True
            raise
    return created, skipped, False