"""Caretaker "Activity & interests" dashboard: the page plus its JSON API.

Access is enforced here on the server, never only in the page:
* only a signed-in caregiver (not a child session, not an admin) can reach anything in this module;
* the child is always resolved through ``child_scope`` (active access grant required) and every query is by that child's id;
* a child that is not yours is a 404, exactly like a child that does not exist.
"""
from datetime import date, timedelta

from flask import Blueprint, abort, current_app, g, jsonify, render_template, request, session

from database.db import Session
from database.models import ActivityEvent, utcnow
from routes.helpers import caregiver_required, child_of, has_questionnaire
from services import activity_analytics_service as analytics
from services import activity_service, cache, child_scope, interest_discovery_service as discovery, plan_service

bp = Blueprint("activity_dashboard", __name__)


def _child():
    """The child this request is about: ?child=<public id> (must be authorised for this caregiver) or the selected child."""
    uid = (request.args.get("child") or "").strip()
    if uid:
        child = child_scope.resolve_child_uid(g.user.id, uid)
    else:
        child = child_of(g.user)
    if not child or not child_scope.can_access(g.user.id, child.id):
        abort(404)
    return child


def _tz():
    return analytics.clamp_tz(request.args.get("tz", 0))


def _today(tz):
    return (utcnow() + timedelta(minutes=tz)).date()


def _earliest(tz):
    """First local day the caregiver's plan still lets them look back to."""
    return _today(tz) - timedelta(days=plan_service.history_days(g.user.id) - 1)


def _parse_day(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _range(tz):
    """Selected period -> (key, start, end), always inside [earliest, today] and at most 365 days."""
    today, earliest = _today(tz), _earliest(tz)
    key = request.args.get("range", "7")
    if key == "today":
        start, end = today, today
    elif key == "30":
        start, end = today - timedelta(days=29), today
    elif key == "month":
        start, end = today.replace(day=1), today
    elif key == "custom":
        start, end = _parse_day(request.args.get("start")), _parse_day(request.args.get("end"))
        if not start or not end or start > end or end > today or (end - start).days > 364:
            key, start, end = "7", today - timedelta(days=6), today
    else:
        key, start, end = "7", today - timedelta(days=6), today
    start = max(start, earliest)
    if start > end:
        start = end
    return key, start, end


def _reading_allowed(child):
    return bool(child) and has_questionnaire(child)


@bp.route("/caretaker/activity")
@caregiver_required
def page():
    child = _child() if (request.args.get("child") or child_of(g.user)) else None
    if child is None:
        abort(404)
    # keep children's activity for a bounded time only (at most once a day per server process)
    if not cache.rate_limited("activity-purge", 1, 86400):
        try:
            activity_service.purge_expired(current_app.config.get("ACTIVITY_RETENTION_DAYS", activity_service.DEFAULT_RETENTION_DAYS))
        except Exception:                                              # housekeeping must never break the page
            Session.rollback()
            current_app.logger.warning("activity retention purge failed", exc_info=True)
    children = child_scope.children_for_caregiver(g.user.id).all()
    days = plan_service.history_days(g.user.id)
    return render_template("caretaker_activity.html", child=child, children=children, history_days=days,
                           can_long=plan_service.can_use(g.user.id, "history_30_days"),
                           retention_days=current_app.config.get("ACTIVITY_RETENTION_DAYS", activity_service.DEFAULT_RETENTION_DAYS),
                           is_read_only=plan_service.child_is_read_only(g.user.id, child))


@bp.route("/api/caretaker/activity/summary")
@caregiver_required
def api_summary():
    child, tz = _child(), _tz()
    key, start, end = _range(tz)
    focus = _parse_day(request.args.get("day"))
    data = analytics.summary(child.id, start, end, tz, earliest=_earliest(tz), focus_day=focus)
    data["child"] = {"id": child.public_uid, "name": child.display_name}
    data["range"]["key"] = key
    data["range"]["earliest"] = _earliest(tz).isoformat()
    return jsonify(data)


@bp.route("/api/caretaker/activity/timeline")
@caregiver_required
def api_timeline():
    child, tz = _child(), _tz()
    day = _parse_day(request.args.get("day")) or _today(tz)
    if day > _today(tz) or day < _earliest(tz):
        return jsonify(error="That day is outside your history."), 400
    return jsonify(analytics.timeline(child.id, day, tz))


@bp.route("/api/caretaker/activity/history")
@caregiver_required
def api_history():
    child, tz = _child(), _tz()
    start, end = _parse_day(request.args.get("start")), _parse_day(request.args.get("end"))
    earliest = _earliest(tz)
    start = max(start, earliest) if start else earliest             # never reveal activity older than the plan's history window
    if end and end < start:
        end = start
    try:
        page_no, per_page = int(request.args.get("page", 1)), int(request.args.get("per_page", 20))
    except ValueError:
        page_no, per_page = 1, 20
    result = analytics.history(child.id, tz=tz, content_type=request.args.get("type") or None,
                               action=request.args.get("action") or None, category=request.args.get("category") or None,
                               q=(request.args.get("q") or "").strip()[:60] or None, start=start, end=end,
                               page=page_no, per_page=per_page, visits=request.args.get("visits", "1") != "0")
    return jsonify(result)


@bp.route("/api/caretaker/activity/series")
@caregiver_required
def api_series():
    child, tz = _child(), _tz()
    group = request.args.get("group", "day")
    if group not in ("day", "week", "month"):
        return jsonify(error="Unknown grouping."), 400
    _, start, end = _range(tz)
    if request.args.get("range") is None:                           # no range given: the whole history this plan allows
        start, end = _earliest(tz), _today(tz)
    return jsonify(items=analytics.series(child.id, group, start, end, tz), group=group,
                   start=start.isoformat(), end=end.isoformat())


@bp.route("/api/caretaker/activity/<int:event_id>")
@caregiver_required
def api_detail(event_id):
    child, tz = _child(), _tz()
    # the scoped query is the authorisation check: child id AND caregiver id must both match
    scoped = child_scope.query(ActivityEvent, g.user.id, child.id).filter_by(id=event_id).first()
    if scoped is None:
        abort(404)
    data = analytics.detail(child.id, event_id, tz)
    if data is None or data["date"] < _earliest(tz).isoformat():
        abort(404)
    return jsonify(data)


@bp.route("/api/caretaker/interests")
@caregiver_required
def api_interests():
    child, tz = _child(), _tz()
    return jsonify(discovery.discover(child.id, tz=tz))
