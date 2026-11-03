"""Database engine/session handling (Turso/libSQL in production, SQLite locally)."""
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import scoped_session, sessionmaker, DeclarativeBase

Session = scoped_session(sessionmaker(autoflush=True, expire_on_commit=False))
_engine = None


class Base(DeclarativeBase):
    pass


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