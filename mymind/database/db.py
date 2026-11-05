"""Database engine/session handling (Turso/libSQL in production, SQLite locally)."""
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import scoped_session, sessionmaker, DeclarativeBase, Session as ORMSession

Session = scoped_session(sessionmaker(autoflush=True, expire_on_commit=False))
_engine = None


class Base(DeclarativeBase):
    pass


@event.listens_for(ORMSession, "before_flush")
def _enforce_child_caregiver_scope(session, _flush_context, _instances):
    from database.models import (CaregiverQuestionnaire, Interaction, ActivityEvent, Favorite,
                                 InterestProfile, DailyActivity, RecommendationLog, ParentLink,
                                 WorldShareLink, CaregiverRecommendationState, ChildSummary,
                                 ChildInsightSnapshot, ChildMyWorld, ChildRecommendation, ChildShareLink,
                                 ChildProfile)

    child_fields = {
        CaregiverQuestionnaire: "child_profile_id", Interaction: "child_profile_id",
        ActivityEvent: "child_id", Favorite: "child_profile_id", InterestProfile: "child_profile_id",
        DailyActivity: "child_profile_id", RecommendationLog: "child_profile_id",
        ParentLink: "child_profile_id", WorldShareLink: "child_profile_id",
        CaregiverRecommendationState: "child_profile_id", ChildSummary: "child_id",
        ChildInsightSnapshot: "child_id", ChildMyWorld: "child_id", ChildRecommendation: "child_id",
        ChildShareLink: "child_id",
    }
    caregiver_by_child = {}
    for row in session.new.union(session.dirty):
        child_field = next((field for model, field in child_fields.items() if isinstance(row, model)), None)
        if not child_field:
            continue
        child_id = getattr(row, child_field, None)
        if child_id is None:
            continue
        if child_id not in caregiver_by_child:
            child = session.get(ChildProfile, child_id)
            caregiver_by_child[child_id] = child.caregiver_user_id if child else None
        expected = caregiver_by_child[child_id]
        if expected is None:
            continue
        current = getattr(row, "caregiver_id", None)
        if current is None:
            row.caregiver_id = expected
        elif current != expected:
            raise ValueError("Child data caregiver does not match the child's owner.")


def init_engine(url: str):
    global _engine
    Session.remove()
    if _engine is not None:
        _engine.dispose()
    import database.hrana  # noqa: F401  (registers the sqlite+hrana dialect)
    hrana = url.startswith("sqlite+hrana")
    _engine = create_engine(url, future=True, pool_pre_ping=not hrana, pool_recycle=300 if hrana else -1)
    if url.startswith("sqlite") and not hrana:
        @event.listens_for(_engine, "connect")
        def _fk(dbapi_conn, _):  # enforce foreign keys on plain SQLite
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    Session.configure(bind=_engine)
    return _engine


def get_engine():
    return _engine


@contextmanager
def transaction():
    """Commit on success, roll back on any error."""
    try:
        yield Session
        Session.commit()
    except Exception:
        Session.rollback()
        raise