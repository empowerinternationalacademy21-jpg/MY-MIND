"""Caretaker child-profile management and child selection."""
import json
from datetime import datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from database.db import Session
from database.models import (CaregiverChildAccess, CaregiverQuestionnaire, ChildAccount,
                             ChildProfile, ConsentRecord, utcnow)
from routes.helpers import caregiver_required, child_of
from routes.onboarding import AVATARS, POLICY_VERSION
from services import age_service, auth_service, plan_service

bp = Blueprint("caretaker", __name__)


def _owned_child(child_id):
    return Session.query(ChildProfile).filter_by(id=child_id, caregiver_user_id=g.user.id).first()


def _new_child_username(user):
    return auth_service.new_child_username(user)


def _profile_context(children):
    return {"children": children,
            "is_read_only": lambda child: plan_service.child_is_read_only(g.user.id, child),
            "plan": plan_service.current_plan(g.user.id),
            "child_limit": plan_service.child_limit(g.user.id)}


@bp.route("/caretaker/children")
@caregiver_required
def children():
    rows = (Session.query(ChildProfile).filter_by(caregiver_user_id=g.user.id)
            .order_by(ChildProfile.archived_at.isnot(None), ChildProfile.created_at.asc()).all())
    return render_template("caretaker_children.html", avatars=AVATARS, **_profile_context(rows))


@bp.route("/caretaker/children/select/<int:child_id>", methods=["POST"])
@caregiver_required
def select_child(child_id):
    child = _owned_child(child_id)
    if not child or child.archived_at:
        abort(404)
    session["selected_child_id"] = child.id
    return redirect(url_for("auth.caretaker"))


@bp.route("/caretaker/children/add", methods=["POST"])
@caregiver_required
def add_child():
    if not plan_service.has_basic_access(g.user.id):
        flash("Choose a plan before adding child profiles.", "error")
        return redirect(url_for("subscriptions.status"))
    if not plan_service.can_add_child(g.user.id):
        flash(f"Your {plan_service.current_plan(g.user.id).title()} plan allows {plan_service.child_limit(g.user.id)} child profile(s). Upgrade to add another.", "error")
        return redirect(url_for("caretaker.children"))
    name = (request.form.get("display_name") or "").strip()[:40]
    avatar = request.form.get("avatar", "smile")
    if not name or avatar not in AVATARS or request.form.get("consent") != "yes":
        flash("Enter a nickname, choose an avatar, and confirm parental consent.", "error")
        return redirect(url_for("caretaker.children"))
    username = _new_child_username(g.user)
    password = request.form.get("child_password", "")
    try:
        auth_service.validate_password(password, username)
    except auth_service.AuthError as exc:
        flash(str(exc), "error")
        return redirect(url_for("caretaker.children"))
    try:
        age = age_service.parse_age(request.form.get("age")) if request.form.get("age") else None
    except age_service.AgeError as exc:
        flash(str(exc), "error")
        return redirect(url_for("caretaker.children"))
    child = ChildProfile(caregiver_user_id=g.user.id, display_name=name, avatar=avatar,
                         child_username=username, age_years=age)
    Session.add(child)
    Session.flush()
    Session.add(ChildAccount(child_profile_id=child.id, username=username,
                             password_hash=auth_service.hash_password(password)))
    Session.add(CaregiverChildAccess(caregiver_id=g.user.id, child_id=child.id,
                                     status="active", access_role="guardian"))
    Session.add(CaregiverQuestionnaire(child_profile_id=child.id, responses_json=json.dumps({})))
    Session.add(ConsentRecord(user_id=g.user.id, consent_type="child_profile_processing", policy_version=POLICY_VERSION))
    Session.commit()
    session["selected_child_id"] = child.id
    flash(f"{name}'s profile is ready. Their family username is {child.child_username}.", "success")
    return redirect(url_for("auth.caretaker"))


@bp.route("/caretaker/children/<int:child_id>/edit", methods=["POST"])
@caregiver_required
def edit_child(child_id):
    child = _owned_child(child_id)
    if not child or child.archived_at:
        abort(404)
    if plan_service.child_is_read_only(g.user.id, child):
        flash("This profile is read-only on the current plan. Upgrade to edit it.", "error")
        return redirect(url_for("caretaker.children"))
    name = (request.form.get("display_name") or "").strip()[:40]
    avatar = request.form.get("avatar", "smile")
    if not name or avatar not in AVATARS:
        flash("Enter a nickname and choose an avatar.", "error")
        return redirect(url_for("caretaker.children"))
    try:
        age = age_service.parse_age(request.form.get("age")) if request.form.get("age") else None
    except age_service.AgeError as exc:
        flash(str(exc), "error")
        return redirect(url_for("caretaker.children"))
    child.display_name, child.avatar, child.age_years, child.updated_at = name, avatar, age, utcnow()
    Session.commit()
    flash("Child profile updated.", "success")
    return redirect(url_for("caretaker.children"))


@bp.route("/caretaker/children/<int:child_id>/archive", methods=["POST"])
@caregiver_required
def archive_child(child_id):
    child = _owned_child(child_id)
    if not child or child.archived_at:
        abort(404)
    if plan_service.child_is_read_only(g.user.id, child):
        flash("This profile is read-only on the current plan. Upgrade to manage it.", "error")
        return redirect(url_for("caretaker.children"))
    child.archived_at = utcnow()
    Session.commit()
    if session.get("selected_child_id") == child.id:
        session.pop("selected_child_id", None)
    flash("Profile archived. Its history and saved content are kept.", "success")
    return redirect(url_for("caretaker.children"))
