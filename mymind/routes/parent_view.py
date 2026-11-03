"""Parent links. `bp` = public family view under /p/<token>; `manage` = the caregiver's page to create and revoke links."""
import time
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session, abort
from routes.helpers import caregiver_required, child_of, subscribed_required
from routes.onboarding import AVATARS
from services import cache, parent_link_service as pls

bp = Blueprint("parent_view", __name__, url_prefix="/p")
manage = Blueprint("parent_links", __name__)


def _ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()


def _unavailable():
    return render_template("parent_unavailable.html"), 404


def _granted(link):
    grants = session.get("pl") or {}
    exp = grants.get(str(link.id))
    return bool(exp and exp > time.time())


@bp.route("/<token>", methods=["GET", "POST"])
def gate(token):
    if cache.rate_limited(f"pl-ip:{_ip()}", 40, 60):
        return render_template("parent_unavailable.html", throttled=True), 429
    link = pls.find(token)
    if not pls.is_active(link):
        return _unavailable()
    if request.method == "POST":
        if cache.rate_limited(f"pl-try:{_ip()}", 12, 600):
            return render_template("parent_gate.html", token=token, error="Too many tries. Please wait a few minutes."), 429
        result = pls.try_password(link, request.form.get("password", ""))
        if result == "ok":
            grants = dict(session.get("pl") or {})
            grants[str(link.id)] = time.time() + pls.VIEW_SESSION_SECONDS
            session["pl"] = grants
            return redirect(url_for("parent_view.view", token=token))
        if result == "locked":
            return render_template("parent_gate.html", token=token, error=f"Too many wrong passwords. This link is paused for {pls.LOCK_MINUTES} minutes."), 429
        return render_template("parent_gate.html", token=token, error="That password isn't right."), 403
    if _granted(link):
        return redirect(url_for("parent_view.view", token=token))
    return render_template("parent_gate.html", token=token, error=pls.locked(link) and f"This link is paused for a few minutes after too many wrong passwords." or None)


@bp.route("/<token>/view")
def view(token):
    link = pls.find(token)
    if not pls.is_active(link):                       # revoke / expiry apply immediately, even mid-session
        return _unavailable()
    if not _granted(link):
        return redirect(url_for("parent_view.gate", token=token))
    from database.db import Session
    from database.models import ChildProfile
    child = Session.get(ChildProfile, link.child_profile_id)
    pls.note_view(link)
    return render_template("parent_home.html", child=child, w=pls.world_for(child), token=token,
                           avatar=child.avatar if child.avatar in AVATARS else "smile")


@bp.route("/<token>/leave", methods=["POST"])
def leave(token):
    link = pls.find(token)
    if link:
        grants = dict(session.get("pl") or {}); grants.pop(str(link.id), None); session["pl"] = grants
    return redirect(url_for("parent_view.gate", token=token) if link else url_for("auth.index"))


# ---------------- caregiver side ----------------
@manage.route("/settings/parent-links", methods=["GET", "POST"])
@subscribed_required
def page():
    child = g.child if g.get("child") else child_of(g.user)
    new_url = None
    if request.method == "POST":
        try:
            link, token = pls.create(child, request.form.get("label"), request.form.get("password"), request.form.get("duration", "30"))
            new_url = url_for("parent_view.gate", token=token, _external=True)
            flash("Link created. Copy it now: for safety it can't be shown again.", "success")
        except pls.LinkError as exc:
            flash(str(exc), "error")
    return render_template("parent_links.html", links=pls.links_for(child), status_of=pls.status_of, new_url=new_url, child=child,
                           durations=[("7", "7 days"), ("30", "30 days"), ("90", "90 days"), ("never", "Until I revoke it")], active="settings")


@manage.route("/settings/parent-links/<int:link_id>/revoke", methods=["POST"])
@subscribed_required
def revoke(link_id):
    child = g.child if g.get("child") else child_of(g.user)
    if not pls.revoke(child, link_id):
        abort(404)
    flash("Link revoked. It stops working immediately.", "success")
    return redirect(url_for("parent_links.page"))
