"""Registration, password hashing (Argon2id) and authentication."""
import re
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from sqlalchemy.exc import IntegrityError
from database.db import Session
from database.models import User, AuditLog, ChildProfile

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
    child_username = _available_child_username(u)
    user = User(username=u, child_username=child_username, password_hash=hash_password(password), role="caregiver")
    Session.add(user)
    try:
        Session.commit()          # the UNIQUE constraint is the real guard against duplicates
    except IntegrityError:
        Session.rollback()
        raise AuthError("That username is already taken. Please choose another.")
    return user


def _available_child_username(caretaker_username):
    stem = caretaker_username[:23]
    candidate, suffix = f"{stem}.child", 2
    while (Session.query(User).filter((User.username == candidate) | (User.child_username == candidate)).first()
           or Session.query(ChildProfile).filter_by(child_username=candidate).first()):
        tail = f".{suffix}"
        candidate = f"{stem[:30 - len(tail)]}{tail}"
        suffix += 1
    return candidate


def new_child_username(user):
    return _available_child_username(user.username)


_DUMMY = _ph.hash("dummy-password-for-timing")


def authenticate(username, password):
    user = Session.query(User).filter_by(username=normalize_username(username)).first()
    if not user:
        verify_password(_DUMMY, password or "")   # keep timing similar
        return None
    return user if verify_password(user.password_hash, password or "") else None


def authenticate_identity(username, password):
    """Resolve either family username to its owner and authenticated session role."""
    username = normalize_username(username)
    user = Session.query(User).filter_by(username=username).first()
    role = user.role if user else "caregiver"
    child = None
    if user is None:
        child = Session.query(ChildProfile).filter_by(child_username=username, archived_at=None).first()
        if child:
            user = Session.get(User, child.caregiver_user_id)
        role = "child"
    if user is None:
        verify_password(_DUMMY, password or "")
        return None, None, None
    if not verify_password(user.password_hash, password or ""):
        return None, None, None
    if role == "child" and not child:
        child = (Session.query(ChildProfile).filter_by(caregiver_user_id=user.id, archived_at=None)
                 .order_by(ChildProfile.created_at.asc(), ChildProfile.id.asc()).first())
    return user, role, child.id if child else None


def username_available(username, user_id=None, exclude_child_id=None):
    username = normalize_username(username)
    query = Session.query(User).filter((User.username == username) | (User.child_username == username))
    if user_id is not None:
        query = query.filter(User.id != user_id)
    children = Session.query(ChildProfile).filter_by(child_username=username)
    if exclude_child_id is not None:
        children = children.filter(ChildProfile.id != exclude_child_id)
    return query.first() is None and children.first() is None


def update_family_credentials(user, caretaker_username, child_username, current_password,
                             new_password="", confirm_password=""):
    """Update the two login names and shared password as one validated operation."""
    caretaker = normalize_username(caretaker_username)
    child = normalize_username(child_username)
    validate_username(caretaker)
    validate_username(child)
    if not verify_password(user.password_hash, current_password or ""):
        raise AuthError("Current password is incorrect.")
    if caretaker == child:
        raise AuthError("Caretaker and child usernames must be different.")
    primary = (Session.query(ChildProfile).filter_by(caregiver_user_id=user.id)
               .filter(ChildProfile.archived_at.is_(None))
               .order_by(ChildProfile.created_at.asc(), ChildProfile.id.asc()).first())
    if not username_available(caretaker, user.id):
        raise AuthError("That username is already taken. Please choose another.")
    if not username_available(child, user.id, primary.id if primary and primary.child_username == child else None):
        raise AuthError("That username is already taken. Please choose another.")
    if new_password or confirm_password:
        validate_password(new_password, caretaker)
        if child in new_password.lower():
            raise AuthError("Password must not contain the child username.")
        if new_password != confirm_password:
            raise AuthError("New passwords do not match.")
        user.password_hash = hash_password(new_password)
    user.username = caretaker
    user.child_username = child
    if primary:
        primary.child_username = child
    Session.commit()


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
