"""Caretaker 18+ verification (Sumsub): age gate, signed requests, webhook authenticity, server-side gate, no personal data kept."""
import hashlib
import hmac
import json
from datetime import date, timedelta
import pytest
import requests
from database.db import Session
from database.models import AuditLog, Subscription, User
from services import sumsub_service as sx, settings_service
from conftest import Client, PW

APP_TOKEN, SECRET, HOOK = "sbx:apptoken", "shh-secret-key", "hook-secret"
ADULT_DOB = (date.today().replace(year=date.today().year - 30)).isoformat()
NAME, MAIL = "Amina Nakato", "amina@example.org"


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._b = status, body or {}
        self.text = json.dumps(self._b)

    def json(self):
        return self._b


class FakeSumsub:
    """Stands in for api.sumsub.com. Records every request so tests can inspect headers, paths and signed bytes."""
    def __init__(self):
        self.calls, self.created, self.raise_exc, self.status_override = [], set(), None, None
        self.applicant = {"id": "a1b2c3d4e5f6a7b8", "externalUserId": None, "review": {"reviewStatus": "init"}, "info": {}}

    def request(self, method, url, data=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "body": data or b"", "headers": headers or {}, "timeout": timeout})
        if self.raise_exc:
            raise self.raise_exc
        if self.status_override:
            return Resp(self.status_override, {"description": "x"})
        path = url.split("sumsub.com", 1)[1]
        if method == "POST" and path.startswith("/resources/applicants?levelName="):
            ext = json.loads(data)["externalUserId"]
            if ext in self.created:
                return Resp(409, {"description": "exists"})
            self.created.add(ext)
            self.applicant["externalUserId"] = ext
            return Resp(201, {"id": self.applicant["id"], "externalUserId": ext})
        if method == "POST" and path == "/resources/accessTokens/sdk":
            return Resp(200, {"token": "_act-sbx-token123", "userId": json.loads(data)["userId"]})
        if method == "GET" and path.endswith("/one"):
            return Resp(200, self.applicant)
        return Resp(404)

    def set_result(self, answer="GREEN", dob=ADULT_DOB, reject="FINAL", status="completed", ext=None):
        self.applicant["review"] = {"reviewStatus": status, "reviewResult": ({"reviewAnswer": answer, **({"reviewRejectType": reject} if answer == "RED" else {})})}
        self.applicant["info"] = {"dob": dob, "country": "UGA", "idDocs": [{"idDocType": "ID_CARD", "country": "UGA"}]} if dob else {"idDocs": []}
        if ext:
            self.applicant["externalUserId"] = ext


@pytest.fixture()
def sumsub(monkeypatch, app):
    f = FakeSumsub()
    monkeypatch.setattr(sx, "SESSION", f)
    app.config.update(ID_VERIFICATION="sumsub", SUMSUB_APP_TOKEN=APP_TOKEN, SUMSUB_SECRET_KEY=SECRET, SUMSUB_WEBHOOK_SECRET=HOOK, SUMSUB_LEVEL_NAME="basic-kyc-level")
    return f


def caretaker(app, name="mum"):
    c = Client(app)
    c.register(name)
    return c


def body(**kw):
    d = {"full_name": NAME, "email": MAIL, "dob": ADULT_DOB, "consent": True}
    d.update(kw)
    return d


def start(c, **kw):
    return c.jpost("/verify/start", body(**kw))


def uid(app, name="mum"):
    with app.app_context():
        return Session.query(User).filter_by(username=name).one().id


def hook(c, payload, secret=HOOK, alg="HMAC_SHA256_HEX", digest=None):
    raw = json.dumps(payload).encode()
    h = {"X-Payload-Digest-Alg": alg}
    if digest is not False:
        h["X-Payload-Digest"] = digest or hmac.new(secret.encode(), raw, {"HMAC_SHA256_HEX": hashlib.sha256, "HMAC_SHA512_HEX": hashlib.sha512, "HMAC_SHA1_HEX": hashlib.sha1}.get(alg, hashlib.sha256)).hexdigest()
    return c.c.post("/verify/webhook", data=raw, headers=h, content_type="application/json")


