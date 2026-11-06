"""Token-only sharing for the read-only child world preview."""
import hashlib
import re
import secrets
from datetime import timedelta

from database.db import Session
from database.models import ChildProfile, User, WorldShareLink, utcnow
from services import child_scope

EXPIRIES = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30), "never": None}
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{30,64}$")


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create(child, expiry="7d"):
    if expiry not in EXPIRIES:
        raise ValueError("Choose a valid link expiry.")
    token = secrets.token_urlsafe(32)
    duration = EXPIRIES[expiry]
    caregiver_id = child_scope.primary_caregiver_id(child.id)
    if not caregiver_id:
        raise ValueError("This child does not have an active caregiver link.")
    link = WorldShareLink(child_profile_id=child.id, caregiver_id=caregiver_id, token_hash=_hash(token),
                          expires_at=utcnow() + duration if duration else None)
    Session.add(link)
    Session.commit()
    return link, token


def find(token):
    if not token or not _TOKEN_RE.fullmatch(token):
        return None
    return Session.query(WorldShareLink).filter_by(token_hash=_hash(token)).first()


def is_active(link):
    if not link or link.revoked_at or (link.expires_at and link.expires_at <= utcnow()):
        return False
    owner = Session.get(User, link.caregiver_id)
    if not child_scope.can_access(link.caregiver_id, link.child_profile_id):
        return False
    return bool(owner and owner.account_status == "active")


def note_opened(link):
    link.last_opened_at = utcnow()
    Session.commit()


def revoke(child, link_id, caregiver_id=None):
    caregiver_id = caregiver_id or child_scope.primary_caregiver_id(child.id)
    link = Session.query(WorldShareLink).filter_by(id=link_id, child_profile_id=child.id,
                                                   caregiver_id=caregiver_id).first()
    if not link:
        return False
    if not link.revoked_at:
        link.revoked_at = utcnow()
        Session.commit()
    return True


def links_for(child):
    caregiver_id = child_scope.primary_caregiver_id(child.id)
    return (Session.query(WorldShareLink).filter_by(child_profile_id=child.id, caregiver_id=caregiver_id)
            .order_by(WorldShareLink.created_at.desc()).all())


def status_of(link):
    if link.revoked_at:
        return "revoked"
    if link.expires_at and link.expires_at <= utcnow():
        return "expired"
    return "active"