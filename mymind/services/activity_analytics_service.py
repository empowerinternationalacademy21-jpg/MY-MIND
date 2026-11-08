"""Caretaker analytics computed ONLY from the child's recorded activity (nothing is typed in, estimated or invented).

Definitions (also shown to caretakers on the dashboard):

* Engagement time  = time spent in content sessions: ``watch`` (video / short), ``listen`` (song) and ``look`` (picture).
                     Page-visit time (``view``) is NOT engagement: it is how long a page was open, not what the child did on it.
* Overlap safety   = sessions that overlap in real time (two tabs, a retried heartbeat) are credited once: each session only
                     keeps the share of its time not already covered by an earlier session.
* Idle time        = when the player reports its state (YouTube / Spotify), only playing time is counted (``measured``). When it
                     cannot, only the time the viewer was open and visible is counted, and the dashboard says so.
* Completion %     = (content actually played / content length) x 100, only when the player reported the length; otherwise unknown.
* Category share   = category engagement time / total categorised engagement time x 100.
* Weekly change    = (this week - previous week) / previous week x 100  (None when there is no previous week to compare).
* Average per day  = total engagement time / number of days in the selected period.
* Content score    = minutes + 2 per completion + 1.5 per replay + 1 per like + 2 per favorite (a plain, explainable ranking).

All day/week/month boundaries use the caretaker's own time zone (``tz`` = minutes east of UTC), not the server's.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_

from database.db import Session
from database.models import ActivityEvent, ContentItem, Interaction, utcnow
from services import activity_service
from services.categories import CATEGORIES, label_for

SESSIONS = tuple(activity_service.SESSION_TYPES)           # watch, listen, look
TYPE_LABELS = {"video": "Videos", "short": "Shorts", "song": "Songs", "picture": "Pictures", "other": "Other activities"}
STOP_LABELS = {"home": "Home", "pictures": "Pictures", "videos": "Videos", "shorts": "Shorts", "music": "Music", "sports": "Sports",
               "food": "Food", "colors": "Colors & Shapes", "nature": "Nature", "animals": "Animals", "vehicles": "Vehicles",
               "art": "Art", "soccer": "Football", "basketball": "Basketball"}
ACTION_LABELS = {"watch": "Watched", "listen": "Listened", "look": "Viewed", "open": "Opened", "like": "Liked", "dislike": "Disliked",
                 "favorite": "Saved as favorite", "next": "Skipped", "search": "Searched", "browse": "Explored a category",
                 "view": "Visited"}
PERIODS = (("night", "Night (00-05)", 0, 6), ("morning", "Morning (06-11)", 6, 12),
           ("afternoon", "Afternoon (12-17)", 12, 18), ("evening", "Evening (18-23)", 18, 24))
MIN_COMPARE_SECONDS = 120                                    # below this there is not enough to call a trend
CHANGE_THRESHOLD = 25.0                                      # +/- % that counts as increasing / decreasing


# ------------------------------------------------------------------ time helpers
def clamp_tz(tz):
    try:
        return max(-840, min(840, int(tz)))
    except (TypeError, ValueError):
        return 0


def _local(dt, tz):
    return dt + timedelta(minutes=tz)


def _bounds(start, end, tz):
    """Local calendar days [start, end] -> naive UTC datetimes [lo, hi)."""
    lo = datetime.combine(start, time.min) - timedelta(minutes=tz)
    hi = datetime.combine(end + timedelta(days=1), time.min) - timedelta(minutes=tz)
    return lo, hi


def _minutes(seconds):
    return round((seconds or 0) / 60.0, 2)


# ------------------------------------------------------------------ engagement time (overlap safe)
def _span_end(row):
    duration = min(row.duration_seconds or 0, activity_service.MAX_SESSION_SECONDS)
    end = row.created_at + timedelta(seconds=duration)
    if row.last_active_at and row.last_active_at > end:
        end = row.last_active_at
    return end


def effective_seconds(rows):
    """{event id: seconds} for session rows, crediting overlapping real time only once (earlier session keeps the overlap)."""
    out, covered = {}, None
    for row in sorted(rows, key=lambda r: (r.created_at, r.id or 0)):
        duration = min(row.duration_seconds or 0, activity_service.MAX_SESSION_SECONDS)
        start, end = row.created_at, _span_end(row)
        span = (end - start).total_seconds()
        if duration <= 0:
            out[row.id] = 0.0
            continue
        if covered is None or start >= covered:
            uncovered = span
        elif end <= covered:
            uncovered = 0.0
        else:
            uncovered = (end - covered).total_seconds()
        out[row.id] = duration * (uncovered / span) if span > 0 else float(duration)
        covered = end if covered is None else max(covered, end)
    return out


def _session_rows(child_id, lo, hi):
    return (Session.query(ActivityEvent)
            .filter(ActivityEvent.child_id == child_id, ActivityEvent.event_type.in_(SESSIONS),
                    ActivityEvent.created_at >= lo, ActivityEvent.created_at < hi)
            .order_by(ActivityEvent.created_at.asc(), ActivityEvent.id.asc()).all())


def _content_map(rows):
    ids = {r.content_id for r in rows if r.content_id}
    if not ids:
        return {}
    return {c.id: c for c in Session.query(ContentItem).filter(ContentItem.id.in_(ids)).all()}


def _category(row, content):
    return row.category or (content.category if content else None)


def _ctype(row, content):
    return row.content_type or (content.content_type if content else None) or "other"


def content_card(item, fallback_title=None):
    """Compact, safe description of a content item for the dashboard (the real thumbnail, never invented)."""
    from services import content_service as cs
    if not item:
        return {"id": None, "title": fallback_title or "Content no longer available", "type": "other", "category": None,
                "category_label": None, "thumbnail_url": None, "available": False}
    return {"id": item.id, "title": item.title, "type": item.content_type, "category": item.category,
            "category_label": label_for(item.category) if item.category else None, "thumbnail_url": cs.thumb_for(item),
            "available": True}


# ------------------------------------------------------------------ core aggregate for one window
def _aggregate(child_id, start, end, tz):
    """One pass over the window's session rows -> every number the dashboard needs for that window."""
    lo, hi = _bounds(start, end, tz)
    rows = _session_rows(child_id, lo, hi)
    content = _content_map(rows)
    eff = effective_seconds(rows)
    agg = {"rows": rows, "content": content, "eff": eff, "total": 0.0, "sessions": len(rows), "completions": 0, "replays": 0,
           "by_day": defaultdict(float), "by_day_type": defaultdict(lambda: defaultdict(float)),
           "by_type": defaultdict(float), "by_category": defaultdict(float), "by_category_type": defaultdict(lambda: defaultdict(float)),
           "by_cat_sessions": defaultdict(int), "by_cat_replays": defaultdict(int), "by_cat_completions": defaultdict(int),
           "by_hour": [0.0] * 24, "by_content": {}, "by_weekday": defaultdict(float), "measured_seconds": 0.0}
    for row in rows:
        item = content.get(row.content_id)
        seconds = eff.get(row.id, 0.0)
        local = _local(row.created_at, tz)
        ctype, category, day = _ctype(row, item), _category(row, item), local.date().isoformat()
        agg["total"] += seconds
        agg["by_day"][day] += seconds
        agg["by_day_type"][day][ctype] += seconds
        agg["by_type"][ctype] += seconds
        agg["by_hour"][local.hour] += seconds
        agg["by_weekday"][local.weekday()] += seconds
        if row.measured:
            agg["measured_seconds"] += seconds
        if category:
            agg["by_category"][category] += seconds
            agg["by_category_type"][category][ctype] += seconds
            agg["by_cat_sessions"][category] += 1
        if row.completed:
            agg["completions"] += 1
            if category:
                agg["by_cat_completions"][category] += 1
        if row.replay_count:
            agg["replays"] += row.replay_count
            if category:
                agg["by_cat_replays"][category] += row.replay_count
        if row.content_id:
            entry = agg["by_content"].setdefault(row.content_id, {"seconds": 0.0, "sessions": 0, "replays": 0, "completions": 0,
                                                                  "last": row.created_at, "best_completion": None})
            entry["seconds"] += seconds
            entry["sessions"] += 1
            entry["replays"] += row.replay_count or 0
            entry["completions"] += 1 if row.completed else 0
            entry["last"] = max(entry["last"], row.created_at)
            if row.completion_pct is not None:
                entry["best_completion"] = max(entry["best_completion"] or 0.0, row.completion_pct)
    return agg


