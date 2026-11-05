from datetime import timedelta

from database.db import Session
from database.models import ActivityEvent, ChildProfile, CaregiverRecommendationState, utcnow
from services import caretaker_recommendation_engine as engine


def _add_view(child_id, stop, seconds, event_id, occurred_at=None):
    occurred_at = occurred_at or utcnow()
    Session.add(ActivityEvent(child_id=child_id, stop=stop, event_type="view", duration_seconds=seconds,
                              client_event_id=event_id, created_at=occurred_at, last_active_at=occurred_at))


def test_dominant_stop_uses_real_time_and_dismissal_is_child_scoped(ready, app):
    with app.app_context():
        child = Session.query(ChildProfile).one()
        now = utcnow()
        _add_view(child.id, "soccer", 10_000, "rec-soccer-view-event-0001", now)
        _add_view(child.id, "music", 5_000, "rec-music-view-event-00001", now - timedelta(days=1))
        Session.commit()
        cards = engine.get_recommendations(child.id, child.caregiver_user_id)
        soccer = next(card for card in cards if card["key"] == "dominant:7:soccer")
        assert "Soccer" in soccer["reason"] and "67%" in soccer["reason"]
        assert "kickabout" in soccer["action"]
        assert engine.update_state(child.id, soccer["key"], "dismiss")
        assert soccer["key"] not in {card["key"] for card in engine.get_recommendations(child.id, child.caregiver_user_id)}
        state = Session.query(CaregiverRecommendationState).filter_by(recommendation_key=soccer["key"]).one()
        state.dismissed_at = utcnow() - timedelta(days=15)
        Session.commit()
        assert soccer["key"] in {card["key"] for card in engine.get_recommendations(child.id, child.caregiver_user_id)}


def test_daily_screen_time_warning_uses_caretaker_threshold(ready, app):
    with app.app_context():
        child = Session.query(ChildProfile).one()
        now = utcnow()
        _add_view(child.id, "pictures", 7_500, "rec-daily-view-event-000001", now)
        Session.commit()
        cards = engine.get_recommendations(child.id, child.caregiver_user_id, daily_limit=120)
        warning = next(card for card in cards if card["key"] == "screen:daily")
        assert "2h 5m" in warning["reason"] and "120-minute" in warning["reason"]
        assert not any(card["key"] == "screen:daily" for card in
                       engine.get_recommendations(child.id, child.caregiver_user_id, daily_limit=130))


def test_remind_action_hides_recommendation_for_a_day(ready, app):
    with app.app_context():
        child = Session.query(ChildProfile).one()
        assert engine.update_state(child.id, "variety:music", "remind")
        state = Session.query(CaregiverRecommendationState).filter_by(recommendation_key="variety:music").one()
        assert state.remind_until > utcnow()
        assert "variety:music" not in {card["key"] for card in engine.get_recommendations(child.id, child.caregiver_user_id)}