def reviewed(app, name="mum"):
    return {"type": "applicantReviewed", "applicantId": "a1b2c3d4e5f6a7b8", "externalUserId": f"mymind-{uid(app, name)}", "reviewStatus": "completed"}


# ---------------------------------------------------------------- age arithmetic (to the day)
@pytest.mark.parametrize("dob,today,age", [
    ("2008-06-15", "2026-06-15", 18), ("2008-06-16", "2026-06-15", 17), ("2008-06-14", "2026-06-15", 18),
    ("2000-02-29", "2026-02-28", 25), ("2000-02-29", "2026-03-01", 26), ("2008-02-29", "2026-02-28", 17), ("2008-02-29", "2026-03-01", 18),
    ("1990-12-31", "2026-01-01", 35), ("2026-01-01", "2026-01-01", 0)])
def test_age_is_exact_to_the_day(dob, today, age):
    assert sx.age_on(date.fromisoformat(dob), date.fromisoformat(today)) == age
    assert sx.is_adult(date.fromisoformat(dob), date.fromisoformat(today)) == (age >= 18)


@pytest.mark.parametrize("bad", ["", None, 5, "15/06/1990", "1990-6-5", "1990-13-01", "1990-02-30", "2999-01-01", "1800-01-01", "abc", "1990-06-15; DROP"])
def test_bad_dates_are_refused(bad):
    with pytest.raises(sx.FormError):
        sx.parse_dob(bad)


def test_person_validation():
    assert sx.clean_person("  Amina   Nakato ", " a@b.co ") == ("Amina Nakato", "a@b.co")
    for n, m in (("", MAIL), ("A", MAIL), ("<b>x</b>", MAIL), (NAME, "nope"), (NAME, "a@b"), (None, None), (NAME, "x" * 300 + "@a.com")):
        with pytest.raises(sx.FormError):
            sx.clean_person(n, m)


