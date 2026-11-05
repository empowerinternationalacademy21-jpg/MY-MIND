"""Tiny migration runner. Add new functions to MIGRATIONS; each runs exactly once."""
import uuid
from sqlalchemy import text
from database import db
from database.models import (Base, WorldAsset, Asset3D, ParentLink, ActivityEvent, WorldShareLink,
                             CaregiverRecommendationState, CaregiverQuestionnaire, Interaction, Favorite,
                             InterestProfile, DailyActivity, RecommendationLog, AuditLog, ChildAccount,
                             CaregiverChildAccess, ChildSummary, ChildInsightSnapshot, ChildMyWorld,
                             ChildRecommendation, ChildShareLink)

def m0001_initial(engine):
    Base.metadata.create_all(engine)

def m0002_world_assets(engine):
    """My World art library. Safe on fresh databases (m0001 may already have created it) and on existing ones."""
    WorldAsset.__table__.create(engine, checkfirst=True)


def m0003_assets3d(engine):
    """AI-generated 3D assets (admin pipeline). Safe on fresh and existing databases."""
    Asset3D.__table__.create(engine, checkfirst=True)


def m0004_parent_links(engine):
    """Private parent links (hashed token + view password). Safe on fresh and existing databases."""
    ParentLink.__table__.create(engine, checkfirst=True)


def _add_missing_columns(engine, table, columns):
    """ALTER TABLE ... ADD COLUMN for columns that don't exist yet (fresh databases already have them from create_all)."""
    with engine.begin() as c:
        have = {r[1] for r in c.execute(text(f"PRAGMA table_info({table})"))}
        for name, ddl in columns:
            if name not in have:
                c.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def m0005_id_verification(engine):
    """Caretaker 18+ verification outcome on users. Existing accounts start as 'none' and verify at their next login.
    """
    _add_missing_columns(engine, "users", [
        ("id_verification_status", "VARCHAR(12) NOT NULL DEFAULT 'none'"), ("is_adult_verified", "BOOLEAN NOT NULL DEFAULT 0"),
        ("verified_at", "DATETIME"), ("verified_country", "VARCHAR(3)"), ("verified_document_type", "VARCHAR(30)"),
        ("sumsub_applicant_id", "VARCHAR(40)"), ("verify_blocked_until", "DATETIME"),
        ("verify_underage_attempts", "INTEGER NOT NULL DEFAULT 0")])


def m0006_child_age(engine):
    """The child's age in years (3-25) drives age-appropriate content. NULL for existing profiles until a caregiver sets it."""
    _add_missing_columns(engine, "child_profiles", [("age_years", "INTEGER")])


def m0007_activity_events(engine):
    """Append-only child activity, with stable client IDs for safely retried heartbeats."""
    ActivityEvent.__table__.create(engine, checkfirst=True)


def m0008_family_login(engine):
    """Add the second family username and optional caretaker PIN without changing existing password hashes."""
    _add_missing_columns(engine, "users", [
        ("child_username", "VARCHAR(30)"), ("caretaker_pin_hash", "VARCHAR(255)"),
        ("caretaker_pin_enabled", "BOOLEAN NOT NULL DEFAULT 0")])
    with engine.begin() as c:
        rows = c.execute(text("SELECT id, username FROM users WHERE role = 'caregiver' AND child_username IS NULL")).all()
        used = {r[0] for r in c.execute(text("SELECT username FROM users WHERE username IS NOT NULL")).all()}
        used.update(r[0] for r in c.execute(text("SELECT child_username FROM users WHERE child_username IS NOT NULL")).all())
        for user_id, username in rows:
            stem = "".join(ch for ch in username.lower() if ch.isalnum() or ch in "._")[:23] or "friend"
            candidate, suffix = f"{stem}.child", 2
            while candidate in used:
                candidate = f"{stem[:max(1, 29 - len(str(suffix)))]}.{suffix}"
                suffix += 1
            c.execute(text("UPDATE users SET child_username = :name WHERE id = :id"), {"name": candidate, "id": user_id})
            used.add(candidate)
        c.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_child_username ON users(child_username)"))


def m0009_activity_last_active(engine):
    """Keep the original event start while updating the last-active timestamp for duration heartbeats."""
    _add_missing_columns(engine, "activity_events", [("last_active_at", "DATETIME")])
    with engine.begin() as c:
        c.execute(text("UPDATE activity_events SET last_active_at = created_at WHERE last_active_at IS NULL"))


def m0010_world_share_links(engine):
    """Anonymous read-only world links store only a hash of the URL token."""
    WorldShareLink.__table__.create(engine, checkfirst=True)


