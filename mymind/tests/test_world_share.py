import re
from datetime import timedelta

from database.db import Session
from database.models import ActivityEvent, ChildProfile, WorldShareLink, utcnow
from conftest import Client, ONB, subscribe_and_approve


def create_world_link(client, expiry="7d"):
    created = client.post("/caretaker/share-links", {"expiry": expiry})
    assert created.status_code == 302
    response = client.get("/caretaker")
    html = response.get_data(as_text=True)
    match = re.search(r"/world/share/([A-Za-z0-9_-]{30,64})", html)
    return response, match.group(1) if match else None


def test_share_link_stores_only_hash_and_preview_does_not_log_activity(ready, app):
    response, token = create_world_link(ready)
    assert response.status_code == 200 and token
    with app.app_context():
        link = Session.query(WorldShareLink).one()
        assert token not in link.token_hash and len(link.token_hash) == 64
        before = Session.query(ActivityEvent).count()

    viewer = Client(app)
    page = viewer.get(f"/world/share/{token}")
    html = page.get_data(as_text=True)
    assert page.status_code == 200 and "You're viewing Sunny's world" in html
    assert 'data-read-only="1"' in html and "data-mode=\"preview\"" in html
    assert page.headers["Cache-Control"] == "no-store"
    assert page.headers["Referrer-Policy"] == "no-referrer"
    assert "mum" not in html and "/subscription" not in html
    assert viewer.get(f"/world/share/{token}/stop/home").status_code == 200
    with app.app_context():
        assert Session.query(ActivityEvent).count() == before
        assert Session.query(WorldShareLink).one().last_opened_at is not None


def test_share_expiry_revoke_and_owner_scope(ready, client, app, admin):
    _, token = create_world_link(ready)
    with app.app_context():
        link = Session.query(WorldShareLink).one()
        link.expires_at = utcnow() - timedelta(seconds=1)
        Session.commit()
    assert Client(app).get(f"/world/share/{token}").status_code == 404

    with app.app_context():
        link = Session.query(WorldShareLink).one()
        link.expires_at = None
        link.revoked_at = None
        link_id = link.id
        Session.commit()
    other = Client(app)
    other.register("othercaregiver")
    subscribe_and_approve(app, other, admin, ref="SHARE999")
    other.post("/onboarding", ONB)
    other_result = other.post(f"/caretaker/share-links/{link_id}/revoke")
    assert other_result.status_code == 404, other_result.location
    assert client.post(f"/caretaker/share-links/{link_id}/revoke").status_code == 302
    assert Client(app).get(f"/world/share/{token}").status_code == 404


def test_invalid_share_tokens_are_generic_and_rate_limited(ready, app):
    _, token = create_world_link(ready)
    visitor = Client(app)
    invalid = visitor.get("/world/share/not-a-token")
    assert invalid.status_code == 404
    assert "expired or was revoked" in invalid.get_data(as_text=True)
    assert visitor.get(f"/world/share/{token}/stop/not-a-stop").status_code == 404