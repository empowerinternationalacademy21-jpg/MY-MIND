"""`flask ai3d-check`: provider keys, balances, model names, storage and optimiser, without creating anything."""
import pytest
import requests


class _R:
    def __init__(self, status=200, body=None):
        self.status_code, self._b = status, body if body is not None else {}

    def json(self):
        return self._b


@pytest.fixture()
def keyed(app, monkeypatch):
    app.config.update(MESHY_API_KEY="mk-SECRET-1", TRIPO_API_KEY="tk-SECRET-2", OPENAI_API_KEY="ok-SECRET-3", CONCEPT_PROVIDER="openai", OPENAI_IMAGE_MODEL="img-model-x")
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/gltf-transform" if n == "gltf-transform" else None)
    return app


def run(app):
    return app.test_cli_runner().invoke(args=["ai3d-check"])


def fake_get(routes):
    def get(url, headers=None, timeout=None):
        for frag, resp in routes.items():
            if frag in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        return _R(404)
    return get


def test_all_green(keyed, monkeypatch):
    monkeypatch.setattr(requests, "get", fake_get({"meshy.ai": _R(200, {"balance": 420}), "tripo3d": _R(200, {"code": 0, "data": {"balance": 99.5}}),
                                                   "openai.com": _R(200, {"data": [{"id": "img-model-x"}, {"id": "other"}]})}))
    out = run(keyed)
    assert out.exit_code == 0, out.output
    assert "[PASS] Meshy key: key accepted, balance 420" in out.output and "balance 99.5" in out.output and "image model 'img-model-x' is available" in out.output
    assert "[PASS] World Library storage is writable" in out.output and "[PASS] Model optimiser" in out.output and "ONE test job per provider" in out.output
    for secret in ("mk-SECRET-1", "tk-SECRET-2", "ok-SECRET-3"):
        assert secret not in out.output


def test_each_failure_mode_is_reported_distinctly(keyed, monkeypatch):
    monkeypatch.setattr(requests, "get", fake_get({"meshy.ai": _R(401), "tripo3d": _R(500), "openai.com": _R(200, {"data": [{"id": "something-else"}]})}))
    out = run(keyed)
    assert out.exit_code != 0
    assert "[FAIL] Meshy key: the key was rejected (HTTP 401)" in out.output
    assert "[FAIL] Tripo key: HTTP 500: the endpoint or base URL may differ" in out.output
    assert "is NOT available to this key" in out.output and "3 check(s) failed" in out.output


def test_network_errors_and_skips(app, monkeypatch):
    app.config.update(MESHY_API_KEY="mk", TRIPO_API_KEY="", OPENAI_API_KEY="", STABILITY_API_KEY="", CONCEPT_PROVIDER="stability")
    monkeypatch.setattr(requests, "get", fake_get({"meshy.ai": requests.ConnectionError("down")}))
    monkeypatch.setattr("shutil.which", lambda n: None)
    out = run(app)
    assert "[FAIL] Meshy key: could not reach the provider (ConnectionError)" in out.output
    assert "[SKIP] Tripo" in out.output and "[SKIP] Concept images" in out.output and "[WARN] Model optimiser" in out.output


def test_unwritable_storage_is_a_failure(keyed, monkeypatch, tmp_path):
    f = tmp_path / "a-file"; f.write_text("x")
    keyed.config["AI3D_PRIVATE_DIR"] = str(f / "sub")                                   # a path under a regular file can't be created
    monkeypatch.setattr(requests, "get", fake_get({"meshy.ai": _R(200), "tripo3d": _R(200), "openai.com": _R(200, {"data": [{"id": "img-model-x"}]})}))
    out = run(keyed)
    assert out.exit_code != 0 and "[FAIL] Private 3D storage is writable" in out.output