def _top_category(agg, types):
    totals = defaultdict(float)
    for category, by_type in agg["by_category_type"].items():
        totals[category] = sum(by_type.get(t, 0.0) for t in types)
    totals = {c: s for c, s in totals.items() if s > 0}
    if not totals:
        return None
    category = max(totals, key=lambda c: (totals[c], c))
    return {"category": category, "label": label_for(category), "minutes": _minutes(totals[category])}


def pct_change(current, previous):
    """((current - previous) / previous) x 100, or None when previous is zero/missing (no invented trend)."""
    if previous is None or previous <= 0:
        return None
    return round((current - previous) / previous * 100.0, 1)


def classify(current, previous, floor=MIN_COMPARE_SECONDS):
    """increasing / decreasing / stable / new / insufficient from two engagement-second totals."""
    if current < floor and previous < floor:
        return "insufficient"
    if previous < floor <= current:
        return "new"
    change = pct_change(current, previous)
    if change is None:
        return "insufficient"
    if change >= CHANGE_THRESHOLD:
        return "increasing"
    if change <= -CHANGE_THRESHOLD:
        return "decreasing"
    return "stable"


# ------------------------------------------------------------------ interactions (likes / favorites / opens / searches / browse)
def _interaction_counts(child_id, lo, hi):
    rows = (Session.query(ActivityEvent.event_type, ActivityEvent.content_id, ActivityEvent.category, ActivityEvent.stop,
                          func.count(ActivityEvent.id))
            .filter(ActivityEvent.child_id == child_id, ActivityEvent.created_at >= lo, ActivityEvent.created_at < hi,
                    ActivityEvent.event_type.notin_(SESSIONS))
            .group_by(ActivityEvent.event_type, ActivityEvent.content_id, ActivityEvent.category, ActivityEvent.stop).all())
    return rows


