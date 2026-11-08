""""Watched" vs "Recommended": the content a child really opened, kept apart from what we suggest next.

Used by the My World stop sheets (child, caretaker, parent preview and share link) and by the caretaker dashboard's Content section.
Watched items come only from recorded activity and the older interaction history; recommended items come from the normal
recommendation pipeline and never repeat something already watched.
"""
from database.db import Session
from database.models import ContentItem
from services import activity_analytics_service as an
from services import age_service, content_service as cs, recommendation_service as rec, safety, settings_service
from services.categories import CATEGORIES, label_for

KINDS = {"video": "video", "short": "short", "song": "song", "picture": "picture"}


def _block(owner, child):
    return cs.blocklist_for(settings_service.caregiver_settings(owner.id), child.age_years)


def watched(owner, child, scope, content_type=None, limit=24, tz=0, safe=True):
    """{'items': [serialised content + w_views / w_minutes / w_last / w_event], 'total': n}. `safe=True` also hides content the caregiver
    has since blocked or the child disliked (the child's own screens); the caretaker's detailed history is never filtered."""
    cards, total = an.watched_cards(child.id, scope, content_type, limit, tz)
    if not cards:
        return {"items": [], "total": 0}
    rows = {r.id: r for r in Session.query(ContentItem).filter(ContentItem.id.in_([c["content_id"] for c in cards])).all()}
    hidden = rec.disliked_ids(child.id) if safe else set()
    block = _block(owner, child) if safe else []
    kept = [c for c in cards if c["content_id"] in rows and c["content_id"] not in hidden
            and (not safe or safety.is_allowed(rows[c["content_id"]].title, rows[c["content_id"]].description, block))]
    served = cs.serialise([rows[c["content_id"]] for c in kept], child.id)
    items = []
    for card, item in zip(kept, served):
        item = dict(item)
        item.update(w_views=card["views"], w_minutes=card["minutes"], w_seconds=card["seconds"], w_completion=card["completion_pct"],
                    w_replays=card["replays"], w_date=card["last_date"], w_time=card["last_time"], w_event=card["last_event_id"])
        items.append(item)
    return {"items": items, "total": max(len(items), total - (len(cards) - len(kept)))}


def recommended(owner, child, content_type, exclude_ids=(), n=12, seed=None):
    """New suggestions of one content type from the child's top interests (age-appropriate, blocklist applied, nothing already watched)."""
    kind = KINDS.get(content_type)
    if not kind:
        return {"items": [], "notice": None}
    block, age = _block(owner, child), child.age_years
    picks = rec.pick_feed_categories(child.id, n=3, age=age)
    skip, out, notice = set(exclude_ids) | rec.disliked_ids(child.id), [], None
    for category, reason in picks:
        if category not in CATEGORIES or category not in age_service.allowed_categories(age):
            continue
        models, nt = cs.fetch_models(kind, category, "", 1, 8, block, age, seed=seed)
        notice = notice or nt
        fresh = [m for m in models if m.id not in skip]
        for item in cs.serialise(fresh, child.id):
            item = dict(item)
            item["reason"] = reason or label_for(category)
            item["reason_label"] = label_for(category)
            out.append(item)
            skip.add(item["id"])
        if len(out) >= n:
            break
    return {"items": out[:n], "notice": notice}
