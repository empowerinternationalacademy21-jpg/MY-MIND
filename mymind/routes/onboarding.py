import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from database.db import Session
from database.models import ChildProfile, CaregiverQuestionnaire, ConsentRecord, utcnow
from services import recommendation_service as rec, settings_service, safety
from services import categories as C
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
            return render_template("onboarding.html", child=child, r=parse_form(), C=C, avatars=AVATARS), 400
        name = _text("display_name", 40) or "Friend"
        avatar = request.form.get("avatar") if request.form.get("avatar") in AVATARS else "smile"
        responses = parse_form()
        if not child:
            child = ChildProfile(caregiver_user_id=g.user.id, display_name=name, avatar=avatar)
            Session.add(child)
            Session.flush()
        else:
            child.display_name, child.avatar = name, avatar
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
    return render_template("onboarding.html", child=child, r=existing, C=C, avatars=AVATARS)
