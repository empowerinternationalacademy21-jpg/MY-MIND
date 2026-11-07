"""Registration, password hashing (Argon2id) and authentication."""
import re
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from sqlalchemy.exc import IntegrityError
from database.db import Session
from database.models import User, AuditLog, ChildProfile, ChildAccount, CaregiverChildAccess

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
    import uuid
    while True:
        candidate = "kid." + uuid.uuid4().hex[:12]
        if username_available(candidate):
            return candidate


_DUMMY = _ph.hash("dummy-password-for-timing")


def authenticate(username, password):
    user = Session.query(User).filter_by(username=normalize_username(username)).first()
    if not user:
        verify_password(_DUMMY, password or "")   # keep timing similar
        return None
    return user if verify_password(user.password_hash, password or "") else None


def authenticate_identity(username, password):
    """Authenticate a caregiver or child identity and resolve the target child scope.

    This supports both the legacy shared caregiver/child credentials and the new
    independent child-account model, while preserving a single auth contract.
    """
    username = normalize_username(username)
    user = Session.query(User).filter_by(username=username).first()
    role = user.role if user else "caregiver"
    child = None

    if user is None:
        account = Session.query(ChildAccount).filter_by(username=username, status="active").first()
        if account:
            child = Session.get(ChildProfile, account.child_profile_id)
            from services import child_scope
            caregiver_id = child_scope.primary_caregiver_id(child.id) if child else None
            user = Session.get(User, caregiver_id) if caregiver_id else None
            if not child or child.archived_at or not user or user.account_status != "active":
                user = None
            elif not verify_password(account.password_hash, password or ""):
                return None, None, None
            else:
                return user, "child", child.id

        legacy_child = Session.query(ChildProfile).filter_by(child_username=username, archived_at=None).first()
        if legacy_child:
            user = Session.get(User, legacy_child.caregiver_user_id)
            child = legacy_child
            role = "child"

    if user is None:
        verify_password(_DUMMY, password or "")
        return None, None, None

    if role == "child":
        if not child:
            child = (Session.query(ChildProfile)
                     .filter_by(caregiver_user_id=user.id, archived_at=None)
                     .order_by(ChildProfile.created_at.asc(), ChildProfile.id.asc()).first())
        if child is None:
            return None, None, None
        legacy_hash = None
        if user.child_username == username:
            legacy_hash = user.password_hash
        elif child.child_username == username:
            legacy_hash = user.password_hash
        else:
            legacy_hash = None
        if legacy_hash is None:
            account = Session.query(ChildAccount).filter_by(child_profile_id=child.id, username=username, status="active").first()
            if not account or not verify_password(account.password_hash, password or ""):
                return None, None, None
            return user, "child", child.id
        if not verify_password(legacy_hash, password or ""):
            return None, None, None
        return user, "child", child.id

    if verify_password(user.password_hash, password or ""):
        return user, role, None
    if role == "caregiver":
        # Same family username, different password: a child's own password opens that child's world.
        child_id = match_family_child(user, password)
        if child_id:
            return user, "child", child_id
    return None, None, None


def _family_child_accounts(user_id):
    """Active child logins under one caretaker that have their OWN password (not the legacy shared one)."""
    return (Session.query(ChildAccount)
            .join(ChildProfile, ChildProfile.id == ChildAccount.child_profile_id)
            .join(CaregiverChildAccess, CaregiverChildAccess.child_id == ChildProfile.id)
            .filter(CaregiverChildAccess.caregiver_id == user_id,
                    CaregiverChildAccess.status == "active",
                    ChildProfile.archived_at.is_(None),
                    ChildAccount.status == "active",
                    ChildAccount.legacy_shared_password.is_(False))
            .order_by(ChildAccount.id.asc()).all())


def match_family_child(user, password):
    """Return the child profile id whose own password matches, or None."""
    for account in _family_child_accounts(user.id):
        if verify_password(account.password_hash, password or ""):
            return account.child_profile_id
    return None


def password_in_use_in_family(user, password, exclude_child_id=None):
    """True when the password already opens the caretaker or another child under this caretaker."""
    if verify_password(user.password_hash, password or ""):
        return True
    for account in _family_child_accounts(user.id):
        if exclude_child_id is not None and account.child_profile_id == exclude_child_id:
            continue
        if verify_password(account.password_hash, password or ""):
            return True
    return False


def validate_child_password(user, password, exclude_child_id=None):
    """A child password must be strong AND unique within the family, or login could not tell them apart."""
    validate_password(password, user.username)
    if password_in_use_in_family(user, password, exclude_child_id):
        raise AuthError("Please choose a different password. Each child and the caretaker need their own.")


def set_child_password(user, child, new_password):
    validate_child_password(user, new_password, exclude_child_id=child.id)
    account = Session.query(ChildAccount).filter_by(child_profile_id=child.id).first()
    if account is None:
        username = child.child_username or new_child_username(user)
        account = ChildAccount(child_profile_id=child.id, username=username,
                               password_hash=hash_password(new_password), legacy_shared_password=False)
        Session.add(account)
    else:
        account.password_hash = hash_password(new_password)
        account.legacy_shared_password = False
    Session.commit()


def username_available(username, user_id=None, exclude_child_id=None):
    username = normalize_username(username)
    query = Session.query(User).filter((User.username == username) | (User.child_username == username))
    if user_id is not None:
        query = query.filter(User.id != user_id)
    children = Session.query(ChildProfile).filter_by(child_username=username)
    if exclude_child_id is not None:
        children = children.filter(ChildProfile.id != exclude_child_id)
    child_accounts = Session.query(ChildAccount).filter_by(username=username)
    if exclude_child_id is not None:
        child_accounts = child_accounts.filter(ChildAccount.child_profile_id != exclude_child_id)
    return query.first() is None and children.first() is None and child_accounts.first() is None


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
        child_account = Session.query(ChildAccount).filter_by(child_profile_id=primary.id).first()
        if child_account:
            child_account.username = child
            if new_password and child_account.legacy_shared_password:
                child_account.password_hash = hash_password(new_password)
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
