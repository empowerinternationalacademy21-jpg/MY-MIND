from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, current_app
from database.db import Session
from services import auth_service, cache, payment_service, recovery_service, settings_service, verification_service
from routes.helpers import next_step, login_required, caregiver_required, child_of, has_questionnaire

bp = Blueprint("auth", __name__)


@bp.route("/")
def index():
    if g.user:
        return redirect(url_for(next_step(g.user, g.auth_role)))
    return render_template("landing.html", plans=settings_service.plans(), trial_days=payment_service.trial_days())


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for(next_step(g.user)))
    if request.method == "POST":
        if cache.rate_limited(f"reg:{request.remote_addr}", 10, 3600):
            flash("Too many sign-up attempts. Please try again later.", "error")
            return render_template("register.html"), 429
        try:
            user = auth_service.register_user(request.form.get("username"), request.form.get("password", ""),
                                              request.form.get("confirm", ""))
        except auth_service.AuthError as exc:
            flash(str(exc), "error")
            return render_template("register.html", username=request.form.get("username", "")), 400
        session.clear()
        session["uid"] = user.id
        session["login_role"] = "caregiver"
        session.permanent = True
        if verification_service.required():
            flash("Welcome to MyMind! One more step: please confirm you are 18 or older.", "success")
            return redirect(url_for(next_step(user)))
        trial = payment_service.start_trial(user)
        if trial:
            flash(f"Welcome to MyMind! Your free trial is active for {trial.duration_days} days.", "success")
        else:
            flash("Welcome to MyMind! Please choose a plan to continue.", "success")
        return redirect(url_for(next_step(user)))
    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        if g.auth_role == "child":
            return redirect(url_for("profile.world"))
        if g.user.role == "caregiver":
            return redirect(url_for("auth.caretaker_pin" if g.user.caretaker_pin_enabled and not session.get("caretaker_pin_verified") else "auth.caretaker"))
        return redirect(url_for(next_step(g.user, g.auth_role)))
    if request.method == "POST":
        c = current_app.config
        uname = auth_service.normalize_username(request.form.get("username"))
        key = f"login:{request.remote_addr}:{uname}"
        if cache.rate_peek(key, c["LOGIN_MAX_ATTEMPTS"], c["LOGIN_WINDOW_SECONDS"]):
            flash("Too many attempts. Please wait a few minutes and try again.", "error")
            return render_template("login.html"), 429
        user, login_role = auth_service.authenticate_identity(uname, request.form.get("password", ""))
        if not user:
            cache.rate_limited(key, c["LOGIN_MAX_ATTEMPTS"], c["LOGIN_WINDOW_SECONDS"])   # count failures only
            flash("Incorrect username or password.", "error")
            return render_template("login.html", username=uname), 401
        if user.account_status != "active":
            flash("This account is suspended. Please contact the administrator.", "error")
            return render_template("login.html"), 403
        cache.rate_reset(key)
        session.clear()
        session["uid"] = user.id
        session["login_role"] = login_role
        session["caretaker_pin_verified"] = login_role != "caregiver" or not user.caretaker_pin_enabled
        session.permanent = request.form.get("remember") == "on"   # "Remember me": persistent cookie only if ticked
        if login_role == "child":
            return redirect(url_for("profile.world"))
        if login_role == "caregiver":
            if user.caretaker_pin_enabled:
                return redirect(url_for("auth.caretaker_pin"))
            return redirect(url_for("auth.caretaker"))
        return redirect(url_for(next_step(user, login_role)))
    return render_template("login.html")


@bp.route("/caretaker")
@caregiver_required
def caretaker():
    child = child_of(g.user)
    state = payment_service.access_state(g.user.id)
    setup = "verification" if verification_service.needs_verification(g.user) else (
        "subscription" if state != "active" else "onboarding" if not has_questionnaire(child) else "ready")
    return render_template("caretaker.html", child=child, setup=setup)


