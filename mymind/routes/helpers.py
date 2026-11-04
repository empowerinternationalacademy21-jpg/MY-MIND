"""Auth decorators, CSRF helpers and access-flow logic (all enforced on the backend)."""
import hmac
import secrets
from functools import wraps
from flask import g, session, redirect, url_for, flash, request, abort, jsonify
from database.db import Session
from database.models import ChildProfile, CaregiverQuestionnaire
from services import payment_service, verification_service


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf():
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken", "")
    return bool(sent) and hmac.compare_digest(sent, session.get("csrf", ""))


def wants_json():
    return request.path.startswith("/api/")


def deny(message, endpoint, status=403):
    if wants_json():
        return jsonify(error=message), status
    flash(message, "error")
    return redirect(url_for(endpoint))


def child_of(user):
    return Session.query(ChildProfile).filter_by(caregiver_user_id=user.id).first()


def has_questionnaire(child):
    return bool(child and Session.query(CaregiverQuestionnaire).filter_by(child_profile_id=child.id).first())


def next_step(user, login_role=None):
    """Where should this account go next? Used after login and by guards."""
    if user.role == "admin":
        return "admin.dashboard"
    if login_role == "child":
        return "profile.world"
    if verification_service.needs_verification(user):
        return "verification.start"                  # 18+ check comes before plans, trial, questionnaire and the feed
    state = payment_service.access_state(user.id)
    if state != "active":
        return "subscriptions.status"
    if not has_questionnaire(child_of(user)):
        return "onboarding.onboarding"
    return "feed.home"


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not g.user:
            if wants_json():
                return jsonify(error="Please log in."), 401
            return redirect(url_for("auth.login", next=request.path))
        if _child_session() and request.endpoint not in CHILD_ENDPOINTS:
            abort(403)
        return f(*a, **kw)
    return wrapper


CHILD_ENDPOINTS = {
    "feed.home", "feed.explore", "pictures.page", "videos.page", "shots.page", "music.page",
    "api.pictures", "api.videos", "api.shots", "api.music", "api.feed", "api.favorites", "api.recent",
    "api.related", "api.react", "api.favorite", "api.activity_events",
    "profile.world", "world.asset_file", "world.api_assets", "world.asset3d_file",
    "world.api_world", "world.api_world_stop",
}


def _child_session():
    return getattr(g, "auth_role", None) == "child"


def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*a, **kw):
        if g.user.role != "admin":
            abort(403)
        return f(*a, **kw)
    return wrapper


# an unverified caretaker can still reach their data rights and log out
VERIFY_EXEMPT = {"profile.export", "profile.delete_request", "profile.delete_cancel", "auth.logout"}


def caregiver_required(f):
    """Logged-in caregiver (not admin). Used for subscription pages. Closed until the 18+ check is passed (when verification is on)."""
    @wraps(f)
    @login_required
    def wrapper(*a, **kw):
        if _child_session():
            abort(403)
        if g.user.role != "caregiver":
            return redirect(url_for("admin.dashboard"))
        if verification_service.needs_verification(g.user) and request.endpoint not in VERIFY_EXEMPT:
            return deny("Please confirm you are 18 or older first.", "verification.start")
        if (g.user.caretaker_pin_enabled and not session.get("caretaker_pin_verified")
                and request.endpoint != "auth.caretaker_pin"):
            return deny("Enter your caretaker PIN to continue.", "auth.caretaker_pin")
        return f(*a, **kw)
    return wrapper


def subscribed_required(f):
    """Active admin-approved subscription AND completed onboarding. Checked server-side on every request."""
    @wraps(f)
    @login_required
    def wrapper(*a, **kw):
        if g.user.role != "caregiver":
            abort(403)
        if _child_session():
            if request.endpoint not in CHILD_ENDPOINTS:
                abort(403)
            g.child = child_of(g.user)
            if not g.child or not has_questionnaire(g.child):
                abort(403)
            if payment_service.access_state(g.user.id) != "active":
                abort(403)
            return f(*a, **kw)
        if verification_service.needs_verification(g.user) and request.endpoint not in VERIFY_EXEMPT:
            return deny("Please confirm you are 18 or older first.", "verification.start")
        if (g.user.caretaker_pin_enabled and not session.get("caretaker_pin_verified")
                and request.endpoint != "auth.caretaker_pin"):
            return deny("Enter your caretaker PIN to continue.", "auth.caretaker_pin")
        state = payment_service.access_state(g.user.id)
        if state != "active":
            return deny("An active subscription is required.", "subscriptions.status")
        g.child = child_of(g.user)
        if not has_questionnaire(g.child):
            return deny("Please finish the quick questionnaire first.", "onboarding.onboarding")
        return f(*a, **kw)
    return wrapper


def paid_required(f):
    """Active subscription, onboarding may still be incomplete."""
    @wraps(f)
    @caregiver_required
    def wrapper(*a, **kw):
        if payment_service.access_state(g.user.id) != "active":
            return deny("An active subscription is required.", "subscriptions.status")
        return f(*a, **kw)
    return wrapper
