import pytest
from fake_turso import FakeTurso
from database import hrana


def test_driver_roundtrip_types_and_errors(tmp_path):
    fake = FakeTurso(str(tmp_path / "d.db"))
    try:
        c = hrana.connect(f"http://127.0.0.1:{fake.port}", "secret-token")
        cur = c.cursor()
        cur.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT UNIQUE, n REAL, b BLOB)")
        cur.execute("INSERT INTO t (name, n, b) VALUES (?, ?, ?)", ("a", 1.5, b"\x00\x01"))
        assert cur.lastrowid == 1 and cur.rowcount == 1
        c.commit()
        cur.execute("SELECT id, name, n, b FROM t")
        assert cur.fetchall() == [(1, "a", 1.5, b"\x00\x01")]
        with pytest.raises(hrana.IntegrityError):
            cur.execute("INSERT INTO t (name) VALUES (?)", ("a",))
        c.rollback()
        cur.execute("INSERT INTO t (name) VALUES (?)", ("rolled",)); c.rollback()
        cur.execute("SELECT count(*) FROM t"); assert cur.fetchone() == (1,)
        c.close()
    finally:
        fake.stop()


def test_bad_token_gives_clear_error(tmp_path):
    fake = FakeTurso(str(tmp_path / "d.db"))
    try:
        c = hrana.connect(f"http://127.0.0.1:{fake.port}", "wrong")
        with pytest.raises(hrana.OperationalError, match="auth token"):
            c.cursor().execute("SELECT 1")
    finally:
        fake.stop()