"""Relational schema for MyMind."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (Column, Integer, String, Text, Float, DateTime, Date, ForeignKey,
                        UniqueConstraint, Index, Boolean)
from sqlalchemy.orm import relationship
from database.db import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, consistently


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(40), nullable=False, unique=True)   # normalised (lower-case)
    child_username = Column(String(30), unique=True)             # second login name; shares this account's password hash
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="caregiver")  # caregiver | admin
    caretaker_pin_hash = Column(String(255))
    caretaker_pin_enabled = Column(Boolean, nullable=False, default=False)
    account_status = Column(String(20), nullable=False, default="active")  # active | suspended
    deletion_requested_at = Column(DateTime)
    # ---- ID verification (18+ caretaker). Only the OUTCOME is stored: never a name, email, date of birth or document number ----
    id_verification_status = Column(String(12), nullable=False, default="none")   # none | pending | verified | retry | rejected | blocked
    is_adult_verified = Column(Boolean, nullable=False, default=False)
    verified_at = Column(DateTime)
    verified_country = Column(String(3))                 # ISO alpha-3 of the document, as reported by the provider
    verified_document_type = Column(String(30))
    sumsub_applicant_id = Column(String(40))             # opaque provider id (needed to look the result up)
    verify_blocked_until = Column(DateTime)              # cool-down after repeated under-18 declarations
    verify_underage_attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    children = relationship("ChildProfile", back_populates="caregiver")
    child_access = relationship("CaregiverChildAccess", back_populates="caregiver")


class ChildProfile(Base):
    __tablename__ = "child_profiles"
    id = Column(Integer, primary_key=True)
    caregiver_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    public_uid = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    display_name = Column(String(40), nullable=False, default="Friend")  # nickname only
    avatar = Column(String(20), nullable=False, default="smile")
    child_username = Column(String(30), unique=True)
    age_years = Column(Integer)                      # 3-25, set by the caregiver; NULL = not set (original behaviour). Years only, never a date of birth
    gender = Column(String(20))
    plan_state = Column(String(20), nullable=False, default="free")  # free | paid_active | paid_expired | suspended
    plan_expires_at = Column(DateTime)
    archived_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    caregiver = relationship("User", back_populates="children")
    child_account = relationship("ChildAccount", uselist=False, back_populates="child")
    access_grants = relationship("CaregiverChildAccess", back_populates="child")


class ChildAccount(Base):
    """Independent child login credentials; caregiver access is granted separately."""
    __tablename__ = "child_accounts"
    id = Column(Integer, primary_key=True)
    child_profile_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False, unique=True)
    username = Column(String(30), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    legacy_shared_password = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    child = relationship("ChildProfile", back_populates="child_account")


class CaregiverChildAccess(Base):
    """Explicit authorization edge between an independent caregiver account and child account."""
    __tablename__ = "caregiver_child_access"
    id = Column(Integer, primary_key=True)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    child_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(16), nullable=False, default="active")
    access_role = Column(String(20), nullable=False, default="guardian")
    created_at = Column(DateTime, default=utcnow, nullable=False)
    revoked_at = Column(DateTime)
    caregiver = relationship("User", back_populates="child_access")
    child = relationship("ChildProfile", back_populates="access_grants")
    __table_args__ = (UniqueConstraint("caregiver_id", "child_id", name="uq_caregiver_child_access"),
                      Index("ix_child_access_caregiver_status", "caregiver_id", "status"),
                      Index("ix_child_access_child_status", "child_id", "status"))


class CaregiverQuestionnaire(Base):
    __tablename__ = "caregiver_questionnaires"
    id = Column(Integer, primary_key=True)
    child_profile_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False, unique=True)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    responses_json = Column(Text, nullable=False, default="{}")
    submitted_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ConsentRecord(Base):
    __tablename__ = "consent_records"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    consent_type = Column(String(40), nullable=False)
    policy_version = Column(String(20), nullable=False)
    granted_at = Column(DateTime, default=utcnow, nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_code = Column(String(20), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    duration_days = Column(Integer, nullable=False)
    # pending_payment | pending_verification | active | rejected | expired
    status = Column(String(24), nullable=False, default="pending_payment")
    starts_at = Column(DateTime)
    expires_at = Column(DateTime)
    cancel_at_period_end = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_sub_user_status", "user_id", "status"),)


class PaymentVerificationRequest(Base):
    __tablename__ = "payment_verification_requests"
    id = Column(Integer, primary_key=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, unique=True)
    payment_reference = Column(String(80), nullable=False, unique=True)  # upper-cased
    payment_date = Column(Date, nullable=False)
    status = Column(String(24), nullable=False, default="pending_verification")  # | approved | rejected
    caregiver_note = Column(Text)
    administrator_note = Column(Text)
    reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    subscription = relationship("Subscription")


class ContentItem(Base):
    __tablename__ = "content_items"
    id = Column(Integer, primary_key=True)
    provider = Column(String(20), nullable=False)       # pexels | youtube | spotify | demo
    provider_content_id = Column(String(120), nullable=False)
    content_type = Column(String(12), nullable=False)   # picture | video | short | song
    title = Column(String(300), nullable=False)
    description = Column(Text)
    thumbnail_url = Column(String(600))
    canonical_url = Column(String(600))
    category = Column(String(30), nullable=False, default="objects")
    tags_json = Column(Text, default="[]")
    attribution_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("provider", "provider_content_id", "content_type", name="uq_content_provider"),
                      Index("ix_content_category", "category"))


class Interaction(Base):
    __tablename__ = "interactions"
    id = Column(Integer, primary_key=True)
    child_profile_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content_item_id = Column(Integer, ForeignKey("content_items.id", ondelete="SET NULL"))
    # selected | watched | like | dislike | skip | favorite | unfavorite | explore | caregiver_adjust
    interaction_type = Column(String(24), nullable=False)
    category = Column(String(30))
    occurred_at = Column(DateTime, default=utcnow, nullable=False)
    content = relationship("ContentItem")
    __table_args__ = (Index("ix_inter_child_time", "child_profile_id", "occurred_at"),
                      Index("ix_inter_scope_time", "child_profile_id", "caregiver_id", "occurred_at"))


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    id = Column(Integer, primary_key=True)
    child_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    stop = Column(String(24), nullable=False)
    content_id = Column(Integer, ForeignKey("content_items.id", ondelete="SET NULL"))
    content_title = Column(String(300))
    event_type = Column(String(12), nullable=False)  # view | watch | like | dislike | favorite | search | next
    duration_seconds = Column(Integer, nullable=False, default=0)
    client_event_id = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    last_active_at = Column(DateTime, default=utcnow, nullable=False)
    # ---- richer engagement detail (migration 14). All nullable/defaulted so older rows and older clients keep working ----
    content_type = Column(String(12))                # picture | video | short | song (copied from the content item when the event is stored)
    category = Column(String(30))                    # interest category (copied from the content item, or the explored category)
    completion_pct = Column(Float)                   # 0-100, only when the player reported the content length; NULL = unknown
    content_seconds = Column(Integer)                # total length of the content as reported by the player, when known
    pause_count = Column(Integer, nullable=False, default=0)
    resume_count = Column(Integer, nullable=False, default=0)
    replay_count = Column(Integer, nullable=False, default=0)   # times playback restarted after the content ended
    completed = Column(Boolean, nullable=False, default=False)
    measured = Column(Boolean, nullable=False, default=False)   # True = time came from the player (playing time only); False = time the viewer was open
    content = relationship("ContentItem")
    __table_args__ = (Index("ix_activity_child_time", "child_id", "created_at"),
                      Index("ix_activity_scope_time", "child_id", "caregiver_id", "created_at"),
                      Index("ix_activity_child_stop_time", "child_id", "stop", "created_at"),
                      Index("ix_activity_child_type_time", "child_id", "event_type", "created_at"),
                      Index("ix_activity_child_content", "child_id", "content_id"),
                      Index("ix_activity_child_category_time", "child_id", "category", "created_at"))


class Favorite(Base):
    __tablename__ = "favorites"
    id = Column(Integer, primary_key=True)
    child_profile_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content_item_id = Column(Integer, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    content = relationship("ContentItem")
    __table_args__ = (UniqueConstraint("child_profile_id", "content_item_id", name="uq_fav"),
                      Index("ix_favorite_scope_time", "child_profile_id", "caregiver_id", "created_at"))


class InterestProfile(Base):
    __tablename__ = "interest_profiles"
    id = Column(Integer, primary_key=True)
    child_profile_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(30), nullable=False)
    interest_score = Column(Float, nullable=False, default=0.0)
    evidence_count = Column(Integer, nullable=False, default=0)   # child-originated evidence only
    caregiver_seed = Column(Float, nullable=False, default=0.0)   # kept separate from child reactions
    first_observed_at = Column(DateTime, default=utcnow)
    last_observed_at = Column(DateTime)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("child_profile_id", "category", name="uq_interest"),
                      Index("ix_interest_scope_time", "child_profile_id", "caregiver_id", "updated_at"))


class DailyActivity(Base):
    __tablename__ = "daily_activities"
    id = Column(Integer, primary_key=True)
    child_profile_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activity_type = Column(String(30), nullable=False)  # activity | observation | update
    title = Column(String(200), nullable=False)
    notes = Column(Text)
    source = Column(String(20), nullable=False, default="caregiver")  # caregiver | child
    activity_date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_act_child_date", "child_profile_id", "activity_date"),
                      Index("ix_daily_activity_scope_time", "child_profile_id", "caregiver_id", "created_at"))


class CaregiverSettings(Base):
    __tablename__ = "caregiver_settings"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    settings_json = Column(Text, nullable=False, default="{}")
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AdminSetting(Base):
    __tablename__ = "admin_settings"
    id = Column(Integer, primary_key=True)
    setting_key = Column(String(60), nullable=False, unique=True)
    setting_value = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    administrator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    child_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="SET NULL"))
    ip_hash = Column(String(64))
    action = Column(String(60), nullable=False)
    target_type = Column(String(30))
    target_id = Column(String(40))
    detail = Column(Text)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class RecommendationLog(Base):
    __tablename__ = "recommendation_history"
    id = Column(Integer, primary_key=True)
    child_profile_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content_item_id = Column(Integer, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)
    reason = Column(String(200))
    shown_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_rec_child_time", "child_profile_id", "shown_at"),
                      Index("ix_rec_scope_time", "child_profile_id", "caregiver_id", "shown_at"))


class WorldAsset(Base):
    """Admin-uploaded art for My World: island art, stop interiors, map backgrounds and characters/stars."""
    __tablename__ = "world_assets"
    id = Column(Integer, primary_key=True)
    kind = Column(String(16), nullable=False)             # island | interior | character | background
    stop = Column(String(20), nullable=False, default="")  # home | sports | music | ... ("" for backgrounds)
    zone = Column(String(20), nullable=False, default="")  # sports zone (football, basketball ...) or ""
    theme = Column(String(20), nullable=False, default="")  # world theme this art belongs to, "" = any theme
    name = Column(String(80), nullable=False, default="")
    caption = Column(String(240), nullable=False, default="")
    filename = Column(String(80), nullable=False, unique=True)
    width = Column(Integer, nullable=False, default=0)
    height = Column(Integer, nullable=False, default=0)
    is_real_person = Column(Boolean, nullable=False, default=False)
    rights_confirmed = Column(Boolean, nullable=False, default=False)
    source_note = Column(String(300), nullable=False, default="")
    active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    uploaded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_world_asset_lookup", "kind", "stop", "active"),)


class Asset3D(Base):
    """An AI-generated 3D item/character. Flow: queued -> running -> review -> published (or failed / rejected).
    Only an administrator can create, review and publish; children and caregivers only ever see published assets."""
    __tablename__ = "assets3d"
    id = Column(Integer, primary_key=True)
    category = Column(String(12), nullable=False)          # food | nature | music | sports
    archetype = Column(String(40), nullable=False)         # key from services/ai3d/safe_prompts.ARCHETYPES
    kind = Column(String(10), nullable=False)              # item | character
    name = Column(String(80), nullable=False, default="")
    caption = Column(String(240), nullable=False, default="")
    provider = Column(String(10), nullable=False)          # meshy | tripo
    options_json = Column(Text, nullable=False, default="{}")     # validated allowlist choices (never free text)
    prompt = Column(Text, nullable=False, default="")             # the exact prompt that was sent (audit)
    stage = Column(String(20), nullable=False, default="start")
    status = Column(String(12), nullable=False, default="queued")
    tasks_json = Column(Text, nullable=False, default="{}")       # provider task ids per stage
    next_poll_at = Column(DateTime)
    concept_filename = Column(String(80), nullable=False, default="")
    glb_filename = Column(String(80), nullable=False, default="")  # primary (idle / static) model
    clips_json = Column(Text, nullable=False, default="{}")        # {"run": "<file>.glb", ...} animation variants
    stats_json = Column(Text, nullable=False, default="{}")        # triangles, bytes, textures, animations ...
    rigged = Column(Boolean, nullable=False, default=False)
    error = Column(String(400), nullable=False, default="")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    __table_args__ = (Index("ix_asset3d_status", "status", "category"),)


class ParentLink(Base):
    """A private, read-only family view of one child's world. The URL token is never stored (only its SHA-256), and the
    viewer must also enter a per-link view password (Argon2id) chosen by the caregiver. NOT the caregiver's account password."""
    __tablename__ = "parent_links"
    id = Column(Integer, primary_key=True)
    child_profile_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    label = Column(String(40), nullable=False, default="")
    expires_at = Column(DateTime)                       # NULL = until revoked
    revoked_at = Column(DateTime)
    failed_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime)
    view_count = Column(Integer, nullable=False, default=0)
    last_viewed_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_parent_link_child", "child_profile_id"),
                      Index("ix_parent_link_scope_time", "child_profile_id", "caregiver_id", "created_at"))


