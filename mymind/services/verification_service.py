"""Caretaker 18+ verification: mode, server-side gate, and recording the OUTCOME (never personal data)."""
from datetime import timedelta
from flask import current_app
from database.db import Session
from database.models import User, utcnow
from services import auth_service, payment_service

MAX_UNDERAGE_ATTEMPTS = 3
BLOCK_HOURS = 24


def mode():
    """off | demo | sumsub. Auto: sumsub when keys are configured, otherwise off (development, existing tests)."""
    c = current_app.config
    m = (c.get("ID_VERIFICATION") or "").lower()
    if m in ("off", "demo", "sumsub"):
        return m
    return "sumsub" if (c.get("SUMSUB_APP_TOKEN") and c.get("SUMSUB_SECRET_KEY")) else "off"


def check_startup(app):
    """Demo mode would let anyone self-certify, so it can never run in production."""
    with app.app_context():
        if app.config["PRODUCTION"] and mode() == "demo":
            raise RuntimeError("ID_VERIFICATION=demo is for development only. Configure Sumsub or unset it.")


def required():
    return mode() != "off"


def needs_verification(user):
    return bool(user and user.role == "caregiver" and required() and not user.is_adult_verified)


def blocked(user):
    return bool(user.verify_blocked_until and user.verify_blocked_until > utcnow())


def note_underage_declaration(user):
    """Self-declared under 18: count it, and pause further attempts after a few (stops 'try another birthday' loops)."""
    user.verify_underage_attempts = (user.verify_underage_attempts or 0) + 1
    if user.verify_underage_attempts >= MAX_UNDERAGE_ATTEMPTS:
        user.verify_blocked_until = utcnow() + timedelta(hours=BLOCK_HOURS)
        user.id_verification_status = "blocked"
    auth_service.audit(None, "id_age_gate_declined", "user", user.id, "under18")      # outcome only: no date of birth
    Session.commit()


def apply_result(user, result):
    """Record Sumsub's decision. `result` comes from sumsub_service.interpret(). Idempotent."""
    state = result["state"]
    if state == "verified":
        if user.is_adult_verified:
            return state
        user.is_adult_verified, user.id_verification_status = True, "verified"
        user.verified_at, user.verified_country, user.verified_document_type = utcnow(), (result.get("country") or "")[:3] or None, (result.get("doc_type") or "")[:30] or None
        user.verify_blocked_until, user.verify_underage_attempts = None, 0
        auth_service.audit(None, "id_verified", "user", user.id, f"country={user.verified_country or '-'}")
        Session.commit()
        payment_service.start_trial(user)                  # the free trial starts when access opens, not at sign-up
        return state
    mapping = {"underage": "blocked", "rejected": "rejected", "retry": "retry", "manual": "pending", "pending": "pending"}
    user.id_verification_status = mapping.get(state, "pending")
    if state == "underage":
        user.is_adult_verified = False
        user.verify_blocked_until = utcnow() + timedelta(hours=BLOCK_HOURS * 30)
    auth_service.audit(None, f"id_{state}", "user", user.id, f"country={(result.get('country') or '-')}")
    Session.commit()
    return state