# ------------------------------------------------------------------ public: summary for the dashboard
def summary(child_id, start, end, tz=0, earliest=None, focus_day=None):
    """Everything the dashboard graphs and statistic cards need, for local days [start, end]."""
    tz = clamp_tz(tz)
    days = (end - start).days + 1
    agg = _aggregate(child_id, start, end, tz)
    lo, hi = _bounds(start, end, tz)
    total = agg["total"]
    category_total = sum(agg["by_category"].values())

    # ---- daily series (+ per content type) over the selected period
    daily = []
    for n in range(days):
        d = (start + timedelta(days=n)).isoformat()
        by_type = {t: _minutes(s) for t, s in agg["by_day_type"].get(d, {}).items() if s > 0}
        daily.append({"date": d, "minutes": _minutes(agg["by_day"].get(d, 0.0)), "by_type": by_type})
    active_days = sum(1 for d in daily if d["minutes"] > 0)
    peak = max(daily, key=lambda d: (d["minutes"], d["date"])) if any(d["minutes"] for d in daily) else None

    # ---- hour-of-day for the whole period (Graph 1 uses the focus day below) and most active time period
    hours = [{"hour": h, "minutes": _minutes(agg["by_hour"][h])} for h in range(24)]
    period_totals = [(key, label, sum(agg["by_hour"][h] for h in range(a, b))) for key, label, a, b in PERIODS]
    best_period = max(period_totals, key=lambda p: p[2]) if total > 0 else None

    # ---- graph 1: one day, hour by hour, split by content type
    focus = focus_day if (focus_day and start <= focus_day <= end) else end
    day_lo, day_hi = _bounds(focus, focus, tz)
    day_rows = [r for r in agg["rows"] if day_lo <= r.created_at < day_hi]
    day_hours = [defaultdict(float) for _ in range(24)]
    for row in day_rows:
        item = agg["content"].get(row.content_id)
        day_hours[_local(row.created_at, tz).hour][_ctype(row, item)] += agg["eff"].get(row.id, 0.0)
    day_graph = [{"hour": h, "minutes": _minutes(sum(v.values())), "by_type": {t: _minutes(s) for t, s in v.items() if s > 0}}
                 for h, v in enumerate(day_hours)]

    # ---- graph 2: weekly engagement = the 7 days ending at `end` (compared with each other)
    week_days = [(end - timedelta(days=6 - n)) for n in range(7)]
    week_agg = agg if (start <= week_days[0]) else _aggregate(child_id, week_days[0], end, tz)
    week_graph = [{"date": d.isoformat(), "weekday": d.strftime("%a"), "minutes": _minutes(week_agg["by_day"].get(d.isoformat(), 0.0))}
                  for d in week_days]
    week_total = sum(week_agg["by_day"].get(d.isoformat(), 0.0) for d in week_days)

    # ---- graph 3: month = every day of the month containing `end`
    month_first = end.replace(day=1)
    next_month = (month_first + timedelta(days=32)).replace(day=1)
    month_last = min(next_month - timedelta(days=1), end)
    m_agg = agg if (start <= month_first and end >= month_last) else _aggregate(child_id, month_first, month_last, tz)
    month_graph = [{"date": (month_first + timedelta(days=n)).isoformat(),
                    "minutes": _minutes(m_agg["by_day"].get((month_first + timedelta(days=n)).isoformat(), 0.0))}
                   for n in range((month_last - month_first).days + 1)]
    month_total = sum(m_agg["by_day"].values())

    # ---- graph 4 & 7: interest distribution (by interactions) and time allocation (by minutes)
    interactions = defaultdict(int)
    for category, n in agg["by_cat_sessions"].items():
        interactions[category] += n + agg["by_cat_replays"].get(category, 0) + agg["by_cat_completions"].get(category, 0)
    like_rows = _interaction_counts(child_id, lo, hi)
    cat_of_content = {c.id: c.category for c in agg["content"].values()}
    missing = {cid for et, cid, cat, stop, n in like_rows if cid and cid not in cat_of_content}
    if missing:
        cat_of_content.update({i: c for i, c in Session.query(ContentItem.id, ContentItem.category).filter(ContentItem.id.in_(missing))})
    reaction_points = defaultdict(float)
    for et, cid, cat, stop, n in like_rows:
        category = cat or (cat_of_content.get(cid) if cid else None)
        if not category:
            continue
        if et in ("like", "favorite"):
            interactions[category] += n
            reaction_points[category] += n * (2.0 if et == "favorite" else 1.0)
        elif et == "browse":
            interactions[category] += n
    inter_total = sum(interactions.values())
    distribution = [{"category": c, "label": label_for(c), "color": CATEGORIES.get(c, {}).get("color", "#7a8794"),
                     "interactions": n, "percent": round(n / inter_total * 100.0, 1) if inter_total else 0.0}
                    for c, n in sorted(interactions.items(), key=lambda kv: (-kv[1], kv[0]))]
    allocation = [{"category": c, "label": label_for(c), "color": CATEGORIES.get(c, {}).get("color", "#7a8794"),
                   "minutes": _minutes(s), "percent": round(s / category_total * 100.0, 1) if category_total else 0.0}
                  for c, s in sorted(agg["by_category"].items(), key=lambda kv: (-kv[1], kv[0])) if s > 0]

    # ---- graph 5: content-type comparison
    types = []
    for t in ("video", "short", "song", "picture"):
        n = sum(1 for r in agg["rows"] if _ctype(r, agg["content"].get(r.content_id)) == t)
        types.append({"type": t, "label": TYPE_LABELS[t], "minutes": _minutes(agg["by_type"].get(t, 0.0)), "sessions": n})
    other_views = sum(n for et, cid, cat, stop, n in like_rows if et in ("view", "browse", "search", "open") and not cid)
    types.append({"type": "other", "label": TYPE_LABELS["other"], "minutes": _minutes(agg["by_type"].get("other", 0.0)),
                  "sessions": other_views})

    # ---- graph 6: interest development (weekly buckets, top categories) - needs real history to mean anything
    development = _development(agg, start, end, tz)

    # ---- graph 8: most engaging content (explainable score)
    reactions = defaultdict(lambda: {"like": 0, "favorite": 0})
    for et, cid, cat, stop, n in like_rows:
        if cid and et in ("like", "favorite"):
            reactions[cid][et] += n
    ranked = []
    for cid, entry in agg["by_content"].items():
        r = reactions.get(cid, {"like": 0, "favorite": 0})
        score = (entry["seconds"] / 60.0 + 2 * entry["completions"] + 1.5 * entry["replays"] + r["like"] + 2 * r["favorite"])
        ranked.append((score, cid, entry))
    ranked.sort(key=lambda t: (-t[0], t[1]))
    most_engaging = [{"content": content_card(agg["content"].get(cid)), "score": round(score, 1), "minutes": _minutes(e["seconds"]),
                      "sessions": e["sessions"], "replays": e["replays"], "completions": e["completions"]}
                     for score, cid, e in ranked[:8]]

    # ---- comparisons with the previous period (only when the plan's history window still contains it)
    prev_week = _previous_total(child_id, end - timedelta(days=13), end - timedelta(days=7), tz, earliest)
    month_prev = _previous_total(child_id, end - timedelta(days=59), end - timedelta(days=30), tz, earliest)
    cur30_start = end - timedelta(days=29)
    cur30 = _window_total(child_id, cur30_start, end, tz, agg, start)
    week_change = pct_change(week_total, prev_week) if prev_week is not None else None
    month_change = pct_change(cur30, month_prev) if month_prev is not None else None

    # ---- interests going up / down / steady: this period vs the previous period of equal length
    trends = _category_trends(child_id, start, end, tz, agg, earliest)

    top_replay = None
    if agg["by_content"]:
        cid, e = max(agg["by_content"].items(), key=lambda kv: (kv[1]["replays"] + max(0, kv[1]["sessions"] - 1), kv[1]["seconds"], -kv[0]))
        if e["replays"] + max(0, e["sessions"] - 1) > 0:
            top_replay = {"content": content_card(agg["content"].get(cid)), "plays": e["sessions"] + e["replays"]}

    stats = {
        "total_minutes": _minutes(total), "avg_daily_minutes": _minutes(total / days) if days else 0.0, "active_days": active_days,
        "days": days, "sessions": agg["sessions"], "completions": agg["completions"], "replays": agg["replays"],
        "week_minutes": _minutes(week_total), "month_minutes": _minutes(month_total),
        "most_active_day": ({"date": peak["date"], "minutes": peak["minutes"]} if peak else None),
        "most_active_period": ({"key": best_period[0], "label": best_period[1], "minutes": _minutes(best_period[2])} if best_period else None),
        "top_video_category": _top_category(agg, ("video", "short")), "top_music_category": _top_category(agg, ("song",)),
        "top_picture_category": _top_category(agg, ("picture",)), "most_replayed": top_replay,
        "week_change_pct": week_change, "week_change_note": None if week_change is not None else
        "Not enough earlier activity to compare with the previous week yet.",
        "month_change_pct": month_change, "month_change_note": None if month_change is not None else
        "Not enough earlier activity to compare with the previous 30 days yet.",
        "measured_share": round(agg["measured_seconds"] / total * 100.0) if total else None,
    }
    return {
        "range": {"start": start.isoformat(), "end": end.isoformat(), "days": days, "focus_day": focus.isoformat(), "tz": tz},
        "stats": stats, "daily": daily, "hours": hours, "day_graph": day_graph, "week_graph": week_graph, "month_graph": month_graph,
        "month_label": month_first.strftime("%B %Y"), "distribution": distribution, "allocation": allocation, "types": types,
        "development": development, "most_engaging": most_engaging, "trends": trends,
        "rankings": rankings(child_id, agg, like_rows, reactions, lo, hi),
        "formulas": FORMULAS, "has_data": agg["sessions"] > 0 or bool(like_rows),
    }


