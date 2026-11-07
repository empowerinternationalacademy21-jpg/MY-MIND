"""Privacy-conscious aggregates for the caregiver activity dashboard."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import func

from database.db import Session
from database.models import ActivityEvent, ContentItem, Favorite, Interaction, utcnow
from services import activity_service
from services.world_service import STOP_DEFS

COLORS = ("#1f78f0", "#e8590c", "#22b450", "#ef6f9a", "#7c5cd6", "#f59e0b", "#2bb3a6")


def _event_query(child_id, start=None, end=None):
    query = Session.query(ActivityEvent).filter(ActivityEvent.child_id == child_id)
    if start is not None:
        query = query.filter(ActivityEvent.created_at >= datetime.combine(start, time.min))
    if end is not None:
        query = query.filter(ActivityEvent.created_at < datetime.combine(end + timedelta(days=1), time.min))
    return query


def _content(item):
    if not item:
        return None
    return {"id": item.id, "title": item.title, "thumbnail_url": item.thumbnail_url,
            "content_type": item.content_type, "category": item.category}


def _timeline(child_id, selected_day):
    rows = (_event_query(child_id, selected_day, selected_day).filter(ActivityEvent.event_type != "search")
            .order_by(ActivityEvent.created_at.asc(), ActivityEvent.id.asc()).all())
    interactions = {}
    ids = {row.content_id for row in rows if row.content_id}
    if ids:
        for item_id, interaction_type in (Session.query(Interaction.content_item_id, Interaction.interaction_type)
                .filter(Interaction.child_profile_id == child_id, Interaction.content_item_id.in_(ids))
                .order_by(Interaction.occurred_at.desc()).all()):
            interactions.setdefault(item_id, interaction_type)
    result = []
    for row in rows:
        item = Session.get(ContentItem, row.content_id) if row.content_id else None
        result.append({"time": row.created_at.strftime("%H:%M"), "iso": row.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "stop": row.stop,
                       "stop_label": STOP_DEFS.get(row.stop, {}).get("label", row.stop.title()),
                       "event_type": row.event_type, "duration_seconds": row.duration_seconds or 0,
                       "content": _content(item), "reaction": interactions.get(row.content_id)})
    return result


def _content_lists(child_id, start, end):
    recent_rows = (_event_query(child_id, start, end)
                   .filter(ActivityEvent.content_id.isnot(None))
                   .order_by(ActivityEvent.created_at.desc()).limit(100).all())
    recent, recent_ids = [], set()
    for row in recent_rows:
        if row.content_id in recent_ids:
            continue
        recent_ids.add(row.content_id)
        item = Session.get(ContentItem, row.content_id)
        if item:
            recent.append(_content(item))
        if len(recent) == 12:
            break

    favorites = (Session.query(ContentItem).join(Favorite, Favorite.content_item_id == ContentItem.id)
                 .filter(Favorite.child_profile_id == child_id)
             .filter(Favorite.created_at >= datetime.combine(start, time.min),
                 Favorite.created_at < datetime.combine(end + timedelta(days=1), time.min))
                 .order_by(Favorite.created_at.desc()).limit(30).all())
    watched_rows = (_event_query(child_id, start, end).filter(ActivityEvent.event_type == "watch",
                                                             ActivityEvent.content_id.isnot(None))
                    .order_by(ActivityEvent.created_at.desc()).all())
    watched, watched_ids = [], set()
    for row in watched_rows:
        if row.content_id in watched_ids:
            continue
        watched_ids.add(row.content_id)
        item = Session.get(ContentItem, row.content_id)
        if item:
            watched.append(_content(item))
    return {"recent": recent, "favorites": [_content(item) for item in favorites], "watched": watched}


def snapshot(child_id, start, end, selected_day=None):
    """Return bounded, presentation-ready chart, summary, and timeline data."""
    today = utcnow().date()
    selected_day = selected_day or today
    today_totals = activity_service.minutes_per_stop(child_id, today, today)
    week_start = today - timedelta(days=today.weekday())
    week_totals = activity_service.minutes_per_stop(child_id, week_start, today)
    totals = activity_service.minutes_per_stop(child_id, start, end)
    daily = activity_service.minutes_per_stop_by_day(child_id, start, end)
    weekly = activity_service.minutes_per_stop_by_week(child_id, start, end)
    daily_map, weekly_map = defaultdict(float), defaultdict(lambda: defaultdict(float))
    for row in daily:
        daily_map[row["period"]] += row["minutes"]
    for row in weekly:
        weekly_map[row["period"]][row["stop"]] += row["minutes"]
    # Taps count even when a short visit rounds to 0 minutes, so charts start moving from the first action.
    action_map = defaultdict(int)
    for created_at, in (_event_query(child_id, start, end)
                        .filter(ActivityEvent.event_type.notin_(("view", "search")))
                        .with_entities(ActivityEvent.created_at)):
        action_map[created_at.date().isoformat()] += 1
    days = [{"date": (start + timedelta(days=n)).isoformat(),
             "minutes": round(daily_map[(start + timedelta(days=n)).isoformat()], 1),
             "actions": action_map[(start + timedelta(days=n)).isoformat()]}
            for n in range((end - start).days + 1)]
    last_active = (Session.query(func.max(ActivityEvent.last_active_at))
                   .filter(ActivityEvent.child_id == child_id).scalar())

    day_rows = _event_query(child_id, start, end).filter(ActivityEvent.event_type == "view").all()
    hours = [0.0] * 24
    for row in day_rows:
        hours[row.created_at.hour] += (row.duration_seconds or 0) / 60
    max_hour = max(range(24), key=lambda hour: hours[hour]) if any(hours) else None
    stop_totals = [{"key": key, "label": STOP_DEFS.get(key, {}).get("label", key.title()),
                    "color": STOP_DEFS.get(key, {}).get("color", COLORS[index % len(COLORS)]),
                    "minutes": round(minutes, 1)}
                   for index, (key, minutes) in enumerate(sorted(totals.items(), key=lambda pair: (-pair[1], pair[0])))]
    total_minutes = round(sum(totals.values()), 1)
    week_minutes = round(sum(week_totals.values()), 1)
    top = stop_totals[0] if stop_totals else None
    trend = [{"week": period, "minutes": round(sum(stops.values()), 1),
              "stops": {key: round(value, 1) for key, value in stops.items()}}
             for period, stops in sorted(weekly_map.items())]
    return {
        "summary": {"today_minutes": round(sum(today_totals.values()), 1), "week_minutes": week_minutes,
                    "range_minutes": total_minutes,
                    "videos_watched": activity_service.videos_watched_count(child_id, start, end),
                    "favorites_added": activity_service.favorites_added_count(child_id, start, end),
                    "streak": activity_service.daily_streak(child_id),
                    "top_stop": top["label"] if top else "No activity yet",
                    "range_actions": sum(day["actions"] for day in days),
                    "last_active_iso": last_active.strftime("%Y-%m-%dT%H:%M:%SZ") if last_active else None},
        "days": days, "stops": stop_totals, "trend": trend,
        "hours": [{"hour": hour, "minutes": round(minutes, 1)} for hour, minutes in enumerate(hours)],
        "peak_hour": max_hour, "timeline": _timeline(child_id, selected_day),
        "content": _content_lists(child_id, start, end),
    }


def donut_gradient(stops):
    total = sum(row["minutes"] for row in stops)
    if total <= 0:
        return "conic-gradient(#e1e8f4 0 100%)"
    offset, parts = 0.0, []
    for index, row in enumerate(stops):
        end = offset + row["minutes"] / total * 100
        color = STOP_DEFS.get(row["key"], {}).get("color", COLORS[index % len(COLORS)])
        parts.append(f"{color} {offset:.2f}% {end:.2f}%")
        offset = end
    return "conic-gradient(" + ", ".join(parts) + ")"


def trend_series(trend, limit=4):
    categories = []
    for week in trend:
        for key in week["stops"]:
            if key not in categories:
                categories.append(key)
    categories = sorted(categories, key=lambda key: -sum(week["stops"].get(key, 0) for week in trend))[:limit]
    series = [{"key": "total", "label": "Total", "color": "#14305c",
               "values": [week["minutes"] for week in trend]}]
    series.extend({"key": key, "label": STOP_DEFS.get(key, {}).get("label", key.title()),
                   "color": STOP_DEFS.get(key, {}).get("color", COLORS[index % len(COLORS)]),
                   "values": [week["stops"].get(key, 0) for week in trend]}
                  for index, key in enumerate(categories))
    maximum = max((value for item in series for value in item["values"]), default=0) or 1
    count = max(1, len(trend))
    for item in series:
        item["points"] = " ".join(f"{(index * 100 / max(1, count - 1)):.1f},{(100 - value / maximum * 88):.1f}"
                                  for index, value in enumerate(item["values"]))
    return series


def export_rows(child_id, start, end):
    rows = (_event_query(child_id, start, end).filter(ActivityEvent.event_type != "search")
            .order_by(ActivityEvent.created_at.asc(), ActivityEvent.id.asc()).all())
    output = []
    for row in rows:
        item = Session.get(ContentItem, row.content_id) if row.content_id else None
        output.append([row.created_at.date().isoformat(), row.created_at.strftime("%H:%M"), row.stop,
                       row.event_type, item.title if item else row.content_title or "",
                       row.duration_seconds or 0, ""])
    return output
