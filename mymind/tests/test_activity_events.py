import uuid

from conftest import CPW, Client
from database.db import Session
from database.models import ActivityEvent, ChildProfile, utcnow
from services import activity_service


def event_id():
    return str(uuid.uuid4())


def login_as_child(app, client):
    with app.app_context():
        child = Session.query(ChildProfile).one()
        username = child.caregiver.child_username
    client.post("/logout")
    assert client.login(username, CPW).status_code == 302
    return client


def test_activity_batch_is_idempotent_and_aggregates(app, ready):
    login_as_child(app, ready)
    item = ready.get("/api/videos").get_json()["items"][0]
    view_id, watch_id, favorite_id = event_id(), event_id(), event_id()
    assert ready.jpost("/api/activity-events", {"events": [
        {"event_id": view_id, "event_type": "view", "stop": "videos", "duration_seconds": 90},
        {"event_id": watch_id, "event_type": "watch", "stop": "videos",
         "content_id": item["id"], "duration_seconds": 15},
        {"event_id": favorite_id, "event_type": "favorite", "stop": "videos",
         "content_id": item["id"], "duration_seconds": 0},
    ]}).status_code == 200
    assert ready.jpost("/api/activity-events", {"events": [
        {"event_id": watch_id, "event_type": "watch", "stop": "videos",
         "content_id": item["id"], "duration_seconds": 30},
    ]}).get_json()["accepted"] == 1

    with app.app_context():
        child = Session.query(ChildProfile).one()
        events = Session.query(ActivityEvent).filter_by(child_id=child.id).all()
        watch = next(row for row in events if row.event_type == "watch")
        assert len(events) == 3
        assert watch.duration_seconds == 30
        assert watch.content_title == item["title"]
        assert activity_service.minutes_per_stop(child.id)["videos"] == 1.5
        assert activity_service.minutes_per_stop_by_day(child.id)[0]["minutes"] == 1.5
        assert activity_service.minutes_per_stop_by_week(child.id)[0]["stop"] == "videos"
        assert activity_service.minutes_per_stop_by_month(child.id)[0]["period"] == utcnow().strftime("%Y-%m")
        assert activity_service.top_stops(child.id) == [("videos", 1.5)]
        assert activity_service.videos_watched_count(child.id) == 1
        assert activity_service.favorites_added_count(child.id) == 1
        assert activity_service.daily_streak(child.id, today=utcnow().date()) == 1
        active = activity_service.first_last_active_per_day(child.id)
        assert active[0]["date"] == utcnow().date().isoformat()
        assert active[0]["first_active_at"] <= active[0]["last_active_at"]


def test_activity_batch_rejects_invalid_events(app, ready):
    login_as_child(app, ready)
    invalid = {"event_id": event_id(), "event_type": "view", "stop": "unknown-stop"}
    assert ready.jpost("/api/activity-events", {"events": [invalid]}).status_code == 400
    assert ready.jpost("/api/activity-events", {"events": [
        {"event_id": event_id(), "event_type": "search", "stop": "home"},
        {"event_id": event_id(), "event_type": "search", "stop": "home"},
    ]}).status_code == 200
    with app.app_context():
        assert Session.query(ActivityEvent).count() == 2


def test_child_page_render_and_read_only_visitor_do_not_write_activity(app, ready):
    assert ready.get("/world").status_code == 200
    with app.app_context():
        assert Session.query(ActivityEvent).count() == 0

    visitor = Client(app)
    response = visitor.jpost("/api/activity-events", {"events": [
        {"event_id": event_id(), "event_type": "view", "stop": "home"},
    ]})
    assert response.status_code == 401
    with app.app_context():
        assert Session.query(ActivityEvent).count() == 0


def test_my_journey_clear_removes_activity_events(app, ready):
    login_as_child(app, ready)
    ready.jpost("/api/activity-events", {"events": [
        {"event_id": event_id(), "event_type": "view", "stop": "home"},
    ]})
    ready.post("/logout")
    ready.login("mum")
    ready.post("/journey/clear", {"scope": "all"})
    with app.app_context():
        assert Session.query(ActivityEvent).count() == 0


def test_family_export_and_deletion_include_activity_events(app, ready):
    login_as_child(app, ready)
    ready.jpost("/api/activity-events", {"events": [
        {"event_id": event_id(), "event_type": "view", "stop": "home", "duration_seconds": 30},
    ]})
    ready.post("/logout")
    ready.login("mum")
    from database.models import User
    from services import account_service
    with app.app_context():
        user = Session.query(User).filter_by(username="mum").one()
        exported = account_service.export_user(user)
        assert exported["child_username"] == user.child_username
        assert exported["activity_events"][0]["duration_seconds"] == 30
        account_service.delete_user(user.id)
        assert Session.query(ActivityEvent).count() == 0
