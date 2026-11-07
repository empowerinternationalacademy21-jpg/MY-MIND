import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from database.db import Session
from database.models import (ChildProfile, ChildAccount, CaregiverChildAccess,
                             CaregiverQuestionnaire, ConsentRecord, utcnow)
from services import recommendation_service as rec, settings_service, safety, auth_service
from services import categories as C, age_service
from routes.helpers import paid_required, child_of

bp = Blueprint("onboarding", __name__)
POLICY_VERSION = "2026-10"
AVATARS = ["smile", "star", "heart", "sun", "rocket", "flower-2", "cat", "fish"]


def _clean_list(name, allowed):
    allowed = {k for k, _ in allowed}
    return [v for v in request.form.getlist(name) if v in allowed]


def _text(name, n=300):
    return (request.form.get(name) or "").strip()[:n]


def parse_form():
    r = {
        "activities": _clean_list("activities", C.ACTIVITIES), "activities_other": _text("activities_other"),
        "interests": _clean_list("interests", C.INTERESTS), "communication": _clean_list("communication", C.COMMUNICATION),
        "communication_other": _text("communication_other"), "content_prefs": _clean_list("content_prefs", C.CONTENT_PREFS),
        "favorite_notes": _text("favorite_notes"), "sensory": _clean_list("sensory", C.SENSORY),
        "avoid_content": _text("avoid_content", 500), "safety_notes": _text("safety_notes"),
        "routine": _clean_list("routine", C.ROUTINE), "routine_notes": _text("routine_notes", 500),
    }
    return r


def _age_ctx():
    return {"min_age": age_service.MIN_AGE, "max_age": age_service.MAX_AGE,
            "age_bands": [age_service.BANDS[k] for k in age_service.BAND_ORDER]}


@bp.route("/onboarding", methods=["GET", "POST"])
@paid_required
def onboarding():
    child = child_of(g.user)
    existing = {}
    if child:
        q = Session.query(CaregiverQuestionnaire).filter_by(child_profile_id=child.id).first()
        if q:
            existing = json.loads(q.responses_json or "{}")
    if request.method == "POST":
        if request.form.get("consent") != "yes":
            flash("Please give your consent so we can store the profile and create recommendations.", "error")
            return render_template("onboarding.html", child=child, r=parse_form(), C=C, avatars=AVATARS, **_age_ctx()), 400
        try:
            age = age_service.parse_age(request.form.get("age"))
        except age_service.AgeError as e:
            flash(str(e), "error")
            return render_template("onboarding.html", child=child, r=parse_form(), C=C, avatars=AVATARS, **_age_ctx()), 400
        name = _text("display_name", 40) or "Friend"
        avatar = request.form.get("avatar") if request.form.get("avatar") in AVATARS else "smile"
        responses = parse_form()
        if not child:
            child_username = g.user.child_username
            if Session.query(ChildAccount).filter_by(username=child_username).first():
                child_username = auth_service.new_child_username(g.user)
            child_password = (request.form.get("child_password") or "").strip()
            try:      # the child's own password: required and different from the caretaker's
                auth_service.validate_child_password(g.user, child_password)
            except auth_service.AuthError as exc:
                flash(str(exc), "error")
                return render_template("onboarding.html", child=child, r=parse_form(), C=C, avatars=AVATARS, **_age_ctx()), 400
            child_pwd_hash = auth_service.hash_password(child_password)
            legacy_shared = False
            child = ChildProfile(caregiver_user_id=g.user.id, display_name=name, avatar=avatar,
                                 child_username=child_username, age_years=age)
            Session.add(child)
            Session.flush()
            Session.add(ChildAccount(child_profile_id=child.id, username=child_username,
                                     password_hash=child_pwd_hash, legacy_shared_password=legacy_shared))
            Session.add(CaregiverChildAccess(caregiver_id=g.user.id, child_id=child.id,
                                             status="active", access_role="guardian"))
        else:
            child.display_name, child.avatar = name, avatar
            if age is not None:
                child.age_years = age
        q = Session.query(CaregiverQuestionnaire).filter_by(child_profile_id=child.id).first()
        if q:
            q.responses_json, q.updated_at = json.dumps(responses), utcnow()
        else:
            Session.add(CaregiverQuestionnaire(child_profile_id=child.id, responses_json=json.dumps(responses)))
        Session.add(ConsentRecord(user_id=g.user.id, consent_type="child_profile_processing", policy_version=POLICY_VERSION))
        Session.commit()
        rec.seed_from_questionnaire(child.id, responses)
        if responses["avoid_content"]:      # carry "content to avoid" into the content filter
            cur = settings_service.caregiver_settings(g.user.id)["avoid_keywords"]
            merged = ", ".join(dict.fromkeys(safety.parse_keywords(cur) + safety.parse_keywords(responses["avoid_content"])))
            settings_service.save_caregiver_settings(g.user.id, {"avoid_keywords": merged})
        flash("Thank you! Your child's personal world is ready.", "success")
        return redirect(url_for("feed.home"))
    return render_template("onboarding.html", child=child, r=existing, C=C, avatars=AVATARS, **_age_ctx())
