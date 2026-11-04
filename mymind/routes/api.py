"""JSON endpoints used by the vanilla-JS front end. All require an active, onboarded caregiver."""
import re
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request, g, abort, current_app
from sqlalchemy.exc import IntegrityError
from database.db import Session
from database.models import ActivityEvent, ContentItem, Favorite, Interaction, utcnow
from services import activity_service, content_service as cs, recommendation_service as rec, settings_service, age_service
from services.categories import CATEGORIES, PICTURE_CATEGORIES
from routes.helpers import subscribed_required

bp = Blueprint("api", __name__, url_prefix="/api")
REACTIONS = {"like", "dislike", "skip", "selected", "watched", "explore"}
MAX_PAGES = 50          # endless scrolling stops here (keeps API quota use bounded)


def _age():
    """The child's age (3-25) or None. Drives age-appropriate categories, search words and safety words."""
    return getattr(g.child, "age_years", None)


def _block():
    return cs.blocklist_for(settings_service.caregiver_settings(g.user.id), _age())


def _cat():
    c = request.args.get("category") or request.args.get("cat", "")
    return c if c in age_service.allowed_categories(_age()) else ""


def _page():
    try:
        return max(1, min(int(request.args.get("page", 1)), MAX_PAGES))
    except ValueError:
        return 1


def _q():
    return (request.args.get("q") or "").strip()[:60]


def _listing(kind, n):
    """One page of an endless-scroll listing.

    Without a chosen category or search, successive pages rotate through the child's top categories so the stream
    stays varied (like YouTube's home feed); content_service then rotates keywords inside each category.
    """
    cat, q, page = _cat(), _q(), _page()
    sub = page                                   # page number *within* the chosen category / search
    if not cat and not q:
        picks = rec.pick_feed_categories(g.child.id, 4, age=_age())
        cats = [c for c, _ in picks] or [age_service.allowed_categories(_age())[0]]
        cat = cats[(page - 1) % len(cats)]
        sub = (page - 1) // len(cats) + 1
    cat = cat or ("objects" if _age() is None else age_service.allowed_categories(_age())[0])
    models, notice = cs.fetch_models(kind, cat, q, sub, n, _block(), _age())
    hidden = rec.disliked_ids(g.child.id)
    models = [m for m in models if m.id not in hidden]
    return jsonify(items=cs.serialise(models, g.child.id), notice=notice, category=cat,
                   more=page < MAX_PAGES)


@bp.route("/pictures")
@subscribed_required
def pictures():
    return _listing("picture", 20)


@bp.route("/videos")
@subscribed_required
def videos():
    return _listing("video", 12)


@bp.route("/shots")
@subscribed_required
def shots():
    if not settings_service.caregiver_settings(g.user.id)["shots_enabled"] or settings_service.get("shots_enabled") != "1":
        return jsonify(error="Short videos are switched off.", items=[]), 403
    return _listing("short", 8)


@bp.route("/music")
@subscribed_required
def music():
    return _listing("song", 10)


@bp.route("/feed")
@subscribed_required
def feed():
    page = _page()
    block = _block()
    chosen = _cat()                              # topic chip on the home page: show only that topic
    picks = [(chosen, "You picked this topic")] if chosen else rec.pick_feed_categories(g.child.id, 4, age=_age())
    shown = rec.recently_shown_ids(g.child.id)
    hidden = rec.disliked_ids(g.child.id)
    sections, notice = [], None
    for idx, (cat, reason) in enumerate(picks):
        items = []
        # YouTube searches cost API quota, so only the first two sections get a video row and a song row
        plan = [("picture", 4)] + ([("video", 3)] if idx < 2 else []) + ([("song", 3)] if idx < 2 else [])
        for kind, n in plan:
            models, nt = cs.fetch_models(kind, cat, "", page, n, block, _age())
            notice = notice or nt
            models = [m for m in models if m.id not in hidden]
            fresh = [m for m in models if m.id not in shown]
            items += (fresh or models)          # prefer unseen items, fall back if nothing else exists
        rec.log_recommendations(g.child.id, items, reason)
        sections.append({"category": cat, "label": CATEGORIES[cat]["label"], "icon": CATEGORIES[cat]["icon"],
                         "reason": reason, "items": cs.serialise(items, g.child.id)})
    return jsonify(sections=sections, notice=notice, page=page, more=page < MAX_PAGES)


@bp.route("/favorites")
@subscribed_required
def favorites():
    rows = (Session.query(ContentItem).join(Favorite, Favorite.content_item_id == ContentItem.id)
            .filter(Favorite.child_profile_id == g.child.id).order_by(Favorite.id.desc()).limit(60).all())
    return jsonify(items=cs.serialise(rows, g.child.id))


@bp.route("/recent")
@subscribed_required
def recent():
    ids, seen = [], set()
    for (cid,) in (Session.query(Interaction.content_item_id)
                   .filter(Interaction.child_profile_id == g.child.id, Interaction.content_item_id.isnot(None),
                           Interaction.interaction_type.in_(["selected", "watched", "like", "explore"]))
                   .order_by(Interaction.id.desc()).limit(60)):
        if cid not in seen:
            seen.add(cid); ids.append(cid)
        if len(ids) >= 8:
            break
    rows = {r.id: r for r in Session.query(ContentItem).filter(ContentItem.id.in_(ids or [0]))}
    return jsonify(items=cs.serialise([rows[i] for i in ids if i in rows], g.child.id))


