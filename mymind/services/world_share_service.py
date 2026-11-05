"""Token-only sharing for the read-only child world preview."""
import hashlib
import re
import secrets
from datetime import timedelta

from database.db import Session
from database.models import ChildProfile, User, WorldShareLink, utcnow

EXPIRIES = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30), "never": None}
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{30,64}$")


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create(child, expiry="7d"):
    if expiry not in EXPIRIES:
        raise ValueError("Choose a valid link expiry.")
    token = secrets.token_urlsafe(32)
    duration = EXPIRIES[expiry]
    link = WorldShareLink(child_profile_id=child.id, token_hash=_hash(token),
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
    owner = (Session.query(User).join(ChildProfile, ChildProfile.caregiver_user_id == User.id)
             .filter(ChildProfile.id == link.child_profile_id).first())
    return bool(owner and owner.account_status == "active")


def note_opened(link):
    link.last_opened_at = utcnow()
    Session.commit()


def revoke(child, link_id):
    link = Session.query(WorldShareLink).filter_by(id=link_id, child_profile_id=child.id).first()
    if not link:
        return False
    if not link.revoked_at:
        link.revoked_at = utcnow()
        Session.commit()
    return True


def links_for(child):
    return (Session.query(WorldShareLink).filter_by(child_profile_id=child.id)
            .order_by(WorldShareLink.created_at.desc()).all())


def status_of(link):
    if link.revoked_at:
        return "revoked"
    if link.expires_at and link.expires_at <= utcnow():
        return "expired"
    return "active"