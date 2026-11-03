"""A tiny local stand-in for Turso's Hrana-over-HTTP endpoint (backed by sqlite3) used to test database/hrana.py."""
import base64, itertools, sqlite3, threading
from flask import Flask, request, jsonify
from werkzeug.serving import make_server


def _arg(a):
    t = a.get("type")
    if t == "null": return None
    if t == "integer": return int(a["value"])
    if t == "float": return float(a["value"])
    if t == "blob": b = a["base64"]; return base64.b64decode(b + "=" * (-len(b) % 4))
    return a["value"]


def _cell(v):
    if v is None: return {"type": "null"}
    if isinstance(v, int): return {"type": "integer", "value": str(v)}
    if isinstance(v, float): return {"type": "float", "value": v}
    if isinstance(v, bytes): return {"type": "blob", "base64": base64.b64encode(v).decode()}
    return {"type": "text", "value": v}


class FakeTurso:
    def __init__(self, db_path, token="secret-token"):
        self.db_path, self.token, self.streams, self.ids = db_path, token, {}, itertools.count(1)
        self.lock = threading.Lock()
        app = Flask(__name__)

        @app.post("/v2/pipeline")
        def pipeline():
            if request.headers.get("Authorization") != f"Bearer {self.token}":
                return jsonify(error="unauthorized"), 401
            body = request.get_json()
            baton = body.get("baton")
            with self.lock:
                conn = self.streams.get(baton) if baton else None
                if baton and conn is None:
                    return jsonify(results=[{"type": "error", "error": {"message": "stream expired"}}]), 200
                if conn is None:
                    conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
                results, closed = [], False
                for r in body["requests"]:
                    if r["type"] == "close":
                        conn.close(); closed = True; results.append({"type": "ok", "response": {"type": "close"}}); continue
                    st = r["stmt"]
                    try:
                        cur = conn.execute(st["sql"], [_arg(a) for a in st.get("args", [])])
                        cols = [{"name": d[0], "decltype": None} for d in (cur.description or [])]
                        rows = [[_cell(v) for v in row] for row in cur.fetchall()] if cols else []
                        results.append({"type": "ok", "response": {"type": "execute", "result": {
                            "cols": cols, "rows": rows, "affected_row_count": max(cur.rowcount, 0) if not cols else 0,
                            "last_insert_rowid": str(cur.lastrowid) if cur.lastrowid else None}}})
                    except sqlite3.Error as exc:
                        code = "SQLITE_CONSTRAINT" if isinstance(exc, sqlite3.IntegrityError) else "SQLITE_ERROR"
                        results.append({"type": "error", "error": {"message": str(exc), "code": code}})
                new = None
                if not closed:
                    new = baton or f"b{next(self.ids)}"; self.streams[new] = conn
                elif baton:
                    self.streams.pop(baton, None)
                return jsonify(baton=new, base_url=None, results=results)

        self.server = make_server("127.0.0.1", 0, app, threaded=True)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"sqlite+hrana://127.0.0.1:{self.port}?scheme=http&authToken={self.token}"

    def stop(self):
        self.server.shutdown()