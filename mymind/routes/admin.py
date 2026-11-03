import json
import re
import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from database.db import Session
from database.models import User, Subscription, PaymentVerificationRequest, AuditLog, ChildProfile
from services import payment_service, settings_service, auth_service, account_service, safety
from services.auth_service import audit
from routes.helpers import admin_required

bp = Blueprint("admin", __name__, url_prefix="/admin")
PHONE_RE = re.compile(r"^\+?[0-9 ()\-]{7,20}$")


@bp.route("/")
@admin_required
def dashboard():
    pending = (Session.query(PaymentVerificationRequest).filter_by(status="pending_verification")
               .order_by(PaymentVerificationRequest.created_at).limit(5).all())
    return render_template("admin/dashboard.html", stats=payment_service.stats(), pending=pending, nav="dashboard")


@bp.route("/payments")
@admin_required
def payments():
    rows = (Session.query(PaymentVerificationRequest, Subscription, User)
            .join(Subscription, Subscription.id == PaymentVerificationRequest.subscription_id)
            .join(User, User.id == Subscription.user_id).order_by(PaymentVerificationRequest.created_at.desc()).limit(200).all())
    return render_template("admin/payments.html", pending=[r for r in rows if r[0].status == "pending_verification"],
                           history=[r for r in rows if r[0].status != "pending_verification"], nav="payments")


@bp.route("/payments/<int:req_id>/<action>", methods=["POST"])
@admin_required
def decide(req_id, action):
    if action not in ("approve", "reject"):
        abort(404)
    note = (request.form.get("note") or "").strip()
    try:
        (payment_service.approve if action == "approve" else payment_service.reject)(g.user, req_id, note)
        flash(f"Payment {action}d.", "success")
    except payment_service.PaymentError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.payments"))


@bp.route("/users")
@admin_required
def users():
    q = (request.args.get("q") or "").strip().lower()[:40]
    query = Session.query(User).filter(User.role == "caregiver")
    if q:
        query = query.filter(User.username.contains(q))
    rows = []
    for u in query.order_by(User.created_at.desc()).limit(100):
        rows.append({"user": u, "state": payment_service.access_state(u.id),
                     "sub": payment_service.active_subscription(u.id)})
    return render_template("admin/users.html", rows=rows, q=q, nav="users")


@bp.route("/users/<int:uid>/status", methods=["POST"])
@admin_required
def user_status(uid):
    u = Session.get(User, uid)
    if not u or u.role != "caregiver":
        abort(404)
    u.account_status = "suspended" if u.account_status == "active" else "active"
    audit(g.user.id, f"account_{u.account_status}", "user", u.id)
    Session.commit()
    flash(f"Account {u.username} is now {u.account_status}.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:uid>/reset-password", methods=["POST"])
@admin_required
def reset_password(uid):
    u = Session.get(User, uid)
    if not u or u.role != "caregiver":
        abort(404)
    temp = secrets.token_urlsafe(9) + "7a"
    u.password_hash = auth_service.hash_password(temp)
    audit(g.user.id, "password_reset", "user", u.id)
    Session.commit()
    flash(f"Temporary password for {u.username}: {temp}  (shown once — share it privately and ask them to change it in Settings).", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:uid>/delete", methods=["POST"])
@admin_required
def delete_user(uid):
    u = Session.get(User, uid)
    if not u or u.role != "caregiver" or not u.deletion_requested_at:
        flash("Only accounts that requested deletion can be deleted.", "error")
        return redirect(url_for("admin.users"))
    name = u.username
    audit(g.user.id, "account_deleted", "user", uid, name)
    Session.commit()
    account_service.delete_user(uid)
    flash(f"Account {name} and all its data were deleted.", "success")
    return redirect(url_for("admin.users"))


def _clean(key, val, n=200):
    val = (val or "").strip()[:n]
    if key in ("whatsapp_number", "contact_phone") and val and not PHONE_RE.match(val):
        raise ValueError("Phone numbers may only contain digits, spaces, +, - and parentheses.")
    return val


@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        f = request.form
        try:
            for key in ("whatsapp_number", "contact_phone", "bank_name", "bank_account_name", "bank_account_number"):
                settings_service.set_value(key, _clean(key, f.get(key)))
            settings_service.set_value("payment_instructions", _clean("x", f.get("payment_instructions"), 800))
            settings_service.set_value("brand_tagline", _clean("x", f.get("brand_tagline"), 80) or "Your thoughts. Your world.")
            plans = {}
            for code in ("weekly", "monthly", "yearly"):
                price, days = float(f.get(f"{code}_price", "")), int(f.get(f"{code}_days", ""))
                if not (0 < price <= 100000 and 1 <= days <= 3660):
                    raise ValueError("Plan prices and durations are out of range.")
                plans[code] = {"name": code.title(), "price": price, "days": days}
            settings_service.set_value("plans_json", json.dumps(plans))
            settings_service.set_value("blocked_keywords", ", ".join(safety.parse_keywords(f.get("blocked_keywords"))))
            td = int(f.get("trial_days", "30"))
            if not 0 <= td <= 365:
                raise ValueError("Plan trial length must be 0–365 days.")
            settings_service.set_value("trial_days", str(td))
            settings_service.set_value("shots_enabled", "1" if "shots_enabled" in f else "0")
        except ValueError as exc:
            Session.rollback()
            flash(str(exc) if "Phone" in str(exc) or "Plan" in str(exc) else "Please check the plan prices and durations (numbers only).", "error")
            return redirect(url_for("admin.settings"))
        audit(g.user.id, "settings_updated", "admin_settings", "-")     # values themselves are never logged
        Session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html", s=settings_service.get_all(), plans=settings_service.plans(),
                           default_blocklist=safety.DEFAULT_BLOCKLIST, nav="settings")


@bp.route("/audit")
@admin_required
def audit_log():
    rows = Session.query(AuditLog).order_by(AuditLog.id.desc()).limit(200).all()
    return render_template("admin/audit.html", rows=rows, nav="audit")
