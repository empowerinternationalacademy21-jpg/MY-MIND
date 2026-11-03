"""/verify: the 18+ caretaker check. See services/sumsub_service.py for the end-to-end data flow."""
import json
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, g, current_app, abort
from database.db import Session
from database.models import User
from services import cache, sumsub_service as sx, verification_service as vs
from services.auth_service import audit
from routes.helpers import login_required, next_step

bp = Blueprint("verification", __name__, url_prefix="/verify")

UNDERAGE = {"error": "underage", "title": "Access denied",
            "message": "Thank you for being honest with us. MyMind accounts are for the adults who look after a child, so the person "
                       "creating the account must be 18 or older. Please ask a parent, guardian or caretaker to set it up. "
                       "We're glad you're here and we hope to see you with them soon."}


def caretaker_only(f):
    """Logged-in caregiver. Deliberately does NOT require verification (this is where verification happens)."""
    from functools import wraps

    @wraps(f)
    @login_required
    def wrapper(*a, **kw):
        if g.user.role != "caregiver" or not vs.required():
            return redirect(url_for(next_step(g.user)))
        return f(*a, **kw)
    return wrapper


def err(code, message, status, title=None):
    return jsonify(error=code, title=title or "We couldn't continue", message=message), status


@bp.route("/")
@caretaker_only
def start():
    if g.user.is_adult_verified:
        return redirect(url_for(next_step(g.user)))
    return render_template("verify.html", mode=vs.mode(), sdk_url=current_app.config["SUMSUB_SDK_URL"], status=g.user.id_verification_status,
                           blocked=vs.blocked(g.user), today=sx.today_utc().isoformat(), min_dob=sx.today_utc().replace(year=sx.today_utc().year - sx.MAX_AGE).isoformat())


@bp.route("/start", methods=["POST"])
@caretaker_only
def begin():
    """Step 2-3 of the flow: validate -> age gate -> create applicant -> access token."""
    user = Session.get(User, g.user.id)
    if user.is_adult_verified:
        return jsonify(state="verified", next=url_for(next_step(user)))
    if vs.blocked(user):
        return err("blocked", "Verification is paused for now. Please try again later or contact the administrator.", 403)
    if cache.rate_limited(f"vstart:{user.id}", 8, 3600) or cache.rate_limited(f"vstart-ip:{request.remote_addr}", 30, 3600):
        return err("rate", "Too many attempts. Please wait a little and try again.", 429)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return err("payload", "Something was missing from the form. Please fill in every field.", 400)
    try:
        name, email = sx.clean_person(data.get("full_name"), data.get("email"))
        dob = sx.parse_dob(data.get("dob"))
    except sx.FormError as exc:
        return err("invalid", str(exc), 400)
    if data.get("consent") is not True:
        return err("consent", "Please tick the box to agree to the identity check.", 400)

    # ---- AGE GATE (before any provider call): exact to the day, in UTC ----
    if not sx.is_adult(dob):
        vs.note_underage_declaration(user)
        return jsonify(UNDERAGE), 403

    if vs.mode() == "demo":                                           # development only; refused at startup in production
        return jsonify(mode="demo")
    try:
        applicant = sx.create_applicant(user.id, name, email, dob)
        token = sx.access_token(user.id)
    except sx.SumsubError as exc:
        return err(exc.kind, str(exc), 504 if exc.kind == "timeout" else 502)
    user.sumsub_applicant_id, user.id_verification_status = applicant, "pending"
    Session.commit()                                                  # only the opaque applicant id is kept; name/email/DOB are dropped here
    return jsonify(mode="sumsub", token=token, ttl=600)


@bp.route("/token", methods=["POST"])
@caretaker_only
def refresh_token():
    """The SDK asks for a new token when its 10-minute token expires."""
    if not g.user.sumsub_applicant_id or g.user.is_adult_verified:
        return err("state", "Please start the verification first.", 400)
    if cache.rate_limited(f"vtoken:{g.user.id}", 20, 3600):
        return err("rate", "Too many attempts. Please wait a little and try again.", 429)
    try:
        return jsonify(token=sx.access_token(g.user.id))
    except sx.SumsubError as exc:
        return err(exc.kind, str(exc), 504 if exc.kind == "timeout" else 502)


@bp.route("/status")
@caretaker_only
def status():
    """Polled by the page after the SDK says 'submitted'. If the webhook hasn't arrived yet we ask Sumsub ourselves (throttled)."""
    user = Session.get(User, g.user.id)
    if user.id_verification_status == "pending" and user.sumsub_applicant_id and not cache.rate_limited(f"vpoll:{user.id}", 1, 4):
        try:
            vs.apply_result(user, sx.interpret(sx.get_applicant(user.sumsub_applicant_id)))
        except sx.SumsubError:
            pass                                                      # transient: the next poll or the webhook will settle it
    state = "verified" if user.is_adult_verified else user.id_verification_status
    return jsonify(state=state, next=url_for(next_step(user)) if user.is_adult_verified else None)


@bp.route("/demo-confirm", methods=["POST"])
@caretaker_only
def demo_confirm():
    if vs.mode() != "demo" or current_app.config["PRODUCTION"]:
        abort(404)
    user = Session.get(User, g.user.id)
    vs.apply_result(user, {"state": "verified", "country": None, "doc_type": "demo"})
    return jsonify(state="verified", next=url_for(next_step(user)))


@bp.route("/webhook", methods=["POST"])
def webhook():
    """Called by Sumsub (no cookies, no CSRF). We (1) check the HMAC signature on the raw bytes, then (2) ignore what the payload
    claims and ask Sumsub for the applicant ourselves, so a forged or replayed webhook can't verify anybody."""
    if vs.mode() != "sumsub":
        abort(404)
    if cache.rate_limited(f"vhook:{request.remote_addr}", 120, 60):
        return ("", 429)
    raw = request.get_data()                                          # the exact bytes Sumsub signed (and the same bytes we parse below)
    if not sx.verify_webhook(raw, request.headers):
        return ("", 401)
    try:
        payload = json.loads(raw)
    except ValueError:
        return ("", 400)
    if not isinstance(payload, dict):
        return ("", 400)
    if payload.get("type") != "applicantReviewed":
        return ("", 200)                                              # other event types aren't needed
    uid, applicant_id = sx.user_id_from_external(payload.get("externalUserId")), payload.get("applicantId")
    user = Session.get(User, uid) if uid else None
    if not user or user.role != "caregiver" or not applicant_id:
        return ("", 200)                                              # unknown user: acknowledge so Sumsub stops retrying
    try:
        applicant = sx.get_applicant(applicant_id)
    except sx.SumsubError:
        return ("", 503)                                              # ask Sumsub to retry later
    if applicant.get("externalUserId") != sx.external_id(user.id):
        return ("", 200)                                              # the applicant isn't this user's: ignore
    user.sumsub_applicant_id = user.sumsub_applicant_id or applicant_id
    vs.apply_result(user, sx.interpret(applicant))
    return ("", 200)
