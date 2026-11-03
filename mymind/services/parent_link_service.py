"""Parent links: a private, read-only family view of one child's world.

Security model (all enforced server-side):
* The URL token is 256 random bits and is NEVER stored: only its SHA-256. A database leak cannot reveal a usable link.
* A viewer needs the token AND a per-link view password (Argon2id) chosen by the caregiver. It is not the account password.
* Five wrong passwords lock that link for 15 minutes (counted per link, so rotating IPs does not help); per-IP limits sit on top.
* Unknown / revoked / expired links all look identical (one generic "not available" page): nothing to enumerate.
* Revoking or expiry takes effect on the very next request; a viewer's session only proves the password was entered, never access.
* The view shows choices only. It never shows caregiver notes, answers, settings, payments or any account detail.
"""
import hashlib
import re
import secrets
from datetime import timedelta
from database.db import Session
from database.models import ChildProfile, ContentItem, Favorite, ParentLink, User, utcnow
from services import auth_service
from services import recommendation_service as rec

MAX_ACTIVE_LINKS = 5
MAX_FAILED = 5
LOCK_MINUTES = 15
VIEW_SESSION_SECONDS = 2 * 60 * 60
DURATIONS = {"7": 7, "30": 30, "90": 90, "never": None}
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{30,64}$")


class LinkError(Exception):
    pass


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_active(link):
    if link is None or link.revoked_at is not None:
        return False
    if link.expires_at is not None and link.expires_at <= utcnow():
        return False
    owner = Session.query(User).join(ChildProfile, ChildProfile.caregiver_user_id == User.id).filter(ChildProfile.id == link.child_profile_id).first()
    return bool(owner and owner.account_status == "active")


def status_of(link):
    if link.revoked_at is not None:
        return "revoked"
    if link.expires_at is not None and link.expires_at <= utcnow():
        return "expired"
    return "active"


def create(child, label, password, duration_key):
    label = (label or "").strip()[:40]
    password = password or ""
    if duration_key not in DURATIONS:
        raise LinkError("Please choose how long the link should work.")
    if len(password) < 8:
        raise LinkError("The view password must be at least 8 characters.")
    if len(password) > 128:
        raise LinkError("That view password is too long.")
    live = [l for l in Session.query(ParentLink).filter_by(child_profile_id=child.id).all() if status_of(l) == "active"]
    if len(live) >= MAX_ACTIVE_LINKS:
        raise LinkError(f"You can have up to {MAX_ACTIVE_LINKS} active links. Revoke one first.")
    token = secrets.token_urlsafe(32)
    days = DURATIONS[duration_key]
    link = ParentLink(child_profile_id=child.id, token_hash=_hash(token), password_hash=auth_service.hash_password(password),
                      label=label, expires_at=(utcnow() + timedelta(days=days)) if days else None)
    Session.add(link)
    Session.flush()
    auth_service.audit(None, "parent_link_created", "parent_link", link.id, f"days={days or 'until revoked'}")   # never the token
    Session.commit()
    return link, token


def find(token):
    """Link for a URL token, or None. Active-ness is checked separately so every failure looks the same."""
    if not token or not _TOKEN_RE.match(token):
        return None
    return Session.query(ParentLink).filter_by(token_hash=_hash(token)).first()


def locked(link):
    return bool(link.locked_until and link.locked_until > utcnow())


def try_password(link, password):
    """-> 'ok' | 'bad' | 'locked'. Counts failures per link and locks after MAX_FAILED."""
    if locked(link):
        return "locked"
    if auth_service.verify_password(link.password_hash, password or ""):
        link.failed_attempts, link.locked_until = 0, None
        Session.commit()
        return "ok"
    link.failed_attempts = (link.failed_attempts or 0) + 1
    if link.failed_attempts >= MAX_FAILED:
        link.failed_attempts, link.locked_until = 0, utcnow() + timedelta(minutes=LOCK_MINUTES)
        auth_service.audit(None, "parent_link_locked", "parent_link", link.id, f"{LOCK_MINUTES} min")
        Session.commit()
        return "locked"
    Session.commit()
    return "bad"


def note_view(link):
    link.view_count = (link.view_count or 0) + 1
    link.last_viewed_at = utcnow()
    Session.commit()


def revoke(child, link_id):
    link = Session.query(ParentLink).filter_by(id=link_id, child_profile_id=child.id).first()     # ownership: other accounts' ids are 404
    if not link:
        return None
    if link.revoked_at is None:
        link.revoked_at = utcnow()
        auth_service.audit(None, "parent_link_revoked", "parent_link", link.id, None)
        Session.commit()
    return link


def links_for(child):
    return Session.query(ParentLink).filter_by(child_profile_id=child.id).order_by(ParentLink.id.desc()).all()


def world_for(child):
    """What a family member may see: the child's choices, in plain words. Observations, not conclusions."""
    interests = rec.get_interests(child.id)
    enjoy = [i for i in interests if i["score"] >= 3 and i["evidence"] >= 3]
    exploring = [i for i in interests if i["score"] > 0.5 and i not in enjoy]
    favs = (Session.query(ContentItem).join(Favorite, Favorite.content_item_id == ContentItem.id)
            .filter(Favorite.child_profile_id == child.id).order_by(Favorite.id.desc()).limit(30).all())
    return {"enjoy": enjoy[:8], "exploring": exploring[:8],
            "pictures": [f for f in favs if f.content_type == "picture"][:8],
            "videos": [f for f in favs if f.content_type in ("video", "short")][:6],
            "songs": [f for f in favs if f.content_type == "song"][:6]}
