"""Pure-Python Turso (libSQL) driver over HTTPS — no Rust, no native wheels.

Implements just enough of DB-API 2.0 + a SQLAlchemy dialect on top of Turso's "Hrana over HTTP" endpoint
(POST /v2/pipeline). It installs on any Python version/OS because it only needs `requests`.

URL form (built by config.py):  sqlite+hrana://<db-host>?authToken=<token>
Each statement is one HTTPS round-trip. Writes run inside a server-side stream held open (via `baton`)
from BEGIN until COMMIT/ROLLBACK, so SQLAlchemy transactions stay atomic.

Connection reliability: Turso closes idle keep-alive connections, so a pooled socket can be dead by the time it is
reused ("Remote end closed connection without response"). `_post` therefore retries on connection errors/timeouts
with a brand-new requests.Session instead of failing the request.
"""
import base64
import re
import time
import requests
from sqlalchemy.dialects import registry
from sqlalchemy.dialects.sqlite.base import SQLiteDialect

# ---- DB-API 2.0 module surface ----
apilevel = "2.0"
threadsafety = 1
paramstyle = "qmark"
sqlite_version = "3.34.0"
sqlite_version_info = (3, 34, 0)      # keeps SQLAlchemy on lastrowid (no RETURNING) -> simplest, most compatible
version_info = (1, 0, 0)
Binary = bytes


class Warning(Exception): pass
class Error(Exception): pass
class InterfaceError(Error): pass
class DatabaseError(Error): pass
class DataError(DatabaseError): pass
class OperationalError(DatabaseError): pass
class IntegrityError(DatabaseError): pass
class InternalError(DatabaseError): pass
class ProgrammingError(DatabaseError): pass
class NotSupportedError(DatabaseError): pass


def _map_error(message, code=""):
    m = (message or "").lower()
    if "constraint" in m or "constraint" in (code or "").lower():
        return IntegrityError(message)
    if "syntax error" in m or "no such table" in m or "no such column" in m or "has no column" in m:
        return ProgrammingError(message)
    return OperationalError(message)


def _encode(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode().rstrip("=")}
    if isinstance(v, str):
        return {"type": "text", "value": v}
    if hasattr(v, "isoformat"):
        return {"type": "text", "value": v.isoformat(sep=" ")}
    return {"type": "text", "value": str(v)}


def _decode(c):
    t = c.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(c["value"])
    if t == "float":
        return float(c["value"])
    if t == "blob":
        b = c.get("base64", "")
        return base64.b64decode(b + "=" * (-len(b) % 4))
    return c.get("value")


_DML = re.compile(r"^\s*(insert|update|delete|replace)\b", re.I)


