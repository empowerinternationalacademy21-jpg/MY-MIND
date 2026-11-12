import json
import re
from datetime import date
from flask import Blueprint, abort, render_template, request, redirect, url_for, flash, g, Response, session
from database.db import Session
from database.models import ChildAccount, ChildProfile, Favorite, ContentItem, DailyActivity, Subscription, PaymentVerificationRequest, utcnow
from services import recommendation_service as rec, settings_service, auth_service, payment_service, account_service, safety, age_service
from services.categories import CATEGORIES
from services import world_service
from routes.helpers import subscribed_required, caregiver_required, child_of
from routes.onboarding import AVATARS

bp = Blueprint("profile", __name__)

WORLD_NOTES = {
    "animals": ("Animal Garden", "A little corner for the animals you enjoy.", 14, 67),
    "nature": ("Nature Meadow", "Flowers, forests and fresh discoveries.", 68, 39),
    "food": ("Food Paradise", "A tasty trail through food you enjoy.", 70, 24),
    "vehicles": ("Roadway Ridge", "Trains, cars and journeys you have explored.", 27, 48),
    "music": ("Music Garden", "Songs, sounds and rhythms that catch your ear.", 19, 43),
    "sports": ("Sports Arena", "Soccer, swimming and other ways you like to play.", 78, 20),
    "toys": ("Toy Workshop", "A place for building, imagining and play.", 35, 75),
    "people": ("Friendship Square", "A warm corner for family and friends.", 44, 80),
    "places": ("Wonderland Way", "Places and settings you have chosen to explore.", 68, 29),
    "colors": ("Color Trail", "Bright shapes and colors along your path.", 54, 47),
    "art": ("Art Studio", "Ideas, colors and things you can create.", 68, 59),
    "objects": ("Everyday Discoveries", "Familiar things with new details to notice.", 45, 58),
    "cartoons": ("Story Screen", "Animated characters and shows you enjoy.", 34, 28),
    "stories": ("Storybook Nook", "Stories and pictures to wander through.", 42, 32),
    "dancing": ("Dance Garden", "Movement, music and room to dance.", 22, 55),
    "water": ("Waterfall Cove", "Splashes, waves and water play.", 72, 76),
}


def world_extras():
    """Admin-approved art and published 3D friends for My World. Real-person art only when the caregiver switched it on."""
    from services import world_library_service as wl
    from services.ai3d import library as a3d
    show = settings_service.caregiver_settings(g.user.id)["show_real_people"]
    art = [a for a in wl.visible(show, kind=None) if a.kind in ("character", "island", "interior")][:24]
    published = a3d.published()
    return {"world_art": art, "world_3d": published, "a3d_clips": {a.id: a3d.clip_names(a) for a in published}}


@bp.route("/world")
@subscribed_required
def world():
    """The 2D island is the base world for everyone (children and caregivers)."""
    from services import world2d_service
    return render_template("my_world_2d.html", scene=world2d_service.scene(g.user, g.child), active="world",
                           share_url=session.pop("new_world_share_url", None), can_3d=(g.auth_role != "child"))