@bp.route("/related/<int:content_id>")
@subscribed_required
def related(content_id):
    item = Session.get(ContentItem, content_id) or abort(404)
    bundle, notice = cs.related_bundle(g.child.id, item, _block(), _age())
    return jsonify(source=cs.serialise([item], g.child.id)[0], notice=notice, **bundle)


@bp.route("/react", methods=["POST"])
@subscribed_required
def react():
    data = request.get_json(silent=True) or {}
    rtype = data.get("type")
    item = Session.get(ContentItem, data.get("content_id")) if isinstance(data.get("content_id"), int) else None
    if rtype not in REACTIONS or not item:
        return jsonify(error="Invalid request."), 400
    recent = (Session.query(Interaction).filter(Interaction.child_profile_id == g.child.id,
                                                Interaction.content_item_id == item.id,
                                                Interaction.interaction_type == rtype,
                                                Interaction.occurred_at > utcnow() - timedelta(seconds=30)).first())
    if not recent:                      # ignore rapid duplicate taps so they can't inflate scores
        if rtype in {"selected", "watched", "like", "explore"} and not item.thumbnail_url:
            item.thumbnail_url = cs.thumb_for(item)
        rec.record_interaction(g.child.id, item, rtype)
    return jsonify(ok=True, type=rtype, counted=not recent)


@bp.route("/favorite", methods=["POST"])
@subscribed_required
def favorite():
    data = request.get_json(silent=True) or {}
    item = Session.get(ContentItem, data.get("content_id")) if isinstance(data.get("content_id"), int) else None
    if not item:
        return jsonify(error="Invalid request."), 400
    fav = Session.query(Favorite).filter_by(child_profile_id=g.child.id, content_item_id=item.id).first()
    if fav:
        Session.delete(fav); Session.commit()
        rec.record_interaction(g.child.id, item, "unfavorite")
        return jsonify(ok=True, favorite=False)
    Session.add(Favorite(child_profile_id=g.child.id, content_item_id=item.id)); Session.commit()
    rec.record_interaction(g.child.id, item, "favorite")
    return jsonify(ok=True, favorite=True)


@bp.route("/activity-events", methods=["POST"])
@subscribed_required
def activity_events():
    """Accept buffered events independently of child-facing actions; retry IDs make heartbeats idempotent."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error="Invalid activity batch."), 400
    events = data.get("events")
    if not isinstance(events, list) or not events or len(events) > 50:
        return jsonify(error="Invalid activity batch."), 400

    parsed, content_ids, event_ids = [], set(), set()
    event_id_re = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
    for event in events:
        if not isinstance(event, dict):
            return jsonify(error="Invalid activity event."), 400
        event_type = event.get("event_type")
        try:
            stop = activity_service.normalize_stop(event.get("stop"))
        except (TypeError, ValueError):
            return jsonify(error="Invalid activity stop."), 400
        event_id = event.get("event_id")
        seconds = event.get("duration_seconds", 0)
        content_id = event.get("content_id")
        if (not isinstance(event_type, str) or event_type not in activity_service.EVENT_TYPES
                or not isinstance(event_id, str) or not event_id_re.fullmatch(event_id)
                or isinstance(seconds, bool) or not isinstance(seconds, int) or not 0 <= seconds <= 604800
                or (content_id is not None and (isinstance(content_id, bool) or not isinstance(content_id, int)))
                or event_id in event_ids):
            return jsonify(error="Invalid activity event."), 400
        event_ids.add(event_id)
        if content_id is not None:
            content_ids.add(content_id)
        parsed.append((event_id, stop, event_type, seconds, content_id))

    content = {item.id: item for item in Session.query(ContentItem).filter(ContentItem.id.in_(content_ids)).all()} if content_ids else {}
    if len(content) != len(content_ids):
        return jsonify(error="Unknown content item."), 400
    if any(event_type == "watch" and content_id is not None
           and content[content_id].content_type not in ("video", "short")
           for _, _, event_type, _, content_id in parsed):
        return jsonify(error="Invalid watched content."), 400

    ids = [row[0] for row in parsed]
    existing = {row.client_event_id: row for row in
                Session.query(ActivityEvent).filter(ActivityEvent.client_event_id.in_(ids)).all()}
    if any(row.child_id != g.child.id for row in existing.values()):
        return jsonify(error="Invalid activity event."), 400

    for event_id, stop, event_type, seconds, content_id in parsed:
        row = existing.get(event_id)
        item = content.get(content_id)
        if row:
            if row.event_type != event_type or row.stop != stop:
                return jsonify(error="Invalid activity event."), 400
            if event_type in ("watch", "view"):
                row.duration_seconds = max(row.duration_seconds, seconds)
            continue
        Session.add(ActivityEvent(
            child_id=g.child.id, stop=stop, content_id=content_id,
            content_title=item.title if item else None, event_type=event_type,
            duration_seconds=seconds, client_event_id=event_id,
        ))

    try:
        Session.commit()
    except IntegrityError:
        Session.rollback()
        current_app.logger.warning("activity batch conflicted during retry")
        return jsonify(error="Activity is temporarily unavailable."), 503
    return jsonify(ok=True, accepted=len(parsed))