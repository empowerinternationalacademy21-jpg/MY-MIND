"""Registration, password hashing (Argon2id) and authentication."""
import re
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from sqlalchemy.exc import IntegrityError
from database.db import Session
from database.models import User, AuditLog

_ph = PasswordHasher()   # Argon2id by default
USERNAME_RE = re.compile(r"^[a-z0-9_.]{3,30}$")


class AuthError(Exception):
    pass


def normalize_username(u):
    return (u or "").strip().lower()


def validate_username(u):
    if not USERNAME_RE.match(u):
        raise AuthError("Username must be 3–30 characters: letters, numbers, dots or underscores.")


def validate_password(p, username=""):
    if len(p or "") < 10:
        raise AuthError("Password must be at least 10 characters.")
    if len(p) > 128:
        raise AuthError("Password is too long (max 128 characters).")
    if not (re.search(r"[A-Za-z]", p) and re.search(r"\d", p)):
        raise AuthError("Password must include at least one letter and one number.")
    if username and username in p.lower():
        raise AuthError("Password must not contain your username.")


def hash_password(p):
    return _ph.hash(p)


def verify_password(hash_, p):
    try:
        return _ph.verify(hash_, p)
    except (VerifyMismatchError, InvalidHashError):
        return False


def register_user(username, password, confirm):
    u = normalize_username(username)
    validate_username(u)
    validate_password(password, u)
    if password != confirm:
        raise AuthError("Passwords do not match.")
    user = User(username=u, password_hash=hash_password(password), role="caregiver")
    Session.add(user)
    try:
        Session.commit()          # the UNIQUE constraint is the real guard against duplicates
    except IntegrityError:
        Session.rollback()
        raise AuthError("That username is already taken. Please choose another.")
    return user


_DUMMY = _ph.hash("dummy-password-for-timing")


def authenticate(username, password):
    user = Session.query(User).filter_by(username=normalize_username(username)).first()
    if not user:
        verify_password(_DUMMY, password or "")   # keep timing similar
        return None
    return user if verify_password(user.password_hash, password or "") else None


def create_admin(username, password):
    u = normalize_username(username)
    validate_username(u)
    validate_password(password, u)
    existing = Session.query(User).filter_by(username=u).first()
    if existing:
        existing.role, existing.password_hash = "admin", hash_password(password)
        Session.commit()
        return f"Admin '{u}' updated."
    Session.add(User(username=u, password_hash=hash_password(password), role="admin"))
    Session.commit()
    return f"Admin '{u}' created."


def audit(admin_id, action, target_type=None, target_id=None, detail=None):
    Session.add(AuditLog(administrator_id=admin_id, action=action, target_type=target_type,
                         target_id=str(target_id) if target_id is not None else None, detail=detail))