def m0011_recommendation_states(engine):
    CaregiverRecommendationState.__table__.create(engine, checkfirst=True)


def m0012_multi_child_profiles(engine):
    """Allow multiple profiles per caregiver and preserve every existing child record and dependent foreign key."""
    with engine.connect() as c:
        c.exec_driver_sql("PRAGMA foreign_keys=OFF")
        c.commit()
        with c.begin():
            c.exec_driver_sql("DROP TABLE IF EXISTS child_profiles_v2")
            c.exec_driver_sql("""CREATE TABLE child_profiles_v2 (
                id INTEGER NOT NULL PRIMARY KEY,
                caregiver_user_id INTEGER NOT NULL,
                display_name VARCHAR(40) NOT NULL DEFAULT 'Friend',
                avatar VARCHAR(20) NOT NULL DEFAULT 'smile',
                child_username VARCHAR(30),
                age_years INTEGER,
                archived_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                FOREIGN KEY(caregiver_user_id) REFERENCES users(id) ON DELETE CASCADE
            )""")
            c.exec_driver_sql("""INSERT INTO child_profiles_v2
                (id, caregiver_user_id, display_name, avatar, child_username, age_years, archived_at, created_at, updated_at)
                SELECT cp.id, cp.caregiver_user_id, cp.display_name, cp.avatar, u.child_username, cp.age_years, NULL, cp.created_at, cp.updated_at
                FROM child_profiles cp JOIN users u ON u.id = cp.caregiver_user_id""")
            c.exec_driver_sql("DROP TABLE child_profiles")
            c.exec_driver_sql("ALTER TABLE child_profiles_v2 RENAME TO child_profiles")
            c.exec_driver_sql("CREATE UNIQUE INDEX uq_child_profiles_username ON child_profiles(child_username)")
            c.exec_driver_sql("CREATE INDEX ix_child_profiles_caregiver_user_id ON child_profiles(caregiver_user_id)")
        c.exec_driver_sql("PRAGMA foreign_keys=ON")
        c.commit()
    _add_missing_columns(engine, "subscriptions", [("cancel_at_period_end", "BOOLEAN NOT NULL DEFAULT 0")])