FORMULAS = [
    {"name": "Category share", "formula": "category engagement time ÷ total categorised engagement time × 100"},
    {"name": "Weekly change", "formula": "(this week − previous week) ÷ previous week × 100"},
    {"name": "Average per day", "formula": "total engagement time ÷ days in the selected period"},
    {"name": "Completion", "formula": "content actually played ÷ content length × 100 (only when the player reports the length)"},
    {"name": "Content score", "formula": "minutes + 2 per completion + 1.5 per replay + 1 per like + 2 per favorite"},
    {"name": "Engagement time", "formula": "time in videos, shorts, songs and pictures; page-open time is not counted; overlaps are counted once"},
]


def _window_total(child_id, start, end, tz, agg, agg_start):
    if agg_start <= start:                        # the selected window already contains it: reuse the pass
        _, hi = _bounds(start, end, tz)
        total = 0.0
        for row in agg["rows"]:
            if _bounds(start, start, tz)[0] <= row.created_at < hi:
                total += agg["eff"].get(row.id, 0.0)
        return total
    return _aggregate(child_id, start, end, tz)["total"]


def _previous_total(child_id, start, end, tz, earliest):
    """Engagement seconds for an earlier window, or None when the plan's history limit hides part of it."""
    if earliest is not None and start < earliest:
        return None
    total = _aggregate(child_id, start, end, tz)["total"]
    return total if total > 0 else None


def _development(agg, start, end, tz):
    """Weekly engagement per category for the top categories. Fewer than two active weeks -> an honest 'not enough data'."""
    weeks, labels = defaultdict(lambda: defaultdict(float)), {}
    for row in agg["rows"]:
        item = agg["content"].get(row.content_id)
        category = _category(row, item)
        if not category:
            continue
        day = _local(row.created_at, tz).date()
        monday = day - timedelta(days=day.weekday())
        weeks[monday.isoformat()][category] += agg["eff"].get(row.id, 0.0)
    ordered = sorted(weeks)
    totals = defaultdict(float)
    for w in ordered:
        for c, s in weeks[w].items():
            totals[c] += s
    top = [c for c, _ in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]
    # fill every week between the first and last so gaps show as zero rather than disappearing
    all_weeks = []
    if ordered:
        cursor, last = date.fromisoformat(ordered[0]), date.fromisoformat(ordered[-1])
        while cursor <= last:
            all_weeks.append(cursor.isoformat())
            cursor += timedelta(days=7)
    series = [{"category": c, "label": label_for(c), "color": CATEGORIES.get(c, {}).get("color", "#7a8794"),
               "values": [_minutes(weeks[w].get(c, 0.0)) for w in all_weeks]} for c in top]
    return {"weeks": all_weeks, "series": series, "enough": len(all_weeks) >= 2 and bool(series),
            "message": None if (len(all_weeks) >= 2 and series) else
            "Interest development needs activity in at least two different weeks. It will appear as more activity is recorded."}


def _category_trends(child_id, start, end, tz, agg, earliest):
    days = (end - start).days + 1
    prev_end, prev_start = start - timedelta(days=1), start - timedelta(days=days)
    if earliest is not None and prev_start < earliest:
        return {"available": False, "message": "Your plan's history window does not cover an earlier period to compare with.",
                "increasing": [], "decreasing": [], "stable": [], "new": []}
    prev = _aggregate(child_id, prev_start, prev_end, tz)
    out = {"available": True, "message": None, "increasing": [], "decreasing": [], "stable": [], "new": []}
    cats = set(agg["by_category"]) | set(prev["by_category"])
    if agg["total"] < MIN_COMPARE_SECONDS or prev["total"] < MIN_COMPARE_SECONDS:
        out.update(available=False, message="There is not enough activity in both periods to describe trends yet. "
                   "Trends appear after a little more history.")
        return out
    for c in sorted(cats):
        cur, before = agg["by_category"].get(c, 0.0), prev["by_category"].get(c, 0.0)
        kind = classify(cur, before)
        if kind == "insufficient":
            continue
        out[kind].append({"category": c, "label": label_for(c), "current_minutes": _minutes(cur), "previous_minutes": _minutes(before),
                          "change_pct": pct_change(cur, before)})
    for key in ("increasing", "decreasing", "stable", "new"):
        out[key].sort(key=lambda r: (-r["current_minutes"], r["category"]))
    return out


def rankings(child_id, agg, like_rows, reactions, lo, hi):
    """Top lists for 'content engagement': most watched / replayed / listened / viewed / explored / used features."""
    def top(types, key, limit=6):
        rows = [(cid, e) for cid, e in agg["by_content"].items()
                if agg["content"].get(cid) and agg["content"][cid].content_type in types]
        rows.sort(key=lambda kv: (-key(kv[1]), kv[0]))
        return [{"content": content_card(agg["content"].get(cid)), "minutes": _minutes(e["seconds"]), "sessions": e["sessions"],
                 "replays": e["replays"], "completions": e["completions"], "plays": e["sessions"] + e["replays"],
                 "completion_pct": round(e["best_completion"]) if e["best_completion"] is not None else None}
                for cid, e in rows[:limit] if key(e) > 0]

    explored = defaultdict(int)
    for category, n in agg["by_cat_sessions"].items():
        explored[category] += n
    features = defaultdict(int)
    for et, cid, cat, stop, n in like_rows:
        if et == "browse" and cat:
            explored[cat] += n
        if et == "view":
            features[stop] += n
    return {
        "most_watched_videos": top(("video", "short"), lambda e: e["seconds"]),
        "most_replayed": top(("video", "short", "song"), lambda e: e["replays"] + max(0, e["sessions"] - 1)),
        "most_listened_songs": top(("song",), lambda e: e["seconds"]),
        "most_viewed_pictures": top(("picture",), lambda e: (e["sessions"] * 60 + e["seconds"])),
        "most_explored_categories": [{"category": c, "label": label_for(c), "count": n, "color": CATEGORIES.get(c, {}).get("color", "#7a8794")}
                                     for c, n in sorted(explored.items(), key=lambda kv: (-kv[1], kv[0]))[:6]],
        "most_used_features": [{"stop": s, "label": STOP_LABELS.get(s, s.title()), "visits": n}
                               for s, n in sorted(features.items(), key=lambda kv: (-kv[1], kv[0]))[:6]],
    }


# ------------------------------------------------------------------ public: bucketed series (day / week / month)
def series(child_id, group, start, end, tz=0):
    """Engagement time + counts grouped by local day, week (Monday) or month, across [start, end]."""
    tz = clamp_tz(tz)
    agg = _aggregate(child_id, start, end, tz)
    buckets = defaultdict(lambda: {"seconds": 0.0, "sessions": 0, "completions": 0, "replays": 0})
    for row in agg["rows"]:
        day = _local(row.created_at, tz).date()
        key = (day.isoformat() if group == "day" else (day - timedelta(days=day.weekday())).isoformat() if group == "week"
               else day.strftime("%Y-%m"))
        b = buckets[key]
        b["seconds"] += agg["eff"].get(row.id, 0.0)
        b["sessions"] += 1
        b["completions"] += 1 if row.completed else 0
        b["replays"] += row.replay_count or 0
    return [{"period": k, "minutes": _minutes(v["seconds"]), "sessions": v["sessions"], "completions": v["completions"],
             "replays": v["replays"]} for k, v in sorted(buckets.items())]


# ------------------------------------------------------------------ public: timeline for one day
def timeline(child_id, day, tz=0):
    """The chosen local day, in order: what came first, what followed, how long each lasted."""
    tz = clamp_tz(tz)
    lo, hi = _bounds(day, day, tz)
    rows = (Session.query(ActivityEvent).filter(ActivityEvent.child_id == child_id, ActivityEvent.created_at >= lo,
                                                ActivityEvent.created_at < hi, ActivityEvent.event_type != "search")
            .order_by(ActivityEvent.created_at.asc(), ActivityEvent.id.asc()).all())
    content = _content_map(rows)
    sessions = [r for r in rows if r.event_type in SESSIONS]
    eff = effective_seconds(sessions)
    out = []
    for row in rows:
        if row.event_type == "view" and (row.duration_seconds or 0) < 5:
            continue                                        # a pass-through page load is noise, not an activity
        item = content.get(row.content_id)
        local = _local(row.created_at, tz)
        out.append({"id": row.id, "iso": row.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"), "time": local.strftime("%H:%M"),
                    "hour": local.hour, "action": row.event_type, "action_label": ACTION_LABELS.get(row.event_type, row.event_type.title()),
                    "stop": row.stop, "stop_label": STOP_LABELS.get(row.stop, row.stop.title()),
                    "seconds": int(round(eff.get(row.id, row.duration_seconds or 0))) if row.event_type in SESSIONS else int(row.duration_seconds or 0),
                    "engagement": row.event_type in SESSIONS, "content_type": _ctype(row, item) if row.content_id else "other",
                    "category": _category(row, item), "category_label": label_for(_category(row, item)) if _category(row, item) else None,
                    "content": content_card(item, row.content_title) if row.content_id else None,
                    "completion_pct": round(row.completion_pct) if row.completion_pct is not None else None,
                    "completed": bool(row.completed), "replays": row.replay_count or 0})
    by_cat = defaultdict(float)
    for row in sessions:
        c = _category(row, content.get(row.content_id))
        if c:
            by_cat[c] += eff.get(row.id, 0.0)
    return {"date": day.isoformat(), "events": out,
            "by_category": [{"category": c, "label": label_for(c), "color": CATEGORIES.get(c, {}).get("color", "#7a8794"),
                             "minutes": _minutes(s)} for c, s in sorted(by_cat.items(), key=lambda kv: -kv[1]) if s > 0],
            "first": out[0]["time"] if out else None, "last": out[-1]["time"] if out else None}


# ------------------------------------------------------------------ public: searchable, filterable, paginated history
TYPE_FILTERS = {"video": ("video",), "short": ("short",), "song": ("song",), "picture": ("picture",)}


def history(child_id, tz=0, content_type=None, action=None, category=None, q=None, start=None, end=None, page=1, per_page=20,
            visits=True):
    """Every recorded event (newest first) with optional filters. ``q`` matches the content title only (never stored search text)."""
    tz = clamp_tz(tz)
    per_page = max(1, min(int(per_page or 20), 50))
    page = max(1, int(page or 1))
    query = Session.query(ActivityEvent).filter(ActivityEvent.child_id == child_id, ActivityEvent.event_type != "search")
    query = query.outerjoin(ContentItem, ContentItem.id == ActivityEvent.content_id)
    if not visits:                                           # the recent feed leaves out plain page visits
        query = query.filter(ActivityEvent.event_type != "view")
    if start or end:
        lo, hi = _bounds(start or date(2000, 1, 1), end or date(2100, 1, 1), tz)
        query = query.filter(ActivityEvent.created_at >= lo, ActivityEvent.created_at < hi)
    if content_type == "other":
        query = query.filter(ActivityEvent.content_id.is_(None))
    elif content_type in TYPE_FILTERS:
        query = query.filter(or_(ActivityEvent.content_type.in_(TYPE_FILTERS[content_type]),
                                 (ActivityEvent.content_type.is_(None)) & (ContentItem.content_type.in_(TYPE_FILTERS[content_type]))))
    if action and action in activity_service.EVENT_TYPES:
        query = query.filter(ActivityEvent.event_type == action)
    elif action == "engaged":
        query = query.filter(ActivityEvent.event_type.in_(SESSIONS))
    if category and category in CATEGORIES:
        query = query.filter(or_(ActivityEvent.category == category,
                                 (ActivityEvent.category.is_(None)) & (ContentItem.category == category)))
    if q:
        term = "%" + q.strip()[:60].replace("%", r"\%").replace("_", r"\_") + "%"
        query = query.filter(or_(ContentItem.title.ilike(term, escape="\\"), ActivityEvent.content_title.ilike(term, escape="\\")))
    total = query.with_entities(func.count(ActivityEvent.id)).scalar() or 0
    rows = (query.order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())
            .offset((page - 1) * per_page).limit(per_page).with_entities(ActivityEvent).all())
    content = _content_map(rows)
    items = [_history_row(row, content.get(row.content_id), tz) for row in rows]
    return {"items": items, "page": page, "per_page": per_page, "total": total, "pages": max(1, -(-total // per_page)),
            "has_more": page * per_page < total}


def _history_row(row, item, tz):
    local = _local(row.created_at, tz)
    category = _category(row, item)
    return {"id": row.id, "iso": row.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"), "date": local.date().isoformat(), "time": local.strftime("%H:%M"),
            "action": row.event_type, "action_label": ACTION_LABELS.get(row.event_type, row.event_type.title()),
            "stop": row.stop, "stop_label": STOP_LABELS.get(row.stop, row.stop.title()), "seconds": int(row.duration_seconds or 0),
            "engagement": row.event_type in SESSIONS, "content_type": _ctype(row, item) if row.content_id else "other",
            "category": category, "category_label": label_for(category) if category else None,
            "completion_pct": round(row.completion_pct) if row.completion_pct is not None else None, "completed": bool(row.completed),
            "replays": row.replay_count or 0, "pauses": row.pause_count or 0, "resumes": row.resume_count or 0,
            "measured": bool(row.measured), "content": content_card(item, row.content_title) if row.content_id else None}


def detail(child_id, event_id, tz=0):
    """One event plus the child's whole history with that content (for the 'open this record' dialog). None if not this child's."""
    tz = clamp_tz(tz)
    row = Session.query(ActivityEvent).filter_by(id=event_id, child_id=child_id).first()
    if not row:
        return None
    item = Session.get(ContentItem, row.content_id) if row.content_id else None
    data = _history_row(row, item, tz)
    data["content_seconds"] = row.content_seconds
    data["viewer"] = None
    if item:
        from services import content_service as cs
        card = cs.serialise([item], child_id)[0]
        data["viewer"] = {"type": card["type"], "title": card["title"], "thumb": card["thumb"], "embed": card["embed"],
                          "url": card["url"] if card["provider"] != "demo" else None, "provider": card["provider"],
                          "attribution": card["attribution"]}
        mine = (Session.query(ActivityEvent).filter(ActivityEvent.child_id == child_id, ActivityEvent.content_id == item.id).all())
        sessions = [r for r in mine if r.event_type in SESSIONS]
        eff = effective_seconds(sessions)
        data["content_history"] = {
            "sessions": len(sessions), "minutes": _minutes(sum(eff.values())), "replays": sum(r.replay_count or 0 for r in sessions),
            "completions": sum(1 for r in sessions if r.completed), "likes": sum(1 for r in mine if r.event_type == "like"),
            "favorites": sum(1 for r in mine if r.event_type == "favorite"), "skips": sum(1 for r in mine if r.event_type == "next"),
            "first_seen": min(r.created_at for r in mine).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_seen": max(r.created_at for r in mine).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return data


# ------------------------------------------------------------------ My World: what the child did at ONE stop
STOP_EVENTS = SESSIONS + ("open", "like", "favorite")          # events that mean "the child actually dealt with this content"
STOP_TYPES = {"video": "video", "song": "song", "picture": "picture", "short": "short"}


def _scope_clause(scope):
    """SQL for 'content that belongs to this stop': by content type, by category, or by a tag equal to one of the stop's categories.
    scope = {'all': bool, 'types': (...), 'cats': (...)}. Nothing else is ever matched, so unrelated content cannot appear."""
    if scope.get("all"):
        return None
    parts = []
    if scope.get("types"):
        parts.append(ContentItem.content_type.in_(tuple(scope["types"])))
    for cat in scope.get("cats") or ():
        parts.append(ContentItem.category == cat)
        parts.append(ContentItem.tags_json.like(f'%"{cat}"%'))
    return or_(*parts) if parts else (ContentItem.id < 0)


def _stop_query(query, child_id, scope, start, end, tz):
    query = query.filter(ActivityEvent.child_id == child_id, ActivityEvent.event_type.in_(STOP_EVENTS),
                         ActivityEvent.content_id.isnot(None))
    clause = _scope_clause(scope)
    if clause is not None:
        query = query.filter(clause)
    if start or end:
        lo, hi = _bounds(start or date(2000, 1, 1), end or date(2100, 1, 1), tz)
        query = query.filter(ActivityEvent.created_at >= lo, ActivityEvent.created_at < hi)
    return query


def _artist(item):
    import json
    try:
        att = json.loads(item.attribution_json or "{}") or {}
    except ValueError:
        att = {}
    return att.get("artist") or att.get("artists") or att.get("channel") or att.get("photographer") or None


def stop_activity(child_id, scope, content_type=None, start=None, end=None, tz=0, page=1, per_page=12):
    """The child's real content at one stop: one card per piece of content, newest first, with views, time, completion, replays.
    Counts per type ignore the type filter so the filter chips can show them."""
    tz = clamp_tz(tz)
    per_page = max(1, min(int(per_page or 12), 30))
    page = max(1, int(page or 1))
    joined = lambda q: q.join(ContentItem, ContentItem.id == ActivityEvent.content_id)
    counts = {t: 0 for t in STOP_TYPES}
    for ctype, n in _stop_query(joined(Session.query(ContentItem.content_type, func.count(func.distinct(ActivityEvent.content_id)))),
                                child_id, scope, start, end, tz).group_by(ContentItem.content_type).all():
        if ctype in counts:
            counts[ctype] = n
    counts["all"] = sum(counts.values())
    grouped = _stop_query(joined(Session.query(ActivityEvent.content_id, func.max(ActivityEvent.created_at).label("last"))),
                          child_id, scope, start, end, tz)
    if content_type in STOP_TYPES:
        grouped = grouped.filter(ContentItem.content_type == STOP_TYPES[content_type])
    grouped = grouped.group_by(ActivityEvent.content_id)
    total = grouped.count()
    page_rows = (grouped.order_by(func.max(ActivityEvent.created_at).desc(), ActivityEvent.content_id.desc())
                 .offset((page - 1) * per_page).limit(per_page).all())
    ids = [cid for cid, _ in page_rows]
    items = []
    if ids:
        events = _stop_query(Session.query(ActivityEvent).filter(ActivityEvent.content_id.in_(ids)).join(
            ContentItem, ContentItem.id == ActivityEvent.content_id), child_id, scope, start, end, tz).order_by(
            ActivityEvent.created_at.asc(), ActivityEvent.id.asc()).all()
        content = {c.id: c for c in Session.query(ContentItem).filter(ContentItem.id.in_(ids)).all()}
        by_content = defaultdict(list)
        for ev in events:
            by_content[ev.content_id].append(ev)
        for cid, last in page_rows:
            evs, item = by_content.get(cid, []), content.get(cid)
            if item is None or not evs:
                continue
            sessions = [e for e in evs if e.event_type in SESSIONS]
            seconds = sum(effective_seconds(sessions).values())
            opens = sum(1 for e in evs if e.event_type == "open")
            completions = [e.completion_pct for e in sessions if e.completion_pct is not None]
            replays = sum(e.replay_count or 0 for e in sessions)
            local = _local(last, tz)
            reactions = sum(1 for e in evs if e.event_type in ("like", "favorite"))
            items.append({
                "content": content_card(item), "artist": _artist(item), "views": max(len(sessions), opens),
                "minutes": _minutes(seconds), "seconds": int(round(seconds)), "completion_pct": round(max(completions)) if completions else None,
                "completed": any(e.completed for e in sessions), "replays": replays, "plays": len(sessions) + replays,
                "interactions": len(evs), "reactions": reactions, "measured": any(e.measured for e in sessions),
                "last_iso": last.strftime("%Y-%m-%dT%H:%M:%SZ"), "last_date": local.date().isoformat(), "last_time": local.strftime("%H:%M"),
                "first_date": _local(evs[0].created_at, tz).date().isoformat()})
    other = _stop_other(child_id, scope, start, end, tz)
    return {"items": items, "counts": counts, "total": total, "page": page, "per_page": per_page, "pages": max(1, -(-total // per_page)),
            "has_more": page * per_page < total, "other": other, "any_activity": counts["all"] > 0}


def _stop_other(child_id, scope, start, end, tz):
    """Other meaningful activity for the stop: favorites, likes, skips and categories explored."""
    out = {"favorites": 0, "likes": 0, "skips": 0, "explored": 0}
    base = Session.query(ActivityEvent.event_type, func.count(ActivityEvent.id)).join(ContentItem, ContentItem.id == ActivityEvent.content_id)
    base = base.filter(ActivityEvent.child_id == child_id, ActivityEvent.event_type.in_(("favorite", "like", "next")))
    clause = _scope_clause(scope)
    if clause is not None:
        base = base.filter(clause)
    lo = hi = None
    if start or end:
        lo, hi = _bounds(start or date(2000, 1, 1), end or date(2100, 1, 1), tz)
        base = base.filter(ActivityEvent.created_at >= lo, ActivityEvent.created_at < hi)
    for et, n in base.group_by(ActivityEvent.event_type).all():
        out[{"favorite": "favorites", "like": "likes", "next": "skips"}[et]] = n
    cats = tuple(scope.get("cats") or ())
    if cats and not scope.get("all"):
        q = Session.query(func.count(ActivityEvent.id)).filter(ActivityEvent.child_id == child_id, ActivityEvent.event_type == "browse",
                                                              ActivityEvent.category.in_(cats))
        if lo is not None:
            q = q.filter(ActivityEvent.created_at >= lo, ActivityEvent.created_at < hi)
        out["explored"] = q.scalar() or 0
    return out


def stop_content_records(child_id, scope, content_id, start=None, end=None, tz=0):
    """Every recorded event for ONE piece of content, but only if that content belongs to the stop (else None)."""
    tz = clamp_tz(tz)
    belongs = _stop_query(Session.query(ActivityEvent.id).join(ContentItem, ContentItem.id == ActivityEvent.content_id).filter(
        ActivityEvent.content_id == content_id), child_id, scope, None, None, tz).first()
    if not belongs:
        return None
    item = Session.get(ContentItem, content_id)
    rows = _stop_query(Session.query(ActivityEvent).join(ContentItem, ContentItem.id == ActivityEvent.content_id).filter(
        ActivityEvent.content_id == content_id), child_id, scope, start, end, tz).order_by(
        ActivityEvent.created_at.desc(), ActivityEvent.id.desc()).limit(200).all()
    from services import content_service as cs
    card = cs.serialise([item], child_id)[0]
    sessions = [r for r in rows if r.event_type in SESSIONS]
    completions = [r.completion_pct for r in sessions if r.completion_pct is not None]
    return {"content": content_card(item), "artist": _artist(item),
            "viewer": {"type": card["type"], "title": card["title"], "thumb": card["thumb"], "embed": card["embed"],
                       "url": card["url"] if card["provider"] != "demo" else None, "attribution": card["attribution"]},
            "totals": {"views": max(len(sessions), sum(1 for r in rows if r.event_type == "open")),
                       "minutes": _minutes(sum(effective_seconds(sessions).values())), "replays": sum(r.replay_count or 0 for r in sessions),
                       "completion_pct": round(max(completions)) if completions else None},
            "records": [_history_row(r, item, tz) for r in rows]}


# ------------------------------------------------------------------ "watched" lists: exactly what the child opened, newest first
HISTORY_INTERACTIONS = ("selected", "watched", "like", "favorite")      # older reactions (before activity tracking) that also mean "the child chose this"


def watched_cards(child_id, scope, content_type=None, limit=24, tz=0):
    """The child's own content at a stop / of a type: [{content_id, last_event_id, views, minutes, seconds, completion_pct, replays,
    last_iso, last_date, last_time}] newest first, plus the total. Built from recorded activity AND the older interaction history,
    so a child who used the app before tracking existed still sees what they chose. Never anything that was only recommended."""
    tz = clamp_tz(tz)
    last = {}
    last_event = {}
    q = _stop_query(Session.query(ActivityEvent.content_id, func.max(ActivityEvent.created_at), func.max(ActivityEvent.id))
                    .join(ContentItem, ContentItem.id == ActivityEvent.content_id), child_id, scope, None, None, tz)
    if content_type in STOP_TYPES:
        q = q.filter(ContentItem.content_type == STOP_TYPES[content_type])
    for cid, at, eid in q.group_by(ActivityEvent.content_id).all():
        last[cid], last_event[cid] = at, eid
    h = (Session.query(Interaction.content_item_id, func.max(Interaction.occurred_at))
         .join(ContentItem, ContentItem.id == Interaction.content_item_id)
         .filter(Interaction.child_profile_id == child_id, Interaction.interaction_type.in_(HISTORY_INTERACTIONS)))
    clause = _scope_clause(scope)
    if clause is not None:
        h = h.filter(clause)
    if content_type in STOP_TYPES:
        h = h.filter(ContentItem.content_type == STOP_TYPES[content_type])
    for cid, at in h.group_by(Interaction.content_item_id).all():
        if cid and (cid not in last or at > last[cid]):
            last[cid] = at
    order = sorted(last, key=lambda c: (last[c], c), reverse=True)
    total, ids = len(order), order[:limit]
    stats = defaultdict(list)
    if ids:
        for ev in Session.query(ActivityEvent).filter(ActivityEvent.child_id == child_id, ActivityEvent.content_id.in_(ids),
                                                      ActivityEvent.event_type.in_(STOP_EVENTS)).order_by(ActivityEvent.created_at.asc()).all():
            stats[ev.content_id].append(ev)
    out = []
    for cid in ids:
        evs = stats.get(cid, [])
        sessions = [e for e in evs if e.event_type in SESSIONS]
        seconds = sum(effective_seconds(sessions).values())
        opens = sum(1 for e in evs if e.event_type == "open")
        pcts = [e.completion_pct for e in sessions if e.completion_pct is not None]
        local = _local(last[cid], tz)
        out.append({"content_id": cid, "last_event_id": last_event.get(cid), "views": max(len(sessions), opens, 1),
                    "minutes": _minutes(seconds), "seconds": int(round(seconds)), "completion_pct": round(max(pcts)) if pcts else None,
                    "replays": sum(e.replay_count or 0 for e in sessions), "last_iso": last[cid].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "last_date": local.date().isoformat(), "last_time": local.strftime("%H:%M")})
    return out, total