class WorldShareLink(Base):
    """Revocable, token-only read access to one child's world and activity summary."""
    __tablename__ = "world_share_links"
    id = Column(Integer, primary_key=True)
    child_profile_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime)
    revoked_at = Column(DateTime)
    last_opened_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_world_share_child", "child_profile_id"),
                      Index("ix_world_share_scope_time", "child_profile_id", "caregiver_id", "created_at"))


class CaregiverRecommendationState(Base):
    __tablename__ = "caregiver_recommendation_states"
    id = Column(Integer, primary_key=True)
    child_profile_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recommendation_key = Column(String(100), nullable=False)
    dismissed_at = Column(DateTime)
    remind_until = Column(DateTime)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("child_profile_id", "recommendation_key", name="uq_rec_state_child_key"),
                      Index("ix_rec_state_child", "child_profile_id"),
                      Index("ix_rec_state_scope_time", "child_profile_id", "caregiver_id", "created_at"))


class ChildSummary(Base):
    __tablename__ = "child_summaries"
    id = Column(Integer, primary_key=True)
    child_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    period = Column(String(16), nullable=False)
    generated_at = Column(DateTime, default=utcnow, nullable=False)
    content_json = Column(Text, nullable=False, default="{}")
    __table_args__ = (UniqueConstraint("child_id", "period", name="uq_child_summary_period"),
                      Index("ix_child_summary_scope_time", "child_id", "caregiver_id", "generated_at"))