class Cursor:
    arraysize = 1

    def __init__(self, conn):
        self.connection = conn
        self.description = None
        self.rowcount = -1
        self.lastrowid = None
        self._rows = []
        self._pos = 0
        self._closed = False

    def execute(self, sql, params=()):
        if isinstance(params, dict):
            raise NotSupportedError("named parameters are not supported")
        result = self.connection._run(sql, list(params or ()))
        cols = result.get("cols") or []
        self.description = tuple((c.get("name"), None, None, None, None, None, None) for c in cols) if cols else None
        self._rows = [tuple(_decode(c) for c in row) for row in result.get("rows", [])]
        self._pos = 0
        self.rowcount = result.get("affected_row_count", -1) if not cols else len(self._rows)
        lid = result.get("last_insert_rowid")
        self.lastrowid = int(lid) if lid is not None else None
        return self

    def executemany(self, sql, seq):
        total = 0
        for params in seq:
            self.execute(sql, params)
            total += max(self.rowcount, 0)
        self.rowcount = total
        return self

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]; self._pos += 1
        return row

    def fetchmany(self, size=None):
        size = size or self.arraysize
        out = self._rows[self._pos:self._pos + size]; self._pos += len(out)
        return out

    def fetchall(self):
        out = self._rows[self._pos:]; self._pos = len(self._rows)
        return out

    def close(self):
        self._closed = True

    def setinputsizes(self, *a): pass
    def setoutputsize(self, *a): pass
    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    _RETRIES = 3          # total attempts per HTTPS request when the connection itself fails

    def __init__(self, base_url, token, timeout=20):
        self.url, self.token, self.timeout = base_url.rstrip("/"), token, timeout
        self.baton, self.in_txn = None, False
        self._http = requests.Session()

    # -- transport --
    def _reset_http(self):
        """Throw away the pooled sockets (Turso may have closed them) and start a clean session."""
        try:
            self._http.close()
        except Exception:
            pass
        self._http = requests.Session()

    def _post(self, body):
        """POST one pipeline request, retrying on dead keep-alive connections and timeouts."""
        last = None
        for attempt in range(self._RETRIES):
            try:
                return self._http.post(
                    self.url + "/v2/pipeline", json=body, timeout=self.timeout,
                    headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
            except (requests.ConnectionError, requests.Timeout) as exc:
                last = exc
                self._reset_http()
                if attempt < self._RETRIES - 1:
                    time.sleep(0.2 * (attempt + 1))
            except requests.RequestException as exc:
                raise OperationalError(f"Could not reach Turso: {exc.__class__.__name__}")
        raise OperationalError(f"Could not reach Turso: {last.__class__.__name__}")

    def _pipeline(self, reqs, close=False):
        body = {"baton": self.baton, "requests": list(reqs) + ([{"type": "close"}] if close else [])}
        r = self._post(body)
        if r.status_code in (401, 403):
            raise OperationalError("Turso rejected the auth token (check TURSO_AUTH_TOKEN).")
        if r.status_code == 404:
            raise OperationalError("Turso database not found (check TURSO_DATABASE_URL).")
        if r.status_code != 200:
            raise OperationalError(f"Turso returned HTTP {r.status_code}.")
        data = r.json()
        self.baton = None if close else data.get("baton")
        if data.get("base_url"):
            self.url = data["base_url"].rstrip("/")
        return data.get("results", [])

    @staticmethod
    def _stmt(sql, args=()):
        return {"type": "execute", "stmt": {"sql": sql, "args": [_encode(a) for a in args], "want_rows": True}}

    def _run(self, sql, args):
        dml = bool(_DML.match(sql))
        reqs = []
        if dml and not self.in_txn:
            reqs.append(self._stmt("BEGIN"))
        reqs.append(self._stmt(sql, args))
        autocommit = not (self.in_txn or dml)
        results = self._pipeline(reqs, close=autocommit)
        if dml and not self.in_txn and results and results[0].get("type") == "ok":
            self.in_txn = True
        for res in results:
            if res.get("type") == "error":
                err = res.get("error", {})
                raise _map_error(err.get("message", "database error"), err.get("code", ""))
        return results[len(reqs) - 1]["response"]["result"]     # the statement itself (not the trailing "close")

    # -- DB-API --
    def cursor(self):
        return Cursor(self)

    def commit(self):
        if self.in_txn:
            try:
                results = self._pipeline([self._stmt("COMMIT")], close=True)
            finally:
                self.in_txn, self.baton = False, None
            for res in results:
                if res.get("type") == "error":
                    raise _map_error(res["error"].get("message", "commit failed"))

    def rollback(self):
        if self.in_txn:
            try:
                self._pipeline([self._stmt("ROLLBACK")], close=True)
            except Error:
                pass
            finally:
                self.in_txn, self.baton = False, None

    def close(self):
        self.rollback()
        self._http.close()


def connect(url=None, auth_token="", **kw):
    return Connection(url, auth_token)


# ---- SQLAlchemy dialect ----
class HranaDialect(SQLiteDialect):
    driver = "hrana"
    supports_statement_cache = True

    @classmethod
    def import_dbapi(cls):
        import database.hrana as mod
        return mod

    def create_connect_args(self, url):
        q = dict(url.query)
        scheme = q.get("scheme", "https")            # "http" is only used by the local test server
        host = url.host + (f":{url.port}" if url.port else "")
        return ([], {"url": f"{scheme}://{host}", "auth_token": q.get("authToken", "")})

    def get_isolation_level(self, dbapi_connection):
        return "SERIALIZABLE"

    def get_default_isolation_level(self, dbapi_conn):
        return "SERIALIZABLE"

    def do_ping(self, dbapi_connection):
        return True              # no cheap ping over HTTP; dead pooled sockets are handled by retries in _post


registry.register("sqlite.hrana", "database.hrana", "HranaDialect")