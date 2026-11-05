"""Single ownership boundary for caregiver-facing child data.

Callers must resolve a child through this module before reading child data. Queries include both
child ID and caregiver ID; legacy child_profile_id columns are mapped here instead of renamed.
"""
import hashlib
import hmac

from flask import current_app
from sqlalchemy.orm import Query

from database.db import Session
from database.models import (ActivityEvent, CaregiverChildAccess, CaregiverQuestionnaire,
                             CaregiverRecommendationState, ChildAccount, ChildProfile,
                             ChildRecommendation, ChildShareLink, ChildSummary, ChildInsightSnapshot,
                             ChildMyWorld, DailyActivity, Favorite, InterestProfile, Interaction,
                             ParentLink, RecommendationLog, WorldShareLink, AuditLog, utcnow)

_CHILD_COLUMN = {
    CaregiverQuestionnaire: "child_profile_id",
    Interaction: "child_profile_id",
    ActivityEvent: "child_id",
    Favorite: "child_profile_id",
    InterestProfile: "child_profile_id",
    DailyActivity: "child_profile_id",
    RecommendationLog: "child_profile_id",
    ParentLink: "child_profile_id",
    WorldShareLink: "child_profile_id",
    CaregiverRecommendationState: "child_profile_id",
    ChildAccount: "child_profile_id",
    ChildSummary: "child_id",
    ChildInsightSnapshot: "child_id",
    ChildMyWorld: "child_id",
    ChildRecommendation: "child_id",
    ChildShareLink: "child_id",
}


def access_grant(caregiver_id, child_id):
    return Session.query(CaregiverChildAccess).filter_by(
        caregiver_id=caregiver_id, child_id=child_id, status="active").first()


def can_access(caregiver_id, child_id):
    return bool(access_grant(caregiver_id, child_id))


def resolve_child_id(caregiver_id, child_id):
    return (Session.query(ChildProfile)
            .join(CaregiverChildAccess, CaregiverChildAccess.child_id == ChildProfile.id)
            .filter(ChildProfile.id == child_id,
                    CaregiverChildAccess.caregiver_id == caregiver_id,
                    CaregiverChildAccess.status == "active",
                    ChildProfile.archived_at.is_(None)).first())


def resolve_child_uid(caregiver_id, public_uid):
    return (Session.query(ChildProfile)
            .join(CaregiverChildAccess, CaregiverChildAccess.child_id == ChildProfile.id)
            .filter(ChildProfile.public_uid == public_uid,
                    CaregiverChildAccess.caregiver_id == caregiver_id,
                    CaregiverChildAccess.status == "active",
                    ChildProfile.archived_at.is_(None)).first())


def children_for_caregiver(caregiver_id, include_archived=False):
    query = (Session.query(ChildProfile)
             .join(CaregiverChildAccess, CaregiverChildAccess.child_id == ChildProfile.id)
             .filter(CaregiverChildAccess.caregiver_id == caregiver_id,
                     CaregiverChildAccess.status == "active"))
    if not include_archived:
        query = query.filter(ChildProfile.archived_at.is_(None))
    return query.order_by(ChildProfile.created_at.asc(), ChildProfile.id.asc())


def caregivers_for_child(child_id):
    return (Session.query(CaregiverChildAccess)
            .filter_by(child_id=child_id, status="active")
            .order_by(CaregiverChildAccess.created_at.asc()).all())


def query(model, caregiver_id, child_id):
    """Query one child-owned model with mandatory child and caregiver predicates."""
    child_column = _CHILD_COLUMN.get(model)
    if child_column is None or not hasattr(model, "caregiver_id"):
        raise TypeError(f"{model!r} is not registered as caregiver-scoped child data")
    return Session.query(model).filter(
        getattr(model, child_column) == child_id,
        model.caregiver_id == caregiver_id,
    )


def primary_caregiver_id(child_id):
    grant = (Session.query(CaregiverChildAccess.caregiver_id)
             .filter_by(child_id=child_id, status="active")
             .order_by(CaregiverChildAccess.created_at.asc()).first())
    return grant[0] if grant else None


def write_audit(caregiver_id, child_id, action, ip_address, target_type=None, target_id=None, detail=None):
    """Record a child action with a keyed IP digest; raw IPs and secrets are never persisted."""
    if child_id is not None and not can_access(caregiver_id, child_id):
        raise PermissionError("Caregiver does not have access to this child.")
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    ip_hash = hmac.new(secret, (ip_address or "unknown").encode("utf-8"), hashlib.sha256).hexdigest()
    row = AuditLog(administrator_id=None, actor_user_id=caregiver_id, caregiver_id=caregiver_id,
                   child_id=child_id, ip_hash=ip_hash, action=action[:60],
                   target_type=(target_type or "child")[:30],
                   target_id=str(target_id)[:40] if target_id is not None else None,
                   detail=(detail or "")[:500] or None, created_at=utcnow())
    Session.add(row)
    return row


def scope_query(model, caregiver_id, child_id) -> Query:
    """Descriptive alias for callers that prefer an explicit authorization name."""
    return query(model, caregiver_id, child_id)
