"""`flask sumsub-check`: the setup self-test an administrator runs against the Sumsub sandbox."""
import time
import email.utils
import pytest
import requests
from services import sumsub_service as sx


class _Head:
    def __init__(self, status=200, date=None):
        self.status_code = status
        self.headers = {"Date": email.utils.formatdate(date if date is not None else time.time(), usegmt=True)}


@pytest.fixture()
def keyed(app):
    app.config.update(SUMSUB_APP_TOKEN="sbx:tok-7a1f", SUMSUB_SECRET_KEY="Sk-9f2c41", SUMSUB_WEBHOOK_SECRET="hk-55d0e8", SUMSUB_LEVEL_NAME="basic-kyc-level")
    return app


def run(app):
    return app.test_cli_runner().invoke(args=["sumsub-check"])


def test_all_checks_pass_with_a_healthy_sandbox(keyed, monkeypatch):
    monkeypatch.setattr(requests, "head", lambda *a, **k: _Head())
    def fake_call(method, path, payload=None):
        if method == "GET":
            raise sx.SumsubError("rejected", "x", 404)                       # unknown test applicant = signature accepted
        return {"token": "_act-sbx-1"}
    monkeypatch.setattr(sx, "_call", fake_call)
    out = run(keyed)
    assert out.exit_code == 0, out.output
    assert out.output.count("[PASS]") >= 7 and "[FAIL]" not in out.output and "sandbox token" in out.output
    for leaked in ("_act-sbx-1", "tok-7a1f", "Sk-9f2c41", "hk-55d0e8"):                        # keys and tokens are never printed
        assert leaked not in out.output


def test_missing_keys_stop_early_with_guidance(app):
    out = run(app)
    assert out.exit_code != 0 and "[FAIL] SUMSUB_APP_TOKEN is set" in out.output and "Set the Sumsub keys first" in out.output


def test_bad_credentials_wrong_level_and_clock_skew_are_each_reported(keyed, monkeypatch):
    monkeypatch.setattr(requests, "head", lambda *a, **k: _Head(date=time.time() - 600))
    def fake_call(method, path, payload=None):
        if method == "GET":
            raise sx.SumsubError("auth", "x", 401)
        raise sx.SumsubError("rejected", "x", 404)
    monkeypatch.setattr(sx, "_call", fake_call)
    out = run(keyed)
    assert out.exit_code != 0
    assert "[FAIL] Server clock matches Sumsub's" in out.output
    assert "[FAIL] Signed request accepted" in out.output and "rejected the token/secret/signature" in out.output
    assert "[FAIL] Level exists" in out.output and "SUMSUB_LEVEL_NAME" in out.output


def test_unreachable_sumsub_and_missing_webhook_secret(keyed, monkeypatch):
    keyed.config["SUMSUB_WEBHOOK_SECRET"] = ""
    def boom(*a, **k): raise requests.ConnectionError("no route")
    monkeypatch.setattr(requests, "head", boom)
    monkeypatch.setattr(sx, "_call", lambda *a, **k: (_ for _ in ()).throw(sx.SumsubError("unreachable", "x")))
    out = run(keyed)
    assert out.exit_code != 0
    assert "[FAIL] Reach Sumsub" in out.output and "[FAIL] SUMSUB_WEBHOOK_SECRET is set" in out.output
    assert "[FAIL] Webhook signature check works" in out.output and "[FAIL] WebSDK script URL is reachable" in out.output
