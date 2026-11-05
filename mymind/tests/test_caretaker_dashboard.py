import csv
import io
from datetime import timedelta

from database.db import Session
from database.models import ActivityEvent, ContentItem, Favorite, utcnow


def test_caretaker_dashboard_and_csv_report(ready, app):
    with app.app_context():
        child = Session.query(__import__("database.models", fromlist=["ChildProfile"]).ChildProfile).one()
        item = ContentItem(provider="demo", provider_content_id="dash-video", content_type="video",
                           title="A bright day", thumbnail_url="https://example.test/thumb.jpg", category="sports")
        Session.add(item)
        Session.flush()
        now = utcnow()
        Session.add_all([
            ActivityEvent(child_id=child.id, stop="sports", content_id=item.id, content_title=item.title,
                          event_type="view", duration_seconds=900, client_event_id="dashboard-view-event-001",
                          created_at=now, last_active_at=now),
            ActivityEvent(child_id=child.id, stop="sports", content_id=item.id, content_title=item.title,
                          event_type="watch", duration_seconds=120, client_event_id="dashboard-watch-event-01",
                          created_at=now, last_active_at=now),
            ActivityEvent(child_id=child.id, stop="sports", content_id=item.id, content_title=item.title,
                          event_type="favorite", duration_seconds=0, client_event_id="dashboard-fav-event-0001",
                          created_at=now, last_active_at=now),
        ])
        Session.add(Favorite(child_profile_id=child.id, content_item_id=item.id))
        Session.commit()
        start = (now.date() - timedelta(days=6)).isoformat()
        end = now.date().isoformat()

    page = ready.get(f"/caretaker?range=custom&start={start}&end={end}")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "Minutes per day" in html and "Time by stop" in html and "Daily activity" in html
    assert "A bright day" in html and "Favorites added" in html

    report = ready.get(f"/caretaker/report.csv?start={start}&end={end}")
    assert report.status_code == 200
    rows = list(csv.reader(io.StringIO(report.get_data(as_text=True))))
    assert rows[0] == ["date", "time", "stop", "event", "content", "duration_seconds", "reaction"]
    assert any(row[4] == "A bright day" and row[3] == "watch" for row in rows[1:])