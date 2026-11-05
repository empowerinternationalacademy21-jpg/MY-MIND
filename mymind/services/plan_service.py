"""Server-side plan feature gates and profile/share limits."""
from database.db import Session
from database.models import ChildProfile, Subscription
from services import payment_service
from services.plan_config import (FREE_ACTIVE_SHARE_LINK_LIMIT, FREE_CHILD_PROFILE_LIMIT,
                                  FREE_FEATURES, FREE_HISTORY_DAYS, PAID_CHILD_PROFILE_LIMIT,
                                  PAID_FEATURES, PAID_HISTORY_DAYS)


def current_subscription(user_id):
    return payment_service.active_subscription(user_id)


def current_plan(user_id):
    subscription = current_subscription(user_id)
    if subscription:
        return subscription.plan_code
    latest = (Session.query(Subscription).filter_by(user_id=user_id)
              .order_by(Subscription.id.desc()).first())
    return "free" if latest and latest.status == "expired" else "none"


def has_basic_access(user_id):
    state = payment_service.access_state(user_id)
    return state == "active" or (state == "expired" and current_plan(user_id) == "free")


def is_paid(user_id):
    return current_plan(user_id) not in ("free", "none")


def can_use(user_id, feature):
    plan = current_plan(user_id)
    if plan == "none" or not has_basic_access(user_id):
        return False
    return feature in (PAID_FEATURES if plan != "free" else FREE_FEATURES)


def history_days(user_id):
    return PAID_HISTORY_DAYS if is_paid(user_id) else FREE_HISTORY_DAYS


def child_limit(user_id):
    return PAID_CHILD_PROFILE_LIMIT if is_paid(user_id) else FREE_CHILD_PROFILE_LIMIT


def active_share_limit(user_id):
    return None if is_paid(user_id) else FREE_ACTIVE_SHARE_LINK_LIMIT


def can_add_child(user_id):
    count = Session.query(ChildProfile).filter_by(caregiver_user_id=user_id, archived_at=None).count()
    return count < child_limit(user_id)


def child_is_read_only(user_id, child):
    if not child or is_paid(user_id):
        return False
    active = (Session.query(ChildProfile).filter_by(caregiver_user_id=user_id, archived_at=None)
              .order_by(ChildProfile.created_at.asc(), ChildProfile.id.asc()).all())
    return child.id not in {profile.id for profile in active[:FREE_CHILD_PROFILE_LIMIT]}
