import time
from conftest import Client, PW, subscribe_and_approve
from database.db import Session
from database.models import AuditLog

RICH = {"consent": "yes", "display_name": "Sunny", "avatar": "smile", "activities": ["dance", "music", "toys"],
        "interests": ["animals", "music"], "communication": ["words", "pointing"], "routine": ["morning", "play", "rest"]}
ANS = {"activities": ["dance", "music", "toys"], "interests": ["animals", "music"], "communication": ["words", "pointing"],
       "routine": ["morning", "play", "rest"], "nickname": "Sunny"}


def make_user(app, admin, name="mum", onboarding=None):
    c = Client(app); c.register(name)
    subscribe_and_approve(app, c, admin, ref=f"REF{name.upper()}99")
    c.post("/onboarding", onboarding or RICH)
    c.post("/logout")
    return c


def attempt(c, username, answers):
    r = c.post("/recover", {"username": username})
    assert r.status_code in (200, 429)
    if r.status_code == 429:
        return r
    return c.post("/recover/verify", answers)


def test_correct_answers_allow_password_reset(app, admin):
    c = make_user(app, admin)
    r = attempt(c, "mum", ANS)
    assert r.status_code == 302 and "/recover/reset" in r.location
    assert c.post("/recover/reset", {"password": "short", "confirm": "short"}).status_code == 400   # still validated
    r = c.post("/recover/reset", {"password": "BrandNew#Pass99", "confirm": "BrandNew#Pass99"})
    assert r.status_code == 302 and "/login" in r.location
    assert c.login("mum", PW).status_code == 401
    assert c.login("mum", "BrandNew#Pass99").status_code == 302
    with app.app_context():
        assert Session.query(AuditLog).filter_by(action="password_reset_self").count() == 1


def test_eighty_percent_threshold(app, admin):
    c = make_user(app, admin)
    ok = dict(ANS, nickname="Totally wrong")                        # 4 of 5 right = 80 %  -> passes
    assert attempt(c, "mum", ok).status_code == 302
    c2 = Client(app)
    bad = dict(ANS, nickname="Nope", routine=["meals"])             # 3 of 5 right = 60 %  -> fails
    r = attempt(c2, "mum", bad)
    assert r.status_code == 403 and b"verify your answers" in r.data and b"Refill the form" in r.data


def test_partial_overlap_scores_fractionally(app, admin):
    c = make_user(app, admin)
    near = dict(ANS, activities=["dance", "music", "toys", "art"])  # Jaccard 3/4 -> average 0.95
    assert attempt(c, "mum", near).status_code == 302


def test_unknown_user_looks_identical_and_always_fails(app, admin):
    make_user(app, admin)
    c = Client(app)
    real = c.post("/recover", {"username": "mum"}).data
    ghost = Client(app).post("/recover", {"username": "nobody_here"}).data
    for page in (real, ghost):
        assert b"Verify it" in page and b"daily routine" in page
    r = attempt(Client(app), "nobody_here", ANS)
    assert r.status_code == 403


def test_admin_account_cannot_use_self_recovery(app, admin):
    assert attempt(Client(app), "boss", ANS).status_code == 403


def test_lockout_after_three_failures(app, admin):
    c = make_user(app, admin)
    for _ in range(3):
        assert attempt(c, "mum", {"nickname": "x"}).status_code == 403
    r = c.post("/recover", {"username": "mum"})
    assert r.status_code == 429 and b"Too many attempts" in r.data and b"WhatsApp" in r.data
    # even the right answers can't be used while locked
    assert attempt(c, "mum", ANS).status_code == 429


def test_reset_page_needs_verification_and_expires(app, admin):
    c = make_user(app, admin)
    assert "/recover" in c.get("/recover/reset").location            # no token -> bounced
    attempt(c, "mum", ANS)
    with c.c.session_transaction() as s:
        s["rec_ok"] = dict(s["rec_ok"], ts=time.time() - 3600)         # expired token
    assert "/recover" in c.get("/recover/reset").location
    assert "/recover" in c.post("/recover/reset", {"password": "BrandNew#Pass99", "confirm": "BrandNew#Pass99"}).location


def test_sparse_questionnaire_cannot_self_recover(app, admin):
    c = make_user(app, admin, "thin", onboarding={"consent": "yes", "display_name": "Sunny", "interests": ["animals"]})
    assert attempt(c, "thin", {"interests": ["animals"], "nickname": "Sunny"}).status_code == 403


def test_token_is_single_use(app, admin):
    c = make_user(app, admin)
    attempt(c, "mum", ANS)
    c.post("/recover/reset", {"password": "BrandNew#Pass99", "confirm": "BrandNew#Pass99"})
    assert "/recover" in c.get("/recover/reset").location


def test_recover_pages_render(client):
    assert client.get("/recover").status_code == 200
    assert b"Forgot password?" in client.get("/login").data