@bp.route("/caretaker-pin", methods=["GET", "POST"])
@login_required
def caretaker_pin():
    if g.user.role != "caregiver" or g.auth_role != "caregiver":
        return render_template("error.html", code=403, msg="You don't have access to this page."), 403
    if not g.user.caretaker_pin_enabled:
        session["caretaker_pin_verified"] = True
        return redirect(url_for("auth.caretaker"))
    key = f"caretaker-pin:{g.user.id}:{request.remote_addr}"
    if request.method == "POST":
        if cache.rate_peek(key, 5, 300):
            return render_template("caretaker_pin.html", locked=True), 429
        if auth_service.verify_password(g.user.caretaker_pin_hash or "", request.form.get("pin", "")):
            cache.rate_reset(key)
            session["caretaker_pin_verified"] = True
            return redirect(url_for("auth.caretaker"))
        cache.rate_limited(key, 5, 300)
        return render_template("caretaker_pin.html", error="That PIN isn't right."), 401
    return render_template("caretaker_pin.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.index"))


def _admin_contact():
    return settings_service.payment_display()


@bp.route("/recover", methods=["GET", "POST"])
def recover():
    """Step 1: username."""
    if g.user:
        return redirect(url_for(next_step(g.user)))
    session.pop("rec", None)
    if request.method == "POST":
        uname = auth_service.normalize_username(request.form.get("username"))
        if not uname:
            flash("Please enter your username.", "error")
            return render_template("recover.html"), 400
        if recovery_service.register_start(request.remote_addr) or recovery_service.is_locked(uname, request.remote_addr):
            return render_template("recover_failed.html", locked=True, contact=_admin_contact()), 429
        user = recovery_service.eligible_user(uname)
        # unknown usernames get the SAME questions and always fail, so accounts can't be enumerated
        session["rec"] = {"uid": user.id if user else 0, "name": uname}
        return render_template("recover_questions.html", questions=recovery_service.QUESTIONS)
    return render_template("recover.html")


@bp.route("/recover/verify", methods=["POST"])
def recover_verify():
    """Step 2: score the answers (>= 80 % passes)."""
    rec = session.get("rec")
    if not rec or g.user:
        return redirect(url_for("auth.recover"))
    name, uid = rec["name"], rec["uid"]
    if recovery_service.is_locked(name, request.remote_addr):
        session.pop("rec", None)
        return render_template("recover_failed.html", locked=True, contact=_admin_contact()), 429
    ok = bool(uid) and recovery_service.score(uid, request.form) >= recovery_service.PASS_THRESHOLD
    session.pop("rec", None)
    if not ok:
        recovery_service.register_failure(name)
        return render_template("recover_failed.html", locked=recovery_service.is_locked(name, request.remote_addr),
                               contact=_admin_contact()), 403
    recovery_service.clear_failures(name)
    import time
    session["rec_ok"] = {"uid": uid, "ts": time.time()}
    return redirect(url_for("auth.recover_reset"))


@bp.route("/recover/reset", methods=["GET", "POST"])
def recover_reset():
    """Step 3: choose a new password (needs a fresh verification)."""
    tok = session.get("rec_ok")
    if not tok or not recovery_service.token_valid(tok.get("ts")):
        session.pop("rec_ok", None)
        flash("Please verify your answers again.", "error")
        return redirect(url_for("auth.recover"))
    from database.models import User
    user = Session.get(User, tok["uid"])
    if request.method == "POST":
        try:
            auth_service.validate_password(request.form.get("password", ""), user.username)
            if request.form.get("password") != request.form.get("confirm"):
                raise auth_service.AuthError("Passwords do not match.")
        except auth_service.AuthError as exc:
            flash(str(exc), "error")
            return render_template("recover_reset.html"), 400
        user.password_hash = auth_service.hash_password(request.form["password"])
        auth_service.audit(None, "password_reset_self", "user", user.id, "verified via questionnaire")
        Session.commit()
        session.clear()                      # single use
        flash("Password updated. Please log in with your new password.", "success")
        return redirect(url_for("auth.login"))
    return render_template("recover_reset.html")