@bp.route("/world/3d")
@subscribed_required
def world_3d():
    """The full 3D world view, kept for caregivers."""
    if g.auth_role == "child":
        return redirect(url_for("profile.world"))
    interests = rec.get_interests(g.child.id)
    now = utcnow()
    enjoy = [i for i in interests if i["score"] >= 3 and i["evidence"] >= 3]
    exploring = [i for i in interests if 0.5 < i["score"] and i not in enjoy]
    landmarks = []
    for interest in interests:
        category = interest["category"]
        if interest["score"] <= 0 or category not in CATEGORIES or category not in WORLD_NOTES:
            continue
        place, note, x, y = WORLD_NOTES[category]
        landmarks.append({**interest, **CATEGORIES[category], "place": place, "note": note, "x": x, "y": y})
    landmarks = landmarks[:5]
    new = [i for i in interests if i["first_observed_at"] and (now - i["first_observed_at"]).days <= 14 and i["evidence"] > 0]
    dislike = [i for i in interests if i["score"] < -0.5]
    favs = (Session.query(ContentItem).join(Favorite, Favorite.content_item_id == ContentItem.id)
            .filter(Favorite.child_profile_id == g.child.id).order_by(Favorite.id.desc()).limit(60).all())
    notes = (Session.query(DailyActivity).filter_by(child_profile_id=g.child.id, source="caregiver")
             .order_by(DailyActivity.id.desc()).limit(8).all())
    return render_template("my_world.html", enjoy=enjoy, exploring=exploring, new=new, dislike=dislike, notes=notes,
                           landmarks=landmarks, world_favorites=favs[:12], theme_key=f"myworld-theme-{g.child.id}", active="world",
                           fav_pics=[f for f in favs if f.content_type == "picture"],
                           fav_vids=[f for f in favs if f.content_type in ("video", "short")],
                           fav_songs=[f for f in favs if f.content_type == "song"], categories=CATEGORIES,
                           share_url=session.pop("new_world_share_url", None),
                           world_data=world_service.payload(g.user, g.child), can_see_activity=(g.auth_role == "caregiver"),
                           **world_extras())


@bp.route("/world/interest/<category>", methods=["POST"])
@subscribed_required
def world_interest(category):
    mode = request.form.get("mode")
    if category not in CATEGORIES or mode not in ("more", "less", "remove"):
        flash("Invalid choice.", "error")
        return redirect(url_for("profile.world_3d"))
    if mode == "more":
        rec.record_interaction(g.child.id, None, "like", category)
    else:
        rec.caregiver_adjust(g.child.id, category, "avoid" if mode == "less" else "remove")
    flash("Updated. Recommendations will change.", "success")
    return redirect(url_for("profile.world_3d"))


@bp.route("/world/reset", methods=["POST"])
@subscribed_required
def world_reset():
    rec.reset_profile(g.child.id)
    flash("Interest profile reset. We'll start learning again.", "success")
    return redirect(url_for("profile.world"))


@bp.route("/me/settings", methods=["GET", "POST"])
@subscribed_required
def child_settings():
    """The child's own settings page: pick an avatar and change their own password."""
    if g.auth_role != "child":
        return redirect(url_for("auth.caretaker"))
    child = g.child
    account = Session.query(ChildAccount).filter_by(child_profile_id=child.id).first()
    can_change_password = bool(account and not account.legacy_shared_password)
    if request.method == "POST":
        if g.child_read_only:
            abort(403)
        action = request.form.get("action")
        if action == "avatar":
            avatar = request.form.get("avatar")
            if avatar in AVATARS:
                child.avatar, child.updated_at = avatar, utcnow()
                Session.commit()
                flash("Your avatar is saved.", "success")
            else:
                flash("Please pick one of the avatars.", "error")
        elif action == "password" and can_change_password:
            f = request.form
            if not auth_service.verify_password(account.password_hash, f.get("current", "")):
                flash("Your current password is not right.", "error")
            elif f.get("new") != f.get("confirm"):
                flash("The new passwords do not match.", "error")
            else:
                try:
                    auth_service.set_child_password(g.user, child, f.get("new", ""))
                    flash("Your password was changed.", "success")
                except auth_service.AuthError as exc:
                    flash(str(exc), "error")
        else:
            flash("That change is not available. Ask your caretaker for help.", "error")
        return redirect(url_for("profile.child_settings"))
    return render_template("child_settings.html", child=child, avatars=AVATARS, active="settings",
                           can_change_password=can_change_password, read_only=g.child_read_only)


