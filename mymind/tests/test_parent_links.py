"""Parent links: private, read-only family view (token + view password)."""
import re
from datetime import timedelta
import pytest
from database.db import Session
from database.models import AuditLog, ParentLink, User, utcnow
from conftest import Client, PW, subscribe_and_approve, ONB

VIEW_PW = "grandma-view-pw"


def create_link(c, label="Grandma", pw=VIEW_PW, duration="30"):
    r = c.post("/settings/parent-links", {"label": label, "password": pw, "duration": duration})
    m = re.search(r'value="https?://[^"/]+/p/([A-Za-z0-9_-]{30,64})"', r.get_data(as_text=True))
    return r, (m.group(1) if m else None)


def open_view(app, token, pw=VIEW_PW):
    v = Client(app)
    r = v.post(f"/p/{token}", {"password": pw})
    return v, r


def test_create_shows_link_once_and_stores_only_a_hash(app, ready):
    r, token = create_link(ready)
    assert r.status_code == 200 and token
    with app.app_context():
        l = Session.query(ParentLink).one()
        assert token not in (l.token_hash, l.password_hash, l.label) and len(l.token_hash) == 64
        assert l.password_hash.startswith("$argon2id$") and VIEW_PW not in l.password_hash
        assert l.expires_at is not None
        log = " ".join(f"{a.action} {a.detail}" for a in Session.query(AuditLog).all())
        assert "parent_link_created" in log and token not in log
    page = ready.get("/settings/parent-links").get_data(as_text=True)
    assert token not in page and "Grandma" in page and "active" in page


def test_family_member_needs_token_and_password_then_sees_read_only_world(app, ready):
    _, token = create_link(ready)
    anon = Client(app)
    g = anon.get(f"/p/{token}")
    assert g.status_code == 200 and "View password" in g.get_data(as_text=True)
    assert anon.get(f"/p/{token}/view").status_code == 302                       # no grant yet
    assert anon.post(f"/p/{token}", {"password": "wrong-password"}).status_code == 403
    assert anon.get(f"/p/{token}/view").status_code == 302
    ok = anon.post(f"/p/{token}", {"password": VIEW_PW})
    assert ok.status_code == 302 and ok.location.endswith(f"/p/{token}/view")
    v = anon.get(f"/p/{token}/view")
    html = v.get_data(as_text=True)
    assert v.status_code == 200 and "Sunny" in html and "read-only" in html
    assert "mum" not in html and "csrf_token\" value=\"" in html and "/subscription" not in html      # no account details or nav
    # a view password does not unlock the caregiver's account or any app page
    assert anon.get("/home").status_code == 302 and "/login" in anon.get("/home").location
    with app.app_context():
        l = Session.query(ParentLink).one()
        assert l.view_count == 1 and l.last_viewed_at is not None


def test_unknown_malformed_revoked_and_expired_links_look_identical(app, ready):
    _, token = create_link(ready)
    anon = Client(app)
    bodies = {anon.get("/p/not-a-real-token").get_data(as_text=True), anon.get("/p/" + "A" * 43).get_data(as_text=True)}
    assert len(bodies) == 1
    assert "link isn" in next(iter(bodies)) and "available" in next(iter(bodies))
    assert anon.get("/p/" + "A" * 43).status_code == 404 and anon.post("/p/" + "A" * 43, {"password": "x" * 9}).status_code == 404
    with app.app_context():                                                      # expiry
        l = Session.query(ParentLink).one(); l.expires_at = utcnow() - timedelta(minutes=1); Session.commit()
    assert anon.get(f"/p/{token}").status_code == 404


def test_revoking_cuts_off_an_open_session_immediately(app, ready):
    _, token = create_link(ready)
    viewer, _ = open_view(app, token)
    assert viewer.get(f"/p/{token}/view").status_code == 200
    with app.app_context():
        lid = Session.query(ParentLink).one().id
    assert ready.post(f"/settings/parent-links/{lid}/revoke").status_code == 302
    assert viewer.get(f"/p/{token}/view").status_code == 404
    assert Client(app).get(f"/p/{token}").status_code == 404
    assert "revoked" in ready.get("/settings/parent-links").get_data(as_text=True)


def test_five_wrong_passwords_lock_the_link_even_for_the_right_password(app, ready):
    _, token = create_link(ready)
    for i in range(4):
        assert Client(app).post(f"/p/{token}", {"password": f"wrong-pass-{i}"}).status_code in (403, 429)
    # a different "visitor" (fresh session) hits the same link: the count is per link, not per browser
    last = Client(app).post(f"/p/{token}", {"password": "wrong-pass-9"})
    assert last.status_code == 429
    assert Client(app).post(f"/p/{token}", {"password": VIEW_PW}).status_code == 429
    with app.app_context():
        l = Session.query(ParentLink).one(); l.locked_until = utcnow() - timedelta(seconds=1); Session.commit()
    assert Client(app).post(f"/p/{token}", {"password": VIEW_PW}).status_code == 302


def test_caregiver_side_is_private_to_the_owner(app, ready, admin):
    _, token = create_link(ready)
    with app.app_context():
        lid = Session.query(ParentLink).one().id
    other = Client(app); other.register("dad")
    subscribe_and_approve(app, other, admin, ref="TXN99999"); other.post("/onboarding", ONB)
    assert other.post(f"/settings/parent-links/{lid}/revoke").status_code == 404            # another account's link
    assert "<b>Grandma</b>" not in other.get("/settings/parent-links").get_data(as_text=True)
    assert Client(app).get("/settings/parent-links").status_code == 302                      # not logged in
    assert admin.get("/settings/parent-links").status_code in (302, 403)                     # admins have no child
    assert Client(app).post(f"/p/{token}/leave", {}).status_code == 302


def test_validation_limits_and_privacy_headers(app, ready):
    r, tok = create_link(ready, pw="short")
    assert tok is None and "at least 8" in r.get_data(as_text=True)
    assert create_link(ready, duration="forever")[1] is None
    tokens = [create_link(ready, label=f"L{i}")[1] for i in range(5)]
    assert all(tokens)
    r, tok = create_link(ready, label="one too many")
    assert tok is None and "up to 5" in r.get_data(as_text=True)
    anon = Client(app)
    h = anon.get(f"/p/{tokens[0]}").headers
    assert h["Cache-Control"] == "no-store" and "noindex" in h["X-Robots-Tag"] and h["Referrer-Policy"] == "no-referrer"
    assert anon.get("/p/nope").headers["Cache-Control"] == "no-store"
    assert "Disallow: /p/" in anon.get("/robots.txt").get_data(as_text=True)


def test_deleted_or_suspended_caregiver_closes_their_links(app, ready):
    _, token = create_link(ready)
    viewer, _ = open_view(app, token)
    with app.app_context():
        u = Session.query(User).filter_by(username="mum").one(); u.account_status = "suspended"; Session.commit()
    assert viewer.get(f"/p/{token}/view").status_code == 404 and Client(app).get(f"/p/{token}").status_code == 404


def test_account_deletion_erases_parent_links(app, ready, admin):
    _, token = create_link(ready)
    viewer, _ = open_view(app, token)
    ready.post("/settings/delete-request", {"confirm": "DELETE"})
    with app.app_context():
        uid = Session.query(User).filter_by(username="mum").one().id
    admin.post(f"/admin/users/{uid}/delete")
    with app.app_context():
        assert Session.query(ParentLink).count() == 0                      # the hashed token and view password are gone, not just disabled
    assert viewer.get(f"/p/{token}/view").status_code == 404 and Client(app).get(f"/p/{token}").status_code == 404
