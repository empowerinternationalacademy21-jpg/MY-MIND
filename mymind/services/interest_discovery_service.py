"""Interest discovery: recurring patterns in what a child actually does in the app.

Everything here is computed from recorded activity (content sessions, completions, replays, likes, favorites, category
exploration). Nothing is typed in by hand and nothing is hardcoded per child.

How a category becomes a *possible interest* (all constants below, so they are easy to read and change):

* Each engaged session adds points: minutes engaged (max 10 per session) + 1 if finished + 1 per replay.
  Tiny opens (under 10 seconds) add a quarter point; likes +1.5, favorites +2, dislikes -1.5, exploring the category +0.25.
* Older points fade (half-life 14 days), so interests can change naturally as new activity is recorded.
* A category qualifies when it has at least 3 engaged sessions on at least 2 different days AND a score of at least 3.
  One click, one long video or one day never creates an interest.
* Trend compares the last 7 days with the 7 days before (emerging / increasing / steady / fading).

These are possible interests to explore together. They are not an assessment of ability, intelligence, talent or future
career, and the dashboard says so wherever they are shown.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from database.db import Session
from database.models import ActivityEvent, ContentItem, utcnow
from services import activity_analytics_service as analytics
from services.categories import CATEGORIES, label_for

LOOKBACK_DAYS = 30
HALF_LIFE_DAYS = 14.0
QUALIFY_SCORE, QUALIFY_SESSIONS, QUALIFY_DAYS = 3.0, 3, 2
TINY_SESSION_SECONDS = 10
LEVEL_STEPS = (3.0, 8.0, 15.0)                       # score needed for emphasis level 1, 2, 3 in the world
DISCLAIMER = ("These are possible interests based on what your child chose and spent time on in MyMind. They are not an assessment "
              "of ability, intelligence or talent. Interests change naturally, so use them as ideas to explore together.")


def _blank():
    return {"points": 0.0, "weighted": 0.0, "sessions": 0, "seconds": 0.0, "completions": 0, "replays": 0, "likes": 0, "favorites": 0,
            "dislikes": 0, "browse": 0, "days": set(), "first": None, "last": None, "recent_points": 0.0, "prev_points": 0.0,
            "recent_seconds": 0.0, "prev_seconds": 0.0, "recent_sessions": 0, "prev_sessions": 0,
            "boost_score": 0.0, "boost_evidence": 0}


def _decay(age_days):
    return 0.5 ** (max(0.0, age_days) / HALF_LIFE_DAYS)


def level_for(score):
    return sum(1 for step in LEVEL_STEPS if score >= step)


def discover(child_id, now=None, tz=0, lookback_days=LOOKBACK_DAYS):
    """Rank the child's categories by recorded engagement, with plain-language evidence for each."""
    now = now or utcnow()
    tz = analytics.clamp_tz(tz)
    since = now - timedelta(days=lookback_days)
    rows = (Session.query(ActivityEvent).filter(ActivityEvent.child_id == child_id, ActivityEvent.created_at >= since,
                                                ActivityEvent.created_at <= now + timedelta(minutes=5),
                                                ActivityEvent.event_type != "view", ActivityEvent.event_type != "search")
            .order_by(ActivityEvent.created_at.asc(), ActivityEvent.id.asc()).all())
    ids = {r.content_id for r in rows if r.content_id}
    content = {c.id: c for c in Session.query(ContentItem).filter(ContentItem.id.in_(ids)).all()} if ids else {}
    eff = analytics.effective_seconds([r for r in rows if r.event_type in analytics.SESSIONS])
    data = defaultdict(_blank)

    for row in rows:
        item = content.get(row.content_id)
        category = row.category or (item.category if item else None)
        if category not in CATEGORIES:
            continue
        age = (now - row.created_at).total_seconds() / 86400.0
        weight = _decay(age)
        d = data[category]
        local_day = (row.created_at + timedelta(minutes=tz)).date()
        points, engaged = 0.0, False
        if row.event_type in analytics.SESSIONS:
            seconds = eff.get(row.id, 0.0)
            engaged = seconds >= TINY_SESSION_SECONDS or bool(row.completed)
            points = (min(seconds, 600.0) / 60.0 + (1.0 if row.completed else 0.0) + (row.replay_count or 0)) if engaged else 0.25
            if engaged:
                d["sessions"] += 1
                d["seconds"] += seconds
                d["completions"] += 1 if row.completed else 0
                d["replays"] += row.replay_count or 0
                d["days"].add(local_day)
                d["boost_score"] += (min(seconds, 600.0) / 60.0 * 0.25 + 0.5 * (1 if row.completed else 0) + 0.5 * (row.replay_count or 0)) * weight
                d["boost_evidence"] += 1 + (row.replay_count or 0)
                bucket = "recent" if age <= 7 else "prev" if age <= 14 else None
                if bucket:
                    d[bucket + "_seconds"] += seconds
                    d[bucket + "_sessions"] += 1
        elif row.event_type == "like":
            points, d["likes"] = 1.5, d["likes"] + 1
        elif row.event_type == "favorite":
            points, d["favorites"] = 2.0, d["favorites"] + 1
        elif row.event_type == "dislike":
            points, d["dislikes"] = -1.5, d["dislikes"] + 1
        elif row.event_type == "browse":
            points, d["browse"] = 0.25, d["browse"] + 1
        elif row.event_type == "open":
            points = 0.25
        d["points"] += points
        d["weighted"] += points * weight
        if age <= 7:
            d["recent_points"] += points
        elif age <= 14:
            d["prev_points"] += points
        d["first"] = row.created_at if d["first"] is None else min(d["first"], row.created_at)
        d["last"] = row.created_at if d["last"] is None else max(d["last"], row.created_at)

    interests = []
    for category, d in data.items():
        score = max(0.0, round(d["weighted"], 2))
        qualified = score >= QUALIFY_SCORE and d["sessions"] >= QUALIFY_SESSIONS and len(d["days"]) >= QUALIFY_DAYS
        status = _status(d, qualified, now)
        entry = {
            "category": category, "label": label_for(category), "icon": CATEGORIES[category]["icon"], "color": CATEGORIES[category]["color"],
            "score": score, "level": level_for(score) if qualified else 0, "qualified": qualified, "status": status,
            "sessions": d["sessions"], "minutes": round(d["seconds"] / 60.0, 1), "completions": d["completions"], "replays": d["replays"],
            "likes": d["likes"], "favorites": d["favorites"], "explored": d["browse"], "active_days": len(d["days"]),
            "recent_minutes": round(d["recent_seconds"] / 60.0, 1), "prev_minutes": round(d["prev_seconds"] / 60.0, 1),
            "recent_sessions": d["recent_sessions"], "prev_sessions": d["prev_sessions"],
            "first_seen": d["first"].strftime("%Y-%m-%dT%H:%M:%SZ") if d["first"] else None,
            "last_seen": d["last"].strftime("%Y-%m-%dT%H:%M:%SZ") if d["last"] else None,
            "boost_score": round(d["boost_score"], 2), "boost_evidence": d["boost_evidence"],
        }
        entry["evidence"] = _evidence_text(entry)
        entry["insight"] = _insight_text(entry, lookback_days)
        interests.append(entry)
    interests.sort(key=lambda i: (-i["score"], i["category"]))
    qualified_rows = [i for i in interests if i["qualified"]]
    insights = [{"kind": i["status"], "category": i["category"], "label": i["label"], "text": i["insight"]}
                for i in qualified_rows[:6] if i["insight"]]
    for i in interests:                                       # a fading interest is worth one gentle line even if it no longer qualifies
        if i["status"] == "fading" and not any(x["category"] == i["category"] for x in insights):
            insights.append({"kind": "fading", "category": i["category"], "label": i["label"], "text": i["insight"]})
    total_sessions = sum(i["sessions"] for i in interests)
    message = None
    if not interests:
        message = "No activity has been recorded yet. Interests appear once your child has explored a few things."
    elif not qualified_rows:
        message = ("Not enough repeated activity yet to name an interest. Interests need a few sessions on at least two different "
                   "days, so one video or one visit never creates one.")
    return {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "lookback_days": lookback_days, "has_activity": total_sessions > 0,
            "interests": interests, "possible": qualified_rows, "insights": insights, "message": message, "disclaimer": DISCLAIMER}