@bp.route("/updates", methods=["GET", "POST"])
@subscribed_required
def updates():
    if request.method == "POST":
        f = request.form
        today = date.today()
        new_cats = [c for c in f.getlist("new_interests") if c in CATEGORIES]
        avoid_cats = [c for c in f.getlist("avoid") if c in CATEGORIES]
        parts = []
        for c in new_cats:
            rec.caregiver_adjust(g.child.id, c, "boost"); parts.append(f"New interest observed: {CATEGORIES[c]['label']}")
        for c in avoid_cats:
            rec.caregiver_adjust(g.child.id, c, "avoid"); parts.append(f"Seems to avoid: {CATEGORIES[c]['label']}")
        for key, label in (("activities", "Activities"), ("routine", "Routine"), ("communication", "Communication"),
                           ("sensory", "Sensory / content preferences"), ("private", "Private note")):
            val = (f.get(key) or "").strip()[:500]
            if val:
                parts.append(f"{label}: {val}")
        kw = (f.get("avoid_keywords") or "").strip()
        if kw:
            cur = settings_service.caregiver_settings(g.user.id)["avoid_keywords"]
            merged = ", ".join(dict.fromkeys(safety.parse_keywords(cur) + safety.parse_keywords(kw)))
            settings_service.save_caregiver_settings(g.user.id, {"avoid_keywords": merged})
            parts.append("Content filter updated")
        if not parts:
            flash("Nothing to save yet.", "error")
            return redirect(url_for("profile.updates"))
        Session.add(DailyActivity(child_profile_id=g.child.id, activity_type="update", title="Caregiver update",
                                  notes="\n".join(parts), source="caregiver", activity_date=today))
        Session.commit()
        flash("Saved. Caregiver observations are kept separate from the child's own choices.", "success")
        return redirect(url_for("profile.updates"))
    history = (Session.query(DailyActivity).filter_by(child_profile_id=g.child.id, activity_type="update")
               .order_by(DailyActivity.id.desc()).limit(10).all())
    return render_template("updates.html", categories=CATEGORIES, history=history, active="updates")


@bp.route("/settings", methods=["GET"])
@caregiver_required
def settings():
    child = child_of(g.user)
    subs = Session.query(Subscription).filter_by(user_id=g.user.id).order_by(Subscription.id.desc()).all()
    reqs = {r.subscription_id: r for r in Session.query(PaymentVerificationRequest)
            .filter(PaymentVerificationRequest.subscription_id.in_([s.id for s in subs] or [0]))}
    age = child.age_years if child else None
    island_options, island_current = world_service.island_settings(g.user.id)
    return render_template("settings.html", island_options=island_options, island_current=island_current, child=child, subs=subs, reqs=reqs, avatars=AVATARS, active="settings",
                           age_bands=[age_service.BANDS[k] for k in age_service.BAND_ORDER], age_band=age_service.band_for(age),
                           min_age=age_service.MIN_AGE, max_age=age_service.MAX_AGE,
                           state=payment_service.access_state(g.user.id), active_sub=payment_service.active_subscription(g.user.id),
                           plans=settings_service.plans(), admin_contact=settings_service.payment_display())


@bp.route("/settings/account", methods=["GET", "POST"])
@caregiver_required
def account_settings():
    if request.method == "POST":
        f = request.form
        pin_enabled = "caretaker_pin_enabled" in f
        new_pin = (f.get("new_pin") or "").strip()
        current_pin = (f.get("current_pin") or "").strip()

        if g.user.caretaker_pin_enabled and not auth_service.verify_password(g.user.caretaker_pin_hash or "", current_pin):
            flash("Current caretaker PIN is incorrect.", "error")
            return render_template("account_settings.html", active="settings"), 400
        if pin_enabled and (new_pin or not g.user.caretaker_pin_enabled) and not re.fullmatch(r"[0-9]{4,6}", new_pin):
            flash("Caretaker PIN must be 4–6 digits.", "error")
            return render_template("account_settings.html", active="settings"), 400
        if f.get("new_password") or f.get("confirm_password"):
            try:
                auth_service.validate_password(f.get("new_password", ""), f.get("caretaker_username", ""))
                if f.get("child_username", "").strip().lower() in f.get("new_password", "").lower():
                    raise auth_service.AuthError("Password must not contain the child username.")
                if f.get("new_password") != f.get("confirm_password"):
                    raise auth_service.AuthError("New passwords do not match.")
            except auth_service.AuthError as exc:
                flash(str(exc), "error")
                return render_template("account_settings.html", active="settings"), 400

        try:
            auth_service.update_family_credentials(
                g.user, f.get("caretaker_username"), f.get("child_username"), f.get("current_password", ""),
                f.get("new_password", ""), f.get("confirm_password", ""))
        except auth_service.AuthError as exc:
            flash(str(exc), "error")
            return render_template("account_settings.html", active="settings"), 400

        if pin_enabled:
            if new_pin:
                g.user.caretaker_pin_hash = auth_service.hash_password(new_pin)
            g.user.caretaker_pin_enabled = True
        else:
            g.user.caretaker_pin_hash = None
            g.user.caretaker_pin_enabled = False
            session["caretaker_pin_verified"] = True
        if g.user.caretaker_pin_enabled:
            session["caretaker_pin_verified"] = False
        Session.commit()
        flash("Family login settings saved.", "success")
        return redirect(url_for("profile.account_settings"))
    return render_template("account_settings.html", active="settings")


