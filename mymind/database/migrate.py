"""Tiny migration runner. Add new functions to MIGRATIONS; each runs exactly once."""
from sqlalchemy import text
from database import db
from database.models import Base, WorldAsset, Asset3D, ParentLink, ActivityEvent

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


MIGRATIONS = [(1, "initial schema", m0001_initial), (2, "world assets", m0002_world_assets), (3, "ai 3d assets", m0003_assets3d),
              (4, "parent links", m0004_parent_links), (5, "id verification", m0005_id_verification),
              (6, "child age", m0006_child_age), (7, "activity events", m0007_activity_events),
              (8, "family login", m0008_family_login), (9, "activity last active", m0009_activity_last_active)]

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