def _status(d, qualified, now):
    if d["sessions"] < 1 and not qualified:
        return "exploring"
    recent, prev = d["recent_points"], d["prev_points"]
    first_age = (now - d["first"]).total_seconds() / 86400.0 if d["first"] else 999
    if qualified and first_age <= 14 and prev < 1.0 and recent >= 2.0:
        return "emerging"
    if prev >= 2.0 and recent <= 0.75 * prev and d["recent_sessions"] <= d["prev_sessions"]:
        return "fading"
    if recent >= 2.0 and prev > 0 and recent >= 1.25 * prev:
        return "increasing"
    if qualified:
        return "steady"
    return "exploring"


def _mins(value):
    return f"{value:g}" if value < 10 else f"{round(value)}"


def _evidence_text(i):
    parts = [f"{i['sessions']} session{'s' if i['sessions'] != 1 else ''}", f"{_mins(i['minutes'])} min engaged",
             f"on {i['active_days']} day{'s' if i['active_days'] != 1 else ''}"]
    if i["completions"]:
        parts.append(f"{i['completions']} finished")
    if i["replays"]:
        parts.append(f"{i['replays']} replay{'s' if i['replays'] != 1 else ''}")
    if i["favorites"]:
        parts.append(f"{i['favorites']} favorite{'s' if i['favorites'] != 1 else ''}")
    if i["likes"]:
        parts.append(f"{i['likes']} like{'s' if i['likes'] != 1 else ''}")
    return ", ".join(parts)


def _insight_text(i, lookback):
    label, evidence = i["label"], i["evidence"]
    status = i["status"]
    if status == "emerging":
        return f"{label} looks like a new interest. In the last {lookback} days: {evidence}."
    if status == "increasing":
        return (f"Your child has shown increased engagement with {label.lower()} content this week: {i['recent_minutes']:g} min across "
                f"{i['recent_sessions']} session{'s' if i['recent_sessions'] != 1 else ''}, compared with {i['prev_minutes']:g} min the week before.")
    if status == "fading":
        return (f"Engagement with {label.lower()} has eased lately ({i['recent_minutes']:g} min this week, {i['prev_minutes']:g} min the week before). "
                "Interests change naturally, so this is not a concern.")
    if status == "steady" and i["qualified"]:
        return f"{label} is among your child's most frequently explored categories: {evidence}."
    return ""


# ------------------------------------------------------------------ hooks used by the world
def world_boost_from(found):
    """{category: {'score': float, 'evidence': int}} from real sessions only (likes/favorites are already counted by the interest profile)."""
    return {i["category"]: {"score": i["boost_score"], "evidence": i["boost_evidence"]} for i in found["interests"]
            if i["boost_score"] > 0 or i["boost_evidence"] > 0}


def world_boost(child_id, now=None):
    return world_boost_from(discover(child_id, now=now))