def m0013_independent_child_portfolios(engine):
    """Add independent child identities, explicit caregiver grants, owner-scoped rows, and portfolio snapshots.

    Existing tables and IDs are preserved. Legacy child logins receive a separate credential row containing
    their current hash so existing families can continue signing in until they choose a new child password.
    """
    _add_missing_columns(engine, "child_profiles", [
        ("public_uid", "VARCHAR(36)"), ("gender", "VARCHAR(20)"),
        ("plan_state", "VARCHAR(20) NOT NULL DEFAULT 'free'"), ("plan_expires_at", "DATETIME")])
    _add_missing_columns(engine, "caregiver_questionnaires", [("caregiver_id", "INTEGER")])
    _add_missing_columns(engine, "interactions", [("caregiver_id", "INTEGER")])
    _add_missing_columns(engine, "activity_events", [("caregiver_id", "INTEGER")])
    _add_missing_columns(engine, "favorites", [("caregiver_id", "INTEGER")])
    _add_missing_columns(engine, "interest_profiles", [("caregiver_id", "INTEGER")])
    _add_missing_columns(engine, "daily_activities", [("caregiver_id", "INTEGER")])
    _add_missing_columns(engine, "recommendation_history", [("caregiver_id", "INTEGER")])
    _add_missing_columns(engine, "parent_links", [("caregiver_id", "INTEGER")])
    _add_missing_columns(engine, "world_share_links", [("caregiver_id", "INTEGER")])
    _add_missing_columns(engine, "caregiver_recommendation_states", [
        ("caregiver_id", "INTEGER"), ("created_at", "DATETIME")])
    _add_missing_columns(engine, "audit_logs", [
        ("actor_user_id", "INTEGER"), ("caregiver_id", "INTEGER"),
        ("child_id", "INTEGER"), ("ip_hash", "VARCHAR(64)")])

    for model in (ChildAccount, CaregiverChildAccess, ChildSummary, ChildInsightSnapshot, ChildMyWorld,
                  ChildRecommendation, ChildShareLink):
        model.__table__.create(engine, checkfirst=True)

    owner_columns = {
        "caregiver_questionnaires": ("child_profile_id", "submitted_at"),
        "interactions": ("child_profile_id", "occurred_at"),
        "activity_events": ("child_id", "created_at"),
        "favorites": ("child_profile_id", "created_at"),
        "interest_profiles": ("child_profile_id", "updated_at"),
        "daily_activities": ("child_profile_id", "created_at"),
        "recommendation_history": ("child_profile_id", "shown_at"),
        "parent_links": ("child_profile_id", "created_at"),
        "world_share_links": ("child_profile_id", "created_at"),
        "caregiver_recommendation_states": ("child_profile_id", "created_at"),
    }
    with engine.begin() as c:
        profile_rows = c.execute(text("SELECT id, caregiver_user_id, child_username, archived_at FROM child_profiles ORDER BY id")).all()
        used_names = {row[0] for row in c.execute(text("SELECT username FROM users")).all()}
        used_names.update(row[0] for row in c.execute(text("SELECT child_username FROM users WHERE child_username IS NOT NULL")).all())
        used_names.update(row[0] for row in c.execute(text("SELECT username FROM child_accounts")).all())
        for child_id, caregiver_id, child_username, archived_at in profile_rows:
            public_uid = c.execute(text("SELECT public_uid FROM child_profiles WHERE id=:id"), {"id": child_id}).scalar_one()
            if not public_uid:
                public_uid = str(uuid.uuid4())
                c.execute(text("UPDATE child_profiles SET public_uid=:uid WHERE id=:id"), {"uid": public_uid, "id": child_id})
            access_status = "revoked" if archived_at else "active"
            c.execute(text("""INSERT OR IGNORE INTO caregiver_child_access
                (caregiver_id, child_id, status, access_role, created_at, revoked_at)
                SELECT :caregiver_id, :child_id, :status, 'guardian', created_at, :revoked_at
                FROM child_profiles WHERE id=:child_id"""),
                {"caregiver_id": caregiver_id, "child_id": child_id, "status": access_status,
                 "revoked_at": archived_at})
            if not child_username:
                suffix = child_id
                child_username = f"child.{suffix}"
                while child_username in used_names:
                    suffix += 1
                    child_username = f"child.{suffix}"
                c.execute(text("UPDATE child_profiles SET child_username=:username WHERE id=:id"),
                          {"username": child_username, "id": child_id})
            if c.execute(text("SELECT 1 FROM child_accounts WHERE child_profile_id=:id"), {"id": child_id}).first():
                continue
            password_hash = c.execute(text("SELECT password_hash FROM users WHERE id=:id"), {"id": caregiver_id}).scalar_one()
            c.execute(text("""INSERT INTO child_accounts
                (child_profile_id, username, password_hash, status, legacy_shared_password, created_at, updated_at)
                VALUES (:child_id, :username, :password_hash, 'active', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""),
                {"child_id": child_id, "username": child_username, "password_hash": password_hash})
            used_names.add(child_username)

        for table, (child_column, created_column) in owner_columns.items():
            c.execute(text(f"""UPDATE {table} SET caregiver_id=(
                SELECT caregiver_user_id FROM child_profiles WHERE child_profiles.id={table}.{child_column})
                WHERE caregiver_id IS NULL"""))
            if table == "caregiver_recommendation_states":
                c.execute(text("UPDATE caregiver_recommendation_states SET created_at=CURRENT_TIMESTAMP WHERE created_at IS NULL"))
            c.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_scope_time ON {table} ({child_column}, caregiver_id, {created_column})"))

        for table, child_column in (("child_summaries", "child_id"), ("child_insight_snapshots", "child_id"),
                                    ("child_my_world", "child_id"), ("child_recommendations", "child_id"),
                                    ("child_share_links", "child_id")):
            c.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_caregiver_child ON {table} (caregiver_id, {child_column})"))
        c.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_child_profiles_public_uid ON child_profiles(public_uid)"))
        c.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_child_time ON audit_logs(child_id, created_at)"))


MIGRATIONS = [(1, "initial schema", m0001_initial), (2, "world assets", m0002_world_assets), (3, "ai 3d assets", m0003_assets3d),
              (4, "parent links", m0004_parent_links), (5, "id verification", m0005_id_verification),
              (6, "child age", m0006_child_age), (7, "activity events", m0007_activity_events),
              (8, "family login", m0008_family_login), (9, "activity last active", m0009_activity_last_active),
              (10, "world share links", m0010_world_share_links),
              (11, "recommendation states", m0011_recommendation_states),
              (12, "multi-child profiles", m0012_multi_child_profiles),
              (13, "independent child portfolios", m0013_independent_child_portfolios)]

def run_migrations():
    engine = db.get_engine()
    with engine.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        done = {r[0] for r in c.execute(text("SELECT version FROM schema_migrations"))}
    for version, name, fn in MIGRATIONS:
        if version in done:
            continue
        fn(engine)
        with engine.begin() as c:
            c.execute(text("INSERT INTO schema_migrations (version, name) VALUES (:v,:n)"), {"v": version, "n": name})
        print(f"applied migration {version}: {name}")