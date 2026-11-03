from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from database.db import Session
from database.models import Subscription, PaymentVerificationRequest
from services import payment_service, settings_service
from routes.helpers import caregiver_required, next_step

bp = Blueprint("subscriptions", __name__, url_prefix="/subscription")


def _own_sub(sub_id):
    sub = Session.get(Subscription, sub_id)
    if not sub or sub.user_id != g.user.id:
        abort(404)                      # ownership check: never reveal other users' records
    return sub


@bp.route("/")
@caregiver_required
def status():
    state = payment_service.access_state(g.user.id)
    active = payment_service.active_subscription(g.user.id)
    pending = Session.query(Subscription).filter(Subscription.user_id == g.user.id,
                                                 Subscription.status.in_(["pending_payment", "pending_verification"])
                                                 ).order_by(Subscription.id.desc()).first()
    return render_template("subscription.html", state=state, active=active, pending=pending,
                           plans=settings_service.plans())


@bp.route("/select", methods=["POST"])
@caregiver_required
def select():
    try:
        sub = payment_service.select_plan(g.user, request.form.get("plan", ""))
    except payment_service.PaymentError as exc:
        flash(str(exc), "error")
        return redirect(url_for("subscriptions.status"))
    return redirect(url_for("subscriptions.payment", sub_id=sub.id))


@bp.route("/payment/<int:sub_id>")
@caregiver_required
def payment(sub_id):
    sub = _own_sub(sub_id)
    if sub.status not in ("pending_payment", "pending_verification"):
        return redirect(url_for("subscriptions.status"))
    return render_template("payment_instructions.html", sub=sub, pay=settings_service.payment_display(),
                           plan=settings_service.plans().get(sub.plan_code, {"name": sub.plan_code}),
                           reference=f"MYMIND-{g.user.username.upper()}-{sub.id}")


@bp.route("/verify/<int:sub_id>", methods=["GET", "POST"])
@caregiver_required
def verify(sub_id):
    sub = _own_sub(sub_id)
    if request.method == "POST":
        try:
            pay_date = datetime.strptime(request.form.get("payment_date", ""), "%Y-%m-%d").date()
        except ValueError:
            flash("Please enter a valid payment date.", "error")
            return render_template("payment_verification.html", sub=sub), 400
        try:
            payment_service.submit_verification(g.user, sub_id, request.form.get("payment_reference"), pay_date,
                                                request.form.get("note"))
        except payment_service.PaymentError as exc:
            flash(str(exc), "error")
            return render_template("payment_verification.html", sub=sub), 400
        flash("Your payment verification request has been submitted. Your account will be activated after the "
              "administrator confirms your payment.", "success")
        return redirect(url_for("subscriptions.status"))
    if sub.status != "pending_payment":
        return redirect(url_for("subscriptions.status"))
    return render_template("payment_verification.html", sub=sub)
