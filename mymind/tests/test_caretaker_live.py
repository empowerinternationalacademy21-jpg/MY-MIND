"""Everything the child does reaches the caretaker dashboard, with numbers the graphs can use straight away."""
from database.db import Session
from database.models import ActivityEvent, ChildProfile
from services import caretaker_dashboard_service as dash
from services.activity_service import EVENT_TYPES
from test_activity_events import event_id, login_as_child


def _child(app):
    with app.app_context():
        c = Session.query(ChildProfile).one()
        return c.id, c.caregiver.child_username


def test_open_is_part_of_the_activity_vocabulary():
    assert "open" in EVENT_TYPES


def test_opened_items_reach_dashboard_timeline_and_counts(app, ready):
    login_as_child(app, ready)
    item = ready.get("/api/pictures").get_json()["items"][0]
    batch = [
        {"event_id": event_id(), "event_type": "view", "stop": "pictures", "duration_seconds": 20},
        {"event_id": event_id(), "event_type": "open", "stop": "pictures", "content_id": item["id"], "duration_seconds": 0},
        {"event_id": event_id(), "event_type": "like", "stop": "pictures", "content_id": item["id"], "duration_seconds": 0},
    ]
    assert ready.jpost("/api/activity-events", {"events": batch}).status_code == 200

    from datetime import date
    with app.app_context():
        child_id = Session.query(ChildProfile).one().id
        snap = dash.snapshot(child_id, date.today(), date.today(), date.today())
    kinds = [e["event_type"] for e in snap["timeline"]]
    assert "open" in kinds and "like" in kinds
    assert snap["summary"]["range_actions"] == 2            # view is time, not an action
    assert snap["days"][-1]["actions"] == 2
    assert snap["summary"]["last_active_iso"].endswith("Z")
    opened = next(e for e in snap["timeline"] if e["event_type"] == "open")
    assert opened["content"]["id"] == item["id"] and opened["iso"].endswith("Z")
    assert any(c["id"] == item["id"] for c in snap["content"]["recent"])


def test_taps_show_on_the_chart_even_with_zero_minutes(app, ready):
    login_as_child(app, ready)
    item = ready.get("/api/pictures").get_json()["items"][0]
    ready.jpost("/api/activity-events", {"events": [
        {"event_id": event_id(), "event_type": "favorite", "stop": "pictures", "content_id": item["id"], "duration_seconds": 0}]})
    ready.post("/logout")
    ready.login("mum")
    page = ready.get("/caretaker?range=7").get_data(as_text=True)
    assert "1 action" in page
    assert 'class="ct-curve' in page                          # chart is drawn from actions alone
    assert 'data-live="timeline"' in page and 'id="ct-live"' in page


def test_dashboard_page_still_renders_with_no_activity(app, ready):
    html = ready.get("/caretaker").get_data(as_text=True)
    assert "Waiting for" in html and "caretaker_live.js" in html
