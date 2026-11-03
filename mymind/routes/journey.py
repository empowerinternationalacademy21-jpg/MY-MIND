import calendar
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify, abort
from sqlalchemy import func
from database.db import Session
from database.models import Interaction, DailyActivity, InterestProfile, Favorite, ContentItem, utcnow
from services import recommendation_service as rec
from services.categories import label_for
from routes.helpers import subscribed_required

bp = Blueprint("journey", __name__)
VERBS = {"like": "Liked", "dislike": "Chose “not for me” on", "favorite": "Favorited", "watched": "Watched", "selected": "Opened",
         "explore": "Explored more like", "skip": "Skipped", "caregiver_adjust": "Caregiver adjusted interest in"}
NOUNS = {"picture": "picture", "video": "video", "short": "short video", "song": "song"}


def parse_day(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def day_range(d):
    start = datetime.combine(d, datetime.min.time())
    return start, start + timedelta(days=1)


def day_summary(child_id, d):
    """Built ONLY from stored events (app interactions + caregiver records)."""
    a, b = day_range(d)
    rows = (Session.query(Interaction).filter(Interaction.child_profile_id == child_id, Interaction.occurred_at >= a,
                                              Interaction.occurred_at < b).order_by(Interaction.occurred_at).all())
    groups = Counter()
    for r in rows:
        ctype = r.content.content_type if r.content else None
        groups[(r.interaction_type, ctype, r.category)] += 1
    lines = []
    for (itype, ctype, cat), n in groups.items():
        what = NOUNS.get(ctype, "topic")
        lines.append(f"{VERBS.get(itype, itype)} {n} {label_for(cat).lower()} {what}{'s' if n > 1 and ctype else ''}" if ctype
                     else f"{VERBS.get(itype, itype)} {label_for(cat).lower()}")
    acts = Session.query(DailyActivity).filter_by(child_profile_id=child_id, activity_date=d).order_by(DailyActivity.id).all()
    return {"date": d.isoformat(), "app_events": lines, "total_events": len(rows),
            "recorded": [{"id": x.id, "title": x.title, "notes": x.notes or "", "type": x.activity_type, "source": x.source} for x in acts],
            "timeline": [{"time": r.occurred_at.strftime("%H:%M"), "text": f"{VERBS.get(r.interaction_type, r.interaction_type)} "
                          f"{r.content.title if r.content else label_for(r.category)}"} for r in rows][:60]}


def month_markers(child_id, first, last):
    a, _ = day_range(first)
    _, b = day_range(last)
    app, rec_days = defaultdict(int), defaultdict(int)
    for (t,) in Session.query(Interaction.occurred_at).filter(Interaction.child_profile_id == child_id,
                                                              Interaction.occurred_at >= a, Interaction.occurred_at < b):
        app[t.date()] += 1
    for (d,) in Session.query(DailyActivity.activity_date).filter(DailyActivity.child_profile_id == child_id,
                                                                  DailyActivity.activity_date >= first, DailyActivity.activity_date <= last):
        rec_days[d] += 1
    return app, rec_days


def trends(child_id, weeks=6):
    today = utcnow().date()
    start_week = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
    table = defaultdict(lambda: [0] * weeks)
    q = Session.query(Interaction.category, Interaction.occurred_at).filter(
        Interaction.child_profile_id == child_id, Interaction.occurred_at >= datetime.combine(start_week, datetime.min.time()),
        Interaction.interaction_type.in_(["like", "favorite", "watched", "explore", "selected"]), Interaction.category.isnot(None))
    for cat, t in q:
        idx = (t.date() - start_week).days // 7
        if 0 <= idx < weeks:
            table[cat][idx] += 1
    top = sorted(table.items(), key=lambda kv: -sum(kv[1]))[:5]
    labels = [(start_week + timedelta(weeks=i)).strftime("%d %b") for i in range(weeks)]
    peak = max([max(v) for _, v in top] + [1])
    return {"labels": labels, "rows": [{"label": label_for(c), "values": v, "peak": peak} for c, v in top]}


@bp.route("/journey")
@subscribed_required
def view():
    today = utcnow().date()
    mode = "week" if request.args.get("view") == "week" else "month"
    sel = parse_day(request.args.get("date")) or today
    if mode == "week":
        first = sel - timedelta(days=sel.weekday())
        days = [first + timedelta(days=i) for i in range(7)]
        weeks, last = [days], days[-1]
        prev_d, next_d = first - timedelta(days=7), first + timedelta(days=7)
    else:
        first = sel.replace(day=1)
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        weeks = [[d if d.month == first.month else None for d in w] for w in calendar.Calendar(0).monthdatescalendar(first.year, first.month)]
        prev_d, next_d = first - timedelta(days=1), last + timedelta(days=1)
    app, rec_days = month_markers(g.child.id, first, last)
    month_ago = utcnow() - timedelta(days=30)
    new_interests = [r for r in rec.get_interests(g.child.id) if r["first_observed_at"] and r["first_observed_at"] >= month_ago and r["evidence"] > 0]
    favs = (Session.query(ContentItem).join(Favorite, Favorite.content_item_id == ContentItem.id)
            .filter(Favorite.child_profile_id == g.child.id).order_by(Favorite.id.desc()).limit(30).all())
    freq = (Session.query(Interaction.category, func.count(Interaction.id)).filter(
        Interaction.child_profile_id == g.child.id, Interaction.interaction_type.in_(["like", "favorite", "watched", "explore", "selected"]),
        Interaction.category.isnot(None)).group_by(Interaction.category).order_by(func.count(Interaction.id).desc()).limit(6).all())
    return render_template("journey.html", weeks=weeks, mode=mode, first=first, today=today, selected=sel, app=app, rec=rec_days,
                           prev=prev_d, next=next_d, summary=day_summary(g.child.id, sel), trends=trends(g.child.id),
                           new_interests=new_interests, freq=[(label_for(c), n) for c, n in freq], active="journey",
                           fav_pics=[f for f in favs if f.content_type == "picture"], fav_vids=[f for f in favs if f.content_type in ("video", "short")],
                           fav_songs=[f for f in favs if f.content_type == "song"])


@bp.route("/api/journey/day/<day>")
@subscribed_required
def day_api(day):
    d = parse_day(day) or abort(404)
    return jsonify(day_summary(g.child.id, d))


@bp.route("/journey/activity", methods=["POST"])
@subscribed_required
def add_activity():
    d = parse_day(request.form.get("activity_date")) or utcnow().date()
    title = (request.form.get("title") or "").strip()[:200]
    if not title:
        flash("Please describe the activity.", "error")
        return redirect(url_for("journey.view", date=d.isoformat()))
    Session.add(DailyActivity(child_profile_id=g.child.id, activity_type="activity", title=title,
                              notes=(request.form.get("notes") or "").strip()[:500], source="caregiver", activity_date=d))
    Session.commit()
    flash("Activity recorded.", "success")
    return redirect(url_for("journey.view", date=d.isoformat()))


@bp.route("/journey/activity/<int:act_id>/delete", methods=["POST"])
@subscribed_required
def delete_activity(act_id):
    act = Session.get(DailyActivity, act_id)
    if not act or act.child_profile_id != g.child.id:    # ownership check
        abort(404)
    d = act.activity_date
    Session.delete(act); Session.commit()
    flash("Record deleted.", "success")
    return redirect(url_for("journey.view", date=d.isoformat()))


@bp.route("/journey/clear", methods=["POST"])
@subscribed_required
def clear():
    scope = request.form.get("scope")
    q = Session.query(Interaction).filter(Interaction.child_profile_id == g.child.id)
    if scope == "day":
        d = parse_day(request.form.get("date")) or abort(400)
        a, b = day_range(d)
        q = q.filter(Interaction.occurred_at >= a, Interaction.occurred_at < b)
    elif scope != "all":
        abort(400)
    n = q.delete(synchronize_session=False)
    Session.commit()
    flash(f"Deleted {n} app activity record(s). Interest scores are kept; reset them in My World if you wish.", "success")
    return redirect(url_for("journey.view"))
