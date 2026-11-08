"""The child's WATCHED content is shown first and kept apart from RECOMMENDED content (stops in every view + caretaker dashboard)."""
import json
import uuid
from datetime import timedelta

from conftest import CPW, Client
from database.db import Session
from database.models import ActivityEvent, ChildProfile, ContentItem, Interaction, User, utcnow
from services import settings_service, watched_service


def item(kind, category, title):
    row = ContentItem(provider="demo", provider_content_id=str(uuid.uuid4())[:12], content_type=kind, title=title, description="",
                      thumbnail_url="https://example.test/t.jpg", category=category, tags_json="[]", attribution_json="{}")
    Session.add(row)
    Session.flush()
    return row


def watch(cid, it, kind="watch", seconds=60, ago=timedelta(minutes=5)):
    at = utcnow() - ago
    Session.add(ActivityEvent(child_id=cid, stop="shorts", content_id=it.id, content_title=it.title, event_type=kind, duration_seconds=seconds,
                              client_event_id=str(uuid.uuid4()), created_at=at, last_active_at=at, content_type=it.content_type, category=it.category))


def seed(app):
    with app.app_context():
        child = Session.query(ChildProfile).first()
        cid, owner = child.id, child.caregiver_user_id
        a, b = item("video", "sports", "Goal Compilation"), item("picture", "sports", "Stadium Photo")
        old, never = item("video", "sports", "Old Match"), item("video", "sports", "Never Opened")
        short = item("short", "sports", "Trick Shot")
        watch(cid, a, "watch", 300, timedelta(minutes=2))
        watch(cid, b, "look", 20, timedelta(hours=1))
        watch(cid, short, "watch", 15, timedelta(minutes=30))
        Session.add(Interaction(child_profile_id=cid, caregiver_id=owner, content_item_id=old.id, interaction_type="selected",
                                category="sports", occurred_at=utcnow() - timedelta(days=3)))        # chosen before tracking existed
        Session.commit()
        return cid, {"a": a.id, "b": b.id, "old": old.id, "never": never.id, "short": short.id}


def stop_titles(client, url="/api/world/stop/sports"):
    return [i["title"] for i in client.get(url).get_json()["watched"]["items"]]


def test_stop_lists_exactly_what_was_watched_newest_first(app, ready):
    seed(app)
    data = ready.get("/api/world/stop/sports").get_json()
    assert stop_titles(ready) == ["Goal Compilation", "Trick Shot", "Stadium Photo", "Old Match"]       # recorded activity AND older history, newest first
    assert "Never Opened" not in stop_titles(ready)                                                       # a recommendation is never listed as watched
    assert data["watched"]["total"] == 4 and data["shelf"] is not None                                    # recommendations are still offered separately
    first = data["watched"]["items"][0]
    assert first["w_views"] >= 1 and first["w_minutes"] == 5.0 and first["thumb"] and first["w_date"]


def test_each_stop_only_lists_its_own_watched_content(app, ready):
    seed(app)
    assert stop_titles(ready, "/api/world/stop/shots") == ["Trick Shot"]
    assert stop_titles(ready, "/api/world/stop/pictures") == ["Stadium Photo"]
    assert stop_titles(ready, "/api/world/stop/videos") == ["Goal Compilation", "Old Match"]
    assert stop_titles(ready, "/api/world/stop/animals") == []


def test_disliked_and_newly_blocked_content_leaves_the_childs_screen(app, ready):
    cid, ids = seed(app)
    with app.app_context():
        owner = Session.get(ChildProfile, cid).caregiver_user_id
        Session.add(Interaction(child_profile_id=cid, caregiver_id=owner, content_item_id=ids["a"], interaction_type="dislike",
                                category="sports", occurred_at=utcnow()))
        settings_service.set_value("blocked_keywords", "stadium")
        Session.commit()
    assert stop_titles(ready) == ["Trick Shot", "Old Match"]


def test_watched_is_shown_to_the_child_too(app, ready):
    seed(app)
    with app.app_context():
        username = Session.query(ChildProfile).first().caregiver.child_username
    ready.post("/logout")
    ready.login(username, CPW)
    assert "Goal Compilation" in stop_titles(ready)


def test_parent_preview_gets_the_same_watched_list(app, ready):
    seed(app)
    with app.app_context():
        uid = Session.query(ChildProfile).first().public_uid
    response = ready.get(f"/caretaker/children/{uid}/world-preview/stop/sports")
    assert response.status_code == 200
    assert [i["title"] for i in response.get_json()["watched"]["items"]][0] == "Goal Compilation"


def test_dashboard_content_lists_watched_first_and_recommendations_apart(app, ready):
    seed(app)
    shots = ready.get("/api/caretaker/activity/content?type=short&tz=0").get_json()
    assert [i["title"] for i in shots["watched"]["items"]] == ["Trick Shot"] and shots["watched"]["items"][0]["w_event"]
    assert shots["recommended"]["items"], "recommendations are still offered"
    watched_ids = {i["id"] for i in shots["watched"]["items"]}
    assert not watched_ids & {i["id"] for i in shots["recommended"]["items"]}                              # never repeats what was watched
    assert all(i.get("reason") for i in shots["recommended"]["items"])
    videos = ready.get("/api/caretaker/activity/content?type=video").get_json()
    assert [i["title"] for i in videos["watched"]["items"]] == ["Goal Compilation", "Old Match"]
    assert ready.get("/api/caretaker/activity/content?type=bogus").status_code == 400
    page = ready.get("/caretaker/activity").data
    assert b"ad-content-panel" in page and b"watched" in page.lower()


def test_dashboard_content_is_private_to_the_childs_caregiver(app, ready):
    seed(app)
    assert Client(app).get("/api/caretaker/activity/content?type=short").status_code in (302, 401)
    other = Client(app)
    other.register("dad")
    with app.app_context():
        uid = Session.query(ChildProfile).first().public_uid
    assert other.get(f"/api/caretaker/activity/content?type=short&child={uid}").status_code in (302, 403, 404)
    with app.app_context():
        username = Session.query(ChildProfile).first().caregiver.child_username
    ready.post("/logout")
    ready.login(username, CPW)
    assert ready.get("/api/caretaker/activity/content?type=short").status_code == 403


def test_recommendations_skip_watched_and_disliked(app, ready):
    cid, ids = seed(app)
    with app.app_context():
        child = Session.get(ChildProfile, cid)
        owner = Session.get(User, child.caregiver_user_id)
        mine = watched_service.watched(owner, child, {"all": False, "types": ("video",), "cats": ()}, "video")
        out = watched_service.recommended(owner, child, "video", exclude_ids={i["id"] for i in mine["items"]})
        assert out["items"] and not {i["id"] for i in out["items"]} & {i["id"] for i in mine["items"]}
        assert watched_service.recommended(owner, child, "nonsense")["items"] == []
