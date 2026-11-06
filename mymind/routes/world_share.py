"""Anonymous, read-only previews of a single child's world."""
from datetime import timedelta

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, session, url_for

from database.db import Session
from database.models import ChildProfile, ContentItem, User, utcnow
from routes.helpers import caregiver_required, child_of, login_required
from services import activity_service, cache, caretaker_dashboard_service as dashboard
from services import content_service, world_service, world_share_service as shares
from services import caretaker_recommendation_engine as recommendations
from services import age_service, plan_service, recommendation_service as rec, safety, settings_service, child_scope

bp = Blueprint("world_share", __name__)


def _ip():
    return request.remote_addr or "?"


def _unavailable(status=404):
    return render_template("world_share_unavailable.html"), status


def _resolve(token):
    link = shares.find(token)
    if not shares.is_active(link):
        return None, None, None
    child = Session.get(ChildProfile, link.child_profile_id)
    owner = Session.get(User, child.caregiver_user_id) if child else None
    return (link, child, owner) if child and owner else (None, None, None)


def _safe_world(owner, child, api_root):
    data = world_service.payload(owner, child)
    data["mode"] = "preview"
    data["api_root"] = api_root
    data["settings"] = {"theme": "auto", "island": "classic", "strength": "balanced", "interests": [],
                        "sports_zones": [], "rotation": False, "animation": False,
                        "hidden_stops": [], "decor_off": [], "sound": False, "real_people": False}
    data["backgrounds"] = []
    data["island_base"] = None
    data["options"] = {}
    today = utcnow().date()
    time_by_stop = activity_service.minutes_per_stop(child.id, today - timedelta(days=6), today)
    for stop in data["stops"]:
        minutes = time_by_stop.get(stop["key"], 0)
        if stop["key"] == "sports":
            minutes += sum(time_by_stop.get(key, 0) for key in ("soccer", "basketball"))
        stop["time_label"] = f"{int(minutes // 60)}h {int(minutes % 60)}m" if minutes >= 60 else f"{int(minutes)}m"
        stop["badge"] = None
        stop["landmark3d"] = None
        stop["characters"] = 0
        stop["chars"] = []
        stop["friends3d"] = 0
        stop["shelf"] = {"endpoint": f"{api_root}/content", "params": {"stop": stop["key"]}}
    return data


def _stop_detail(owner, child, key, api_root):
    detail = world_service.stop_detail(owner, child, key)
    if detail is None:
        return None
    detail["friends3d"] = []
    detail["characters"] = []
    detail["interior"] = None
    if detail.get("shelf"):
        detail["shelf"] = {"endpoint": f"{api_root}/content", "params": {"stop": key}}
    return detail


def _content_response(owner, child, stop, page):
    from services.world_service import STOP_DEFS
    definition = STOP_DEFS.get(stop)
    if not definition or not definition.get("shelf"):
        return None
    if page < 1 or page > 100:
        return jsonify(error="Invalid page."), 400
    endpoint, params = definition["shelf"]
    allowed_categories = set(age_service.allowed_categories(child.age_years))
    category = params.get("category")
    if category and category not in allowed_categories:
        return jsonify(error="This place is not available for this profile."), 404
    kind = {"/api/videos": "video", "/api/shots": "short", "/api/music": "song"}.get(endpoint, "picture")
    query = Session.query(ContentItem).filter(ContentItem.content_type == kind)
    if category:
        query = query.filter(ContentItem.category == category)
    else:
        query = query.filter(ContentItem.category.in_(allowed_categories))
    block = content_service.blocklist_for(settings_service.caregiver_settings(owner.id), child.age_years)
    hidden = rec.disliked_ids(child.id)
    safe_rows = [row for row in query.order_by(ContentItem.id.desc()).all()
                 if row.id not in hidden and safety.is_allowed(row.title, row.description, block)]
    start = (page - 1) * 8
    rows = safe_rows[start:start + 9]
    return jsonify(items=content_service.serialise(rows[:8], child.id), more=len(rows) > 8)


def _weekly_summary(child, owner):
    today = utcnow().date()
    start = today - timedelta(days=6)
    snapshot = dashboard.snapshot(child.id, start, today, today)
    snapshot["interests"] = [item for item in rec.get_interests(child.id)
                              if item["score"] > 0 and item["evidence"] > 0][:5]
    snapshot["recommendations"] = recommendations.get_recommendations(child.id, owner.id)
    return snapshot


@bp.route("/world/share/<token>")
def view(token):
    if cache.rate_limited(f"world-share-ip:{_ip()}", 60, 60):
        return _unavailable(429)
    link, child, owner = _resolve(token)
    if not link:
        return _unavailable()
    shares.note_opened(link)
    root = f"/world/share/{token}"
    world_data = _safe_world(owner, child, root)
    week = _weekly_summary(child, owner)
    return render_template("world_preview.html", child=child, world_data=world_data, week=week, world_mode="preview",
                           token=token, mode="public")


@bp.route("/world/share/<token>/stop/<key>")
def stop_detail(token, key):
    if cache.rate_limited(f"world-share-ip:{_ip()}", 60, 60):
        return jsonify(error="This link is temporarily unavailable."), 429
    link, child, owner = _resolve(token)
    if not link:
        return jsonify(error="This link is no longer available."), 404
    detail = _stop_detail(owner, child, key, f"/world/share/{token}")
    if detail is None:
        abort(404)
    return jsonify(detail)


@bp.route("/world/share/<token>/content")
def content(token):
    if cache.rate_limited(f"world-share-ip:{_ip()}", 60, 60):
        return jsonify(error="This link is temporarily unavailable."), 429
    link, child, _owner = _resolve(token)
    if not link:
        return jsonify(error="This link is no longer available."), 404
    stop = request.args.get("stop", "")
    page = request.args.get("page", 1, type=int)
    result = _content_response(_owner, child, stop, page)
    return result if result is not None else (jsonify(error="Unknown place."), 404)


def _resolve_caretaker_child(child_uid):
    child = child_scope.resolve_child_uid(g.user.id, child_uid)
    if child:
        return child
    try:
        child_id = int(child_uid)
    except (TypeError, ValueError):
        return None
    return Session.query(ChildProfile).filter_by(id=child_id, caregiver_user_id=g.user.id).first()


@bp.route("/caretaker/children/<child_uid>/world-preview")
@caregiver_required
def caretaker_preview(child_uid):
    child = _resolve_caretaker_child(child_uid)
    if not child:
        abort(404)
    root = url_for("world_share.caretaker_preview", child_uid=child.public_uid).rsplit("/world-preview", 1)[0] + "/world-preview"
    world_data = _safe_world(g.user, child, root)
    return render_template("world_preview.html", child=child, world_data=world_data,
                           week=_weekly_summary(child, g.user), world_mode="preview", mode="embedded")


@bp.route("/caretaker/children/<child_uid>/world-preview/stop/<key>")
@caregiver_required
def caretaker_preview_stop(child_uid, key):
    child = _resolve_caretaker_child(child_uid)
    if not child:
        abort(404)
    root = f"/caretaker/children/{child.public_uid}/world-preview"
    detail = _stop_detail(g.user, child, key, root)
    return jsonify(detail) if detail is not None else (jsonify(error="Unknown place."), 404)


@bp.route("/caretaker/children/<child_uid>/world-preview/content")
@caregiver_required
def caretaker_preview_content(child_uid):
    child = _resolve_caretaker_child(child_uid)
    if not child:
        abort(404)
    result = _content_response(g.user, child, request.args.get("stop", ""), request.args.get("page", 1, type=int))
    return result if result is not None else (jsonify(error="Unknown place."), 404)


@bp.route("/caretaker/share-links", methods=["POST"])
@caregiver_required
def create_link():
    if not plan_service.can_use(g.user.id, "share_world"):
        flash("Choose a plan before creating a share link.", "error")
        return redirect(url_for("subscriptions.status"))
    child = child_of(g.user)
    if not child:
        flash("Create a child profile before sharing a world.", "error")
        return redirect(url_for("auth.caretaker"))
    if plan_service.child_is_read_only(g.user.id, child):
        flash("This child profile is read-only on the current plan. Upgrade to share it.", "error")
        return redirect(url_for("auth.caretaker"))
    limit = plan_service.active_share_limit(g.user.id)
    active_count = sum(shares.status_of(link) == "active" for link in shares.links_for(child))
    if limit is not None and active_count >= limit:
        flash("Your Free plan includes one active share link. Revoke it or upgrade for more.", "error")
        return redirect(url_for("auth.caretaker"))
    try:
        link, token = shares.create(child, request.form.get("expiry", "7d"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("auth.caretaker"))
    session["new_world_share_url"] = url_for("world_share.view", token=token, _external=True)
    flash("A private share link was created. Copy it now; the token is not stored in readable form.", "success")
    return redirect(url_for("auth.caretaker"))


@bp.route("/caretaker/share-links/<int:link_id>/revoke", methods=["POST"])
@caregiver_required
def revoke_link(link_id):
    child = child_of(g.user)
    if not child or not shares.revoke(child, link_id):
        abort(404)
    flash("Share link revoked.", "success")
    return redirect(url_for("auth.caretaker"))


@bp.route("/world/share-link", methods=["POST"])
@login_required
def create_child_link():
    if g.auth_role != "child":
        abort(403)
    if not plan_service.can_use(g.user.id, "share_world"):
        abort(403)
    child = child_of(g.user)
    if not child or plan_service.child_is_read_only(g.user.id, child):
        abort(403)
    limit = plan_service.active_share_limit(g.user.id)
    active_count = sum(shares.status_of(link) == "active" for link in shares.links_for(child))
    if limit is not None and active_count >= limit:
        flash("Ask your caretaker to revoke the current link or upgrade the plan before creating another.", "error")
        return redirect(url_for("profile.world"))
    try:
        _link, token = shares.create(child, request.form.get("expiry", "7d"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("profile.world"))
    session["new_world_share_url"] = url_for("world_share.view", token=token, _external=True)
    flash("Your private world link is ready. Share it only with someone you trust.", "success")
    return redirect(url_for("profile.world"))