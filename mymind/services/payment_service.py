"""Subscriptions and the manual payment-approval workflow. Access decisions happen on the backend."""
from datetime import timedelta, date
from sqlalchemy import update, func
from sqlalchemy.exc import IntegrityError
from database.db import Session, transaction
from database.models import Subscription, PaymentVerificationRequest, User, utcnow
from services import settings_service
from services.auth_service import audit


class PaymentError(Exception):
    pass


def expire_due(user_id=None):
    q = Session.query(Subscription).filter(Subscription.status == "active", Subscription.expires_at <= utcnow())
    if user_id:
        q = q.filter(Subscription.user_id == user_id)
    for s in q.all():
        s.status = "expired"
    Session.commit()


def active_subscription(user_id):
    expire_due(user_id)
    now = utcnow()
    return (Session.query(Subscription).filter(Subscription.user_id == user_id, Subscription.status == "active",
                                              Subscription.expires_at > now)
            .order_by(Subscription.expires_at.desc()).first())


def access_state(user_id):
    """active | pending_verification | pending_payment | rejected | expired | none"""
    if active_subscription(user_id):
        return "active"
    subs = Session.query(Subscription).filter_by(user_id=user_id).order_by(Subscription.id.desc()).all()
    for wanted in ("pending_verification", "pending_payment"):
        if any(s.status == wanted for s in subs):
            return wanted
    return subs[0].status if subs else "none"


def trial_days():
    try:
        return max(0, min(int(settings_service.get("trial_days") or 0), 365))
    except ValueError:
        return 0


def start_trial(user):
    """Free trial: an already-active, zero-amount subscription created once, at registration."""
    days = trial_days()
    if days <= 0:
        return None
    if Session.query(Subscription).filter_by(user_id=user.id, plan_code="trial").first():
        return None                       # one trial per account
    now = utcnow()
    sub = Subscription(user_id=user.id, plan_code="trial", amount=0.0, currency="USD", duration_days=days,
                       status="active", starts_at=now, expires_at=now + timedelta(days=days))
    Session.add(sub)
    Session.commit()
    return sub


def select_plan(user, plan_code):
    plans = settings_service.plans()
    if plan_code not in plans:
        raise PaymentError("Please choose a valid plan.")
    # reuse an unpaid selection instead of stacking duplicates
    pending = Session.query(Subscription).filter_by(user_id=user.id, status="pending_payment").first()
    p = plans[plan_code]
    if pending:
        pending.plan_code, pending.amount, pending.duration_days = plan_code, float(p["price"]), int(p["days"])
        sub = pending
    else:
        sub = Subscription(user_id=user.id, plan_code=plan_code, amount=float(p["price"]), currency="USD",
                           duration_days=int(p["days"]), status="pending_payment")
        Session.add(sub)
    Session.commit()
    return sub


def submit_verification(user, sub_id, reference, pay_date, note):
    sub = Session.get(Subscription, sub_id)
    if not sub or sub.user_id != user.id:
        raise PaymentError("Subscription not found.")
    if sub.status != "pending_payment":
        raise PaymentError("This subscription is not awaiting payment.")
    ref = (reference or "").strip().upper()
    if not 4 <= len(ref) <= 60 or not ref.replace("-", "").replace("_", "").replace("/", "").isalnum():
        raise PaymentError("Enter the payment reference or transaction ID (4–60 letters/numbers).")
    if not isinstance(pay_date, date) or pay_date > date.today() + timedelta(days=1) or pay_date < date.today() - timedelta(days=60):
        raise PaymentError("Enter a valid payment date (within the last 60 days).")
    req = PaymentVerificationRequest(subscription_id=sub.id, payment_reference=ref, payment_date=pay_date,
                                     caregiver_note=(note or "")[:500], status="pending_verification")
    sub.status = "pending_verification"
    Session.add(req)
    try:
        Session.commit()
    except IntegrityError:
        Session.rollback()
        raise PaymentError("That payment reference has already been submitted.")
    return req


def approve(admin, request_id, note=""):
    """Atomic approval: a conditional UPDATE guarantees only ONE approval can ever succeed."""
    with transaction() as s:
        res = s.execute(update(PaymentVerificationRequest)
                        .where(PaymentVerificationRequest.id == request_id,
                               PaymentVerificationRequest.status == "pending_verification")
                        .values(status="approved", administrator_note=note[:500], reviewed_by=admin.id, reviewed_at=utcnow()))
        if res.rowcount != 1:
            raise PaymentError("This request was already decided (or does not exist).")
        req = s.get(PaymentVerificationRequest, request_id)
        sub = s.get(Subscription, req.subscription_id)
        if sub.status == "active":
            raise PaymentError("Subscription already active.")
        now = utcnow()
        latest = (s.query(func.max(Subscription.expires_at))
                  .filter(Subscription.user_id == sub.user_id, Subscription.status == "active").scalar())
        start = max(now, latest) if latest else now      # renewals stack after the current period
        sub.status, sub.starts_at, sub.expires_at = "active", start, start + timedelta(days=sub.duration_days)
        audit(admin.id, "payment_approved", "payment_request", request_id, note[:200])
    return sub


def reject(admin, request_id, note=""):
    with transaction() as s:
        res = s.execute(update(PaymentVerificationRequest)
                        .where(PaymentVerificationRequest.id == request_id,
                               PaymentVerificationRequest.status == "pending_verification")
                        .values(status="rejected", administrator_note=note[:500], reviewed_by=admin.id, reviewed_at=utcnow()))
        if res.rowcount != 1:
            raise PaymentError("This request was already decided (or does not exist).")
        req = s.get(PaymentVerificationRequest, request_id)
        s.get(Subscription, req.subscription_id).status = "rejected"
        audit(admin.id, "payment_rejected", "payment_request", request_id, note[:200])


def stats():
    q = Session.query
    return {
        "caregivers": q(User).filter_by(role="caregiver").count(),
        "children": q(__import__("database.models", fromlist=["ChildProfile"]).ChildProfile).count(),
        "active": q(Subscription).filter(Subscription.status == "active", Subscription.expires_at > utcnow()).count(),
        "pending": q(PaymentVerificationRequest).filter_by(status="pending_verification").count(),
        "approved": q(PaymentVerificationRequest).filter_by(status="approved").count(),
        "rejected": q(PaymentVerificationRequest).filter_by(status="rejected").count(),
        "expired": q(Subscription).filter(Subscription.status == "expired").count(),
    }