@bp.route("/settings/preferences", methods=["POST"])
@caregiver_required
def save_preferences():
    f = request.form
    try:
        new_age = age_service.parse_age(f.get("age"))        # blank = leave the age as it is
    except age_service.AgeError as e:
        flash(str(e), "error")
        return redirect(url_for("profile.settings"))
    try:
        minutes = max(5, min(int(f.get("screen_time_minutes", 30)), 240))
    except ValueError:
        minutes = 30
    settings_service.save_caregiver_settings(g.user.id, {
        "reduced_motion": "reduced_motion" in f, "large_text": "large_text" in f, "sound_labels": "sound_labels" in f,
        "high_contrast": "high_contrast" in f, "show_real_people": "show_real_people" in f, "shots_enabled": "shots_enabled" in f, "screen_time_minutes": minutes,
        "avoid_keywords": ", ".join(safety.parse_keywords(f.get("avoid_keywords")))[:600]})
    if "island" in f:                                        # island look chosen on the Settings page (same setting as My World's gear menu)
        try:
            world_service.update_settings(g.user.id, {"island": f.get("island", "auto")})
        except world_service.WorldError as e:
            flash(str(e), "error")
    child = child_of(g.user)
    if child:
        child.display_name = (f.get("display_name") or "Friend").strip()[:40] or "Friend"
        child.avatar = f.get("avatar") if f.get("avatar") in AVATARS else child.avatar
        if new_age is not None:
            child.age_years = new_age
        Session.commit()
    flash("Settings saved.", "success")
    return redirect(url_for("profile.settings"))


@bp.route("/settings/password", methods=["POST"])
@caregiver_required
def change_password():
    f = request.form
    if not auth_service.verify_password(g.user.password_hash, f.get("current", "")):
        flash("Current password is incorrect.", "error")
    else:
        try:
            auth_service.validate_password(f.get("new", ""), g.user.username)
            if g.user.child_username and g.user.child_username in f.get("new", "").lower():
                raise auth_service.AuthError("Password must not contain the child username.")
            if f.get("new") != f.get("confirm"):
                raise auth_service.AuthError("New passwords do not match.")
            g.user.password_hash = auth_service.hash_password(f["new"]); Session.commit()
            flash("Password changed.", "success")
        except auth_service.AuthError as exc:
            flash(str(exc), "error")
    return redirect(url_for("profile.settings"))


@bp.route("/settings/export")
@caregiver_required
def export():
    data = json.dumps(account_service.export_user(g.user), indent=2, default=str)
    return Response(data, mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=mymind-data-export.json"})


@bp.route("/settings/delete-request", methods=["POST"])
@caregiver_required
def delete_request():
    if request.form.get("confirm") != "DELETE":
        flash("Type DELETE to confirm the request.", "error")
    else:
        g.user.deletion_requested_at = utcnow(); Session.commit()
        flash("Deletion requested. The administrator will remove your account and all stored data.", "success")
    return redirect(url_for("profile.settings"))


@bp.route("/settings/delete-cancel", methods=["POST"])
@caregiver_required
def delete_cancel():
    g.user.deletion_requested_at = None; Session.commit()
    flash("Deletion request cancelled.", "success")
    return redirect(url_for("profile.settings"))