# ---------------------------------------------------------------- request signing
def test_signature_is_hmac_sha256_over_exactly_the_bytes_sent(app, sumsub):
    c = caretaker(app)
    assert start(c).status_code == 200
    for call in sumsub.calls:
        h = call["headers"]
        path = call["url"].split("sumsub.com", 1)[1]
        expect = hmac.new(SECRET.encode(), h["X-App-Access-Ts"].encode() + call["method"].encode() + path.encode() + call["body"], hashlib.sha256).hexdigest()
        assert h["X-App-Access-Sig"] == expect and h["X-App-Token"] == APP_TOKEN
        assert abs(int(h["X-App-Access-Ts"]) - __import__("time").time()) < 5
        assert call["timeout"] == sx.TIMEOUT and call["url"].startswith("https://")
    assert sx.sign("k", 1607551635, "post", "/a?b=1", b"{}") == hmac.new(b"k", b"1607551635POST/a?b=1{}", hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- the age gate and the happy path
def test_under_18_is_blocked_before_any_provider_call_with_a_supportive_message(app, sumsub):
    c = caretaker(app)
    teen = (date.today() - timedelta(days=17 * 365 + 100)).isoformat()
    r = start(c, dob=teen)
    d = r.get_json()
    assert r.status_code == 403 and d["error"] == "underage" and d["title"] == "Access denied"
    assert "18" in d["message"] and "ask a parent" in d["message"].lower()
    assert sumsub.calls == []                                                          # Sumsub was never contacted
    with app.app_context():
        assert Session.get(User, uid(app)).is_adult_verified is False
        assert any(a.action == "id_age_gate_declined" and "under18" in a.detail for a in Session.query(AuditLog))
        assert all(teen not in (a.detail or "") for a in Session.query(AuditLog))      # no date of birth in the log


def test_turning_18_today_passes_and_the_day_before_does_not(app, sumsub):
    c = caretaker(app)
    t = date.today()
    eighteen_today = date(t.year - 18, t.month, t.day) if not (t.month == 2 and t.day == 29) else date(t.year - 18, 2, 28)
    assert start(c, dob=(eighteen_today + timedelta(days=1)).isoformat()).status_code == 403
    assert start(c, dob=eighteen_today.isoformat()).status_code == 200


def test_repeated_under_18_declarations_pause_verification(app, sumsub):
    c = caretaker(app)
    teen = (date.today() - timedelta(days=10 * 365)).isoformat()
    for _ in range(3):
        assert start(c, dob=teen).status_code == 403
    r = start(c, dob=ADULT_DOB)                                                        # "try another birthday" no longer works
    assert r.status_code == 403 and r.get_json()["error"] == "blocked" and sumsub.calls == []


def test_valid_start_creates_applicant_then_token_and_returns_only_the_token(app, sumsub):
    c = caretaker(app)
    r = start(c)
    d = r.get_json()
    assert r.status_code == 200 and d == {"mode": "sumsub", "token": "_act-sbx-token123", "ttl": 600}
    raw = r.get_data(as_text=True)
    assert SECRET not in raw and APP_TOKEN not in raw
    a, t = sumsub.calls
    assert a["url"].endswith("/resources/applicants?levelName=basic-kyc-level")
    ab = json.loads(a["body"])
    assert ab["externalUserId"] == f"mymind-{uid(app)}" and ab["email"] == MAIL and ab["fixedInfo"]["dob"] == ADULT_DOB
    assert t["url"].endswith("/resources/accessTokens/sdk") and json.loads(t["body"]) == {"userId": f"mymind-{uid(app)}", "levelName": "basic-kyc-level", "ttlInSecs": 600}
    assert c.jpost("/verify/token", {}).get_json()["token"] == "_act-sbx-token123"


def test_nothing_personal_is_stored(app, sumsub):
    c = caretaker(app)
    start(c)
    with app.app_context():
        u = Session.get(User, uid(app))
        dump = json.dumps({k: str(v) for k, v in u.__dict__.items() if not k.startswith("_")}) + json.dumps([[a.action, a.detail] for a in Session.query(AuditLog)])
        for secret in (NAME, "Amina", "Nakato", MAIL, ADULT_DOB):
            assert secret not in dump
        assert u.sumsub_applicant_id == "a1b2c3d4e5f6a7b8" and u.id_verification_status == "pending"


def test_existing_applicant_is_reused(app, sumsub):
    c = caretaker(app)
    assert start(c).status_code == 200
    assert start(c).status_code == 200                                                 # second start hits 409 and carries on
    assert any(x["url"].endswith("/one") for x in sumsub.calls)


# ---------------------------------------------------------------- robustness
@pytest.mark.parametrize("payload", [None, [], "x", {}, {"full_name": NAME}, {"full_name": NAME, "email": MAIL}])
def test_missing_or_malformed_payloads_are_refused(app, sumsub, payload):
    c = caretaker(app)
    r = c.c.post("/verify/start", json=payload, headers={"X-CSRFToken": c.token()}) if payload is not None else c.c.post("/verify/start", data="not json", headers={"X-CSRFToken": c.token()}, content_type="text/plain")
    assert r.status_code == 400 and sumsub.calls == []


@pytest.mark.parametrize("kw", [{"dob": "not-a-date"}, {"dob": "1990-02-30"}, {"dob": "2999-01-01"}, {"email": "bad"}, {"full_name": ""}, {"consent": False}])
def test_invalid_fields_give_friendly_errors(app, sumsub, kw):
    c = caretaker(app)
    r = start(c, **kw)
    assert r.status_code == 400 and r.get_json()["message"] and sumsub.calls == []


def test_start_needs_csrf_and_login(app, sumsub):
    anon = Client(app)
    assert anon.c.post("/verify/start", json=body()).status_code in (302, 400)
    c = caretaker(app)
    assert c.c.post("/verify/start", json=body()).status_code in (302, 400)            # no CSRF header


def test_timeout_unreachable_and_bad_keys_are_handled_without_leaking(app, sumsub):
    c = caretaker(app)
    sumsub.raise_exc = requests.Timeout()
    r = start(c)
    assert r.status_code == 504 and "too long" in r.get_json()["message"]
    sumsub.raise_exc = requests.ConnectionError("boom " + SECRET)
    r = start(c)
    assert r.status_code == 502 and SECRET not in r.get_data(as_text=True)
    sumsub.raise_exc, sumsub.status_override = None, 401
    r = start(c)
    assert r.status_code == 502 and "temporarily unavailable" in r.get_json()["message"] and SECRET not in r.get_data(as_text=True)
    sumsub.status_override = 503
    assert start(c).status_code == 502


def test_missing_credentials_report_a_setup_problem_not_a_crash(app, monkeypatch):
    f = FakeSumsub(); monkeypatch.setattr(sx, "SESSION", f)
    app.config.update(ID_VERIFICATION="sumsub", SUMSUB_APP_TOKEN="", SUMSUB_SECRET_KEY="")
    c = caretaker(app)
    r = start(c)
    assert r.status_code == 502 and "isn't set up" in r.get_json()["message"] and f.calls == []


def test_start_is_rate_limited(app, sumsub):
    c = caretaker(app)
    codes = [start(c, email="bad").status_code for _ in range(10)]
    assert 429 in codes


# ---------------------------------------------------------------- the server-side gate
def test_unverified_caretakers_are_locked_out_everywhere_but_data_rights(app, sumsub):
    c = caretaker(app)
    assert c.get("/verify/").status_code == 200
    for url in ("/home", "/subscription/", "/onboarding", "/world", "/pictures", "/journey", "/settings", "/music", "/updates"):
        r = c.get(url)
        assert r.status_code == 302 and "/verify" in r.location, url
    assert c.get("/api/pictures").status_code == 403 and c.get("/api/feed").status_code == 403
    assert c.get("/settings/export").status_code == 200                               # data rights stay available
    assert c.get("/").location.endswith("/verify/")


def test_registration_goes_to_verification_and_does_not_burn_the_trial(app, sumsub):
    with app.app_context():
        settings_service.set_value("trial_days", "30"); Session.commit()
    c = Client(app)
    r = c.register("newmum")
    assert r.status_code == 302 and "/verify" in r.location
    with app.app_context():
        assert Session.query(Subscription).count() == 0                               # trial not started yet


def test_verified_caretaker_continues_and_admin_is_never_gated(app, sumsub, admin):
    assert admin.get("/admin/").status_code == 200
    c = caretaker(app)
    with app.app_context():
        u = Session.get(User, uid(app)); u.is_adult_verified = True; Session.commit()
    assert c.get("/subscription/").status_code == 200 and c.get("/verify/").status_code == 302


def test_gate_is_off_when_verification_is_off(app):
    c = caretaker(app)
    assert c.get("/subscription/").status_code == 200 and c.get("/verify/").status_code == 302


# ---------------------------------------------------------------- webhook: authenticity first, then Sumsub is asked directly
def test_webhook_rejects_unsigned_wrongly_signed_and_legacy_sha1(app, sumsub):
    c = caretaker(app); start(c)
    p = reviewed(app); sumsub.set_result()
    anon = Client(app)
    assert hook(anon, p, digest=False).status_code == 401
    assert hook(anon, p, digest="0" * 64).status_code == 401
    assert hook(anon, p, secret="wrong").status_code == 401
    assert hook(anon, p, alg="HMAC_SHA1_HEX").status_code == 401
    assert hook(anon, p, alg="WHATEVER").status_code == 401
    with app.app_context():
        assert Session.get(User, uid(app)).is_adult_verified is False


def test_green_webhook_with_an_adult_document_verifies_and_starts_the_trial(app, sumsub):
    with app.app_context():
        settings_service.set_value("trial_days", "30"); Session.commit()
    c = caretaker(app); start(c)
    sumsub.set_result("GREEN", ADULT_DOB, ext=f"mymind-{uid(app)}")
    r = hook(Client(app), reviewed(app))                                               # no cookie, no CSRF token: signature only
    assert r.status_code == 200
    with app.app_context():
        u = Session.get(User, uid(app))
        assert u.is_adult_verified and u.id_verification_status == "verified" and u.verified_country == "UGA" and u.verified_document_type == "ID_CARD" and u.verified_at
        assert Session.query(Subscription).filter_by(user_id=u.id).count() == 1        # trial begins now
        assert any(a.action == "id_verified" and a.detail == "country=UGA" for a in Session.query(AuditLog))
    assert hook(Client(app), reviewed(app)).status_code == 200                         # replay is harmless
    with app.app_context():
        assert Session.query(Subscription).filter_by(user_id=uid(app)).count() == 1
    assert c.get("/subscription/").status_code == 200                                  # and the doors open


def test_the_document_date_of_birth_decides_not_what_was_typed(app, sumsub):
    c = caretaker(app); start(c)                                                       # typed an adult birthday...
    minor = (date.today() - timedelta(days=15 * 365)).isoformat()
    sumsub.set_result("GREEN", minor, ext=f"mymind-{uid(app)}")                       # ...but the document says 15
    assert hook(Client(app), reviewed(app)).status_code == 200
    with app.app_context():
        u = Session.get(User, uid(app))
        assert u.is_adult_verified is False and u.id_verification_status == "blocked" and u.verify_blocked_until
    assert c.get("/subscription/").status_code == 302


def test_forged_or_mismatched_webhooks_cannot_verify_anyone(app, sumsub):
    c = caretaker(app); start(c)
    sumsub.set_result("GREEN", ADULT_DOB, ext="mymind-9999")                          # Sumsub's record belongs to someone else
    assert hook(Client(app), reviewed(app)).status_code == 200
    with app.app_context():
        assert Session.get(User, uid(app)).is_adult_verified is False
    sumsub.set_result("RED", ADULT_DOB, ext=f"mymind-{uid(app)}")                     # payload claims GREEN-ish, Sumsub says RED
    forged = {**reviewed(app), "reviewResult": {"reviewAnswer": "GREEN"}}
    hook(Client(app), forged)
    with app.app_context():
        assert Session.get(User, uid(app)).is_adult_verified is False
    assert hook(Client(app), {**reviewed(app), "externalUserId": "mymind-424242"}).status_code == 200   # unknown user acknowledged


@pytest.mark.parametrize("answer,reject,dob,expect", [("GREEN", None, None, "pending"), ("RED", "FINAL", ADULT_DOB, "rejected"), ("RED", "RETRY", ADULT_DOB, "retry")])
def test_other_outcomes(app, sumsub, answer, reject, dob, expect):
    c = caretaker(app); start(c)
    sumsub.set_result(answer, dob, reject or "FINAL", ext=f"mymind-{uid(app)}")
    hook(Client(app), reviewed(app))
    with app.app_context():
        u = Session.get(User, uid(app))
        assert u.id_verification_status == expect and u.is_adult_verified is False     # approved-without-DOB is never auto-verified


def test_non_review_events_are_ignored_and_status_polling_settles_a_missed_webhook(app, sumsub):
    c = caretaker(app); start(c)
    assert hook(Client(app), {"type": "applicantCreated", "externalUserId": f"mymind-{uid(app)}"}).status_code == 200
    assert c.get("/verify/status").get_json()["state"] == "pending"
    sumsub.set_result("GREEN", ADULT_DOB, ext=f"mymind-{uid(app)}")
    from services import cache; cache.cache_clear(); cache.rate_reset()
    d = c.get("/verify/status").get_json()
    assert d["state"] == "verified" and d["next"]


# ---------------------------------------------------------------- demo mode
def test_demo_mode_works_in_development_only(app, tmp_path):
    app.config["ID_VERIFICATION"] = "demo"
    c = caretaker(app)
    assert start(c).get_json() == {"mode": "demo"}
    assert c.jpost("/verify/demo-confirm", {}).status_code == 200
    from app import create_app
    with pytest.raises(RuntimeError):
        create_app({"TESTING": True, "DATABASE_URL": f"sqlite:///{tmp_path}/p.db", "SECRET_KEY": "x" * 40, "PRODUCTION": True, "ID_VERIFICATION": "demo"})


def test_demo_confirm_is_unavailable_otherwise(app, sumsub):
    c = caretaker(app)
    assert c.jpost("/verify/demo-confirm", {}).status_code == 404


def test_page_renders_with_expected_form_and_csp_for_the_sdk_only_here(app, sumsub):
    c = caretaker(app)
    r = c.get("/verify/")
    html = r.get_data(as_text=True)
    for needle in ('id="vf-name"', 'id="vf-email"', 'type="date"', 'id="vf-consent"', "sumsub-websdk-container", "js/verify.js"):
        assert needle in html
    assert "static.sumsub.com" in r.headers["Content-Security-Policy"]
    assert "static.sumsub.com" not in c.get("/privacy").headers["Content-Security-Policy"]
    assert "unsafe-inline" not in r.headers["Content-Security-Policy"].split("script-src")[1].split(";")[0]