class ChildInsightSnapshot(Base):
    __tablename__ = "child_insight_snapshots"
    id = Column(Integer, primary_key=True)
    child_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    period = Column(String(16), nullable=False)
    generated_at = Column(DateTime, default=utcnow, nullable=False)
    metrics_json = Column(Text, nullable=False, default="{}")
    __table_args__ = (UniqueConstraint("child_id", "period", name="uq_child_insight_period"),
                      Index("ix_child_insight_scope_time", "child_id", "caregiver_id", "generated_at"))


class ChildMyWorld(Base):
    __tablename__ = "child_my_world"
    id = Column(Integer, primary_key=True)
    child_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False, unique=True)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content_json = Column(Text, nullable=False, default="{}")
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    __table_args__ = (Index("ix_child_my_world_scope_time", "child_id", "caregiver_id", "updated_at"),)


class ChildRecommendation(Base):
    __tablename__ = "child_recommendations"
    id = Column(Integer, primary_key=True)
    child_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    generated_at = Column(DateTime, default=utcnow, nullable=False)
    items_json = Column(Text, nullable=False, default="[]")
    __table_args__ = (Index("ix_child_recommendation_scope_time", "child_id", "caregiver_id", "generated_at"),)


class ChildShareLink(Base):
    __tablename__ = "child_share_links"
    id = Column(Integer, primary_key=True)
    child_id = Column(Integer, ForeignKey("child_profiles.id", ondelete="CASCADE"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    expires_at = Column(DateTime)
    revoked_at = Column(DateTime)
    last_accessed_at = Column(DateTime)
    access_count = Column(Integer, nullable=False, default=0)
    passcode_hash = Column(String(255))
    permissions_json = Column(Text, nullable=False, default='{"graphs":true,"summaries":true,"my_world":true,"recommendations":true}')
    __table_args__ = (Index("ix_child_share_scope_time", "child_id", "caregiver_id", "created_at"),)
