"""Child activity storage vocabulary and privacy-conscious aggregate helpers."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from database.db import Session
from database.models import ActivityEvent, ContentItem, utcnow


EVENT_TYPES = frozenset({"view", "watch", "like", "dislike", "favorite", "search", "next"})
STOPS = frozenset({
    # Requested stop names and the additional stops currently present in My World.
    "home", "soccer", "music", "food", "basketball", "colors", "pictures", "videos", "shorts", "nature",
    "sports", "animals", "vehicles", "art",
})
STOP_ALIASES = {"shots": "shorts"}


def normalize_stop(stop):
    if not isinstance(stop, str):
        raise ValueError("Unknown activity stop.")
    stop = STOP_ALIASES.get(stop, stop)
    if stop not in STOPS:
        raise ValueError("Unknown activity stop.")
    return stop


def _events(child_id, start=None, end=None, event_type=None):
    query = Session.query(ActivityEvent).filter(ActivityEvent.child_id == child_id)
    if start is not None:
        start_at = datetime.combine(start, time.min) if isinstance(start, date) and not isinstance(start, datetime) else start
        query = query.filter(ActivityEvent.created_at >= start_at)
    if end is not None:
        end_at = datetime.combine(end + timedelta(days=1), time.min) if isinstance(end, date) and not isinstance(end, datetime) else end
        query = query.filter(ActivityEvent.created_at < end_at)
    if event_type:
        query = query.filter(ActivityEvent.event_type == event_type)
    return query


def minutes_per_stop(child_id, start=None, end=None):
    """Active stop time in minutes; page/map view duration includes time spent watching content there."""
    totals = defaultdict(int)
    for stop, seconds in (_events(child_id, start, end, "view")
                          .with_entities(ActivityEvent.stop, ActivityEvent.duration_seconds)):
        totals[stop] += seconds or 0
    return {stop: round(seconds / 60, 2) for stop, seconds in totals.items()}


def _minutes_by_period(child_id, period, start=None, end=None):
    buckets = defaultdict(int)
    rows = (_events(child_id, start, end, "view")
            .with_entities(ActivityEvent.stop, ActivityEvent.created_at, ActivityEvent.duration_seconds))
    for stop, occurred_at, seconds in rows:
        day = occurred_at.date()
        if period == "day":
            bucket = day.isoformat()
        elif period == "week":
            bucket = (day - timedelta(days=day.weekday())).isoformat()
        else:
            bucket = day.strftime("%Y-%m")
        buckets[(bucket, stop)] += seconds or 0
    return [
        {"period": bucket, "stop": stop, "minutes": round(seconds / 60, 2)}
        for (bucket, stop), seconds in sorted(buckets.items())
    ]


def minutes_per_stop_by_day(child_id, start=None, end=None):
    return _minutes_by_period(child_id, "day", start, end)


def minutes_per_stop_by_week(child_id, start=None, end=None):
    return _minutes_by_period(child_id, "week", start, end)


def minutes_per_stop_by_month(child_id, start=None, end=None):
    return _minutes_by_period(child_id, "month", start, end)


def top_stops(child_id, start=None, end=None, limit=3):
    totals = minutes_per_stop(child_id, start, end)
    return sorted(totals.items(), key=lambda row: (-row[1], row[0]))[:max(0, limit)]


def videos_watched_count(child_id, start=None, end=None):
    return (_events(child_id, start, end, "watch")
            .join(ContentItem, ActivityEvent.content_id == ContentItem.id)
            .filter(ContentItem.content_type.in_(("video", "short")))
            .count())


def favorites_added_count(child_id, start=None, end=None):
    return _events(child_id, start, end, "favorite").count()


def daily_streak(child_id, today=None):
    today = today or utcnow().date()
    days = {row[0].date() for row in
            _events(child_id).with_entities(ActivityEvent.created_at).all()}
    cursor = today if today in days else today - timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def first_last_active_per_day(child_id, start=None, end=None):
    times = defaultdict(list)
    for occurred_at, last_active_at in (
            _events(child_id, start, end)
            .with_entities(ActivityEvent.created_at, ActivityEvent.last_active_at)):
        times[occurred_at.date()].extend((occurred_at, last_active_at or occurred_at))
    return [
        {"date": day.isoformat(), "first_active_at": min(values).isoformat(),
         "last_active_at": max(values).isoformat()}
        for day, values in sorted(times.items())
    ]


def active_times_per_day(child_id, start=None, end=None):
    """Alias retained for dashboard callers that prefer the shorter aggregate name."""
    return first_last_active_per_day(child_id, start, end)
