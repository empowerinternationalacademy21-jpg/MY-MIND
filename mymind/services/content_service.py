"""Fetch (real or demo) content, apply safety filters, persist to content_items, and serialise for the UI.

Source order for every kind of content:
  1. the live provider (Pexels / YouTube; songs: Spotify first, then YouTube Music)
  2. items saved earlier in our own database (so scrolling never dries up when a quota is used up)
  3. clearly labelled demo content
"""
import html
import random
import json
import re
from urllib.parse import parse_qs, urlparse
from flask import current_app
from sqlalchemy.exc import IntegrityError
from database.db import Session
from database.models import ContentItem, Favorite, Interaction
from services import (youtube_service, spotify_service, image_service, demo_service, safety, settings_service,
                      age_service, recommendation_service as rec)
from services.cache import cache_get, cache_set
from services.categories import CATEGORIES
from services.errors import ServiceError

SPOTIFY_OFF = ("sp", "off")         # set for a few minutes after Spotify fails, so we don't retry it on every request
SPOTIFY_OFF_SECONDS = 600


def _key(d):
    return (d["provider"], d["content_type"], d["provider_content_id"])


def _build(d):
    thumbnail_url = d.get("thumbnail_url") or ""
    if not thumbnail_url:
        video_id = youtube_video_id(d)
        if video_id:
            thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    return ContentItem(provider=d["provider"], provider_content_id=d["provider_content_id"], content_type=d["content_type"],
                       title=d["title"][:300], description=(d.get("description") or "")[:500],
                       thumbnail_url=thumbnail_url[:600], canonical_url=(d.get("canonical_url") or "")[:600],
                       category=d.get("category") if d.get("category") in CATEGORIES else "objects",
                       tags_json=json.dumps(d.get("tags", [])), attribution_json=json.dumps(d.get("attribution", {})))


def upsert(d):
    """Single-item upsert (kept for callers that only have one item)."""
    return upsert_many([d])[0]


def upsert_many(dicts):
    """Persist many items with one SELECT per (provider, type) and a single COMMIT.

    Every database call is an HTTPS round-trip to Turso, so this replaces the old one-SELECT-per-item loop.
    Returns models in the same order as `dicts`.
    """
    if not dicts:
        return []
    keys = [_key(d) for d in dicts]

    def load():
        found = {}
        for prov, ctype in {(p, t) for p, t, _ in keys}:
            ids = list({c for p, t, c in keys if p == prov and t == ctype})
            for it in Session.query(ContentItem).filter(ContentItem.provider == prov,
                                                        ContentItem.content_type == ctype,
                                                        ContentItem.provider_content_id.in_(ids)):
                found[(it.provider, it.content_type, it.provider_content_id)] = it
        return found

    found = load()
    added = False
    for d, k in zip(dicts, keys):
        if k in found:
            continue
        item = _build(d)
        Session.add(item)
        found[k] = item
        added = True
    if added:
        try:
            Session.commit()
        except IntegrityError:          # another request inserted the same item first
            Session.rollback()
            found = load()
    return [found[k] for k in keys if k in found]


def blocklist_for(user_settings, age=None):
    """Admin words + caregiver words + (for younger children) the age band's extra words."""
    admin = settings_service.get_all()
    return (safety.parse_keywords(admin.get("blocked_keywords")) + safety.parse_keywords(user_settings.get("avoid_keywords"))
            + age_service.extra_blocklist(age))


def _topic_round(category, q, page, age=None, seed=None):
    """Pick the search words and the 'round' (which provider page of that search) for an endless-scroll page.

    No free-text search: each page uses the NEXT keyword of the category (variety); once every keyword was used,
    the cycle starts again on the provider's next result page (round 2, 3, ...).
    With free-text search: the same words every time, and page N is the provider's page N.

    `seed` (a number the page picks once per visit) makes every visit different without making scrolling inconsistent:
    the keyword ORDER is shuffled by the seed and the provider page starts at a seed-chosen offset, so two visits begin
    with different searches and different photos, while the pages of one visit still follow on from each other.
    """
    q = (q or "").strip()
    if q:
        return q, page
    kws = age_service.keywords_for(category if category in CATEGORIES else "objects", age) or ["kids"]
    if seed is not None:
        kws = list(kws)
        random.Random(f"{seed}:{category}").shuffle(kws)
    rnd = (page - 1) // len(kws) + 1
    if seed is not None:
        rnd += random.Random(f"{seed}:round").randint(0, VARIETY_PAGE_SPREAD)
    return kws[(page - 1) % len(kws)], rnd


VARIETY_PAGE_SPREAD = 4         # a visit may start up to this many provider pages deep (more variety, still relevant photos)


def _provider_items(kind, topic, category, rnd, n, age=None):
    """Live results, or None when no provider is configured. Raises ServiceError when the provider fails."""
    if kind == "picture":
        return image_service.search_images(topic, category, rnd, n) if image_service.configured() else None
    audience = age_service.audience_for(age)
    if kind in ("video", "short"):
        return (youtube_service.search_videos(topic, category, n, short=(kind == "short"), page=rnd, audience=audience)
                if youtube_service.configured() else None)
    # songs: Spotify when it works, otherwise YouTube's Music category (plays with audio and video)
    if spotify_service.configured() and cache_get(SPOTIFY_OFF) is None:
        try:
            return spotify_service.search_tracks(f"{topic} {audience}".strip(), category, n, page=rnd)
        except ServiceError as exc:
            current_app.logger.warning("provider failure (song/spotify): %s — using YouTube music for a while", exc)
            cache_set(SPOTIFY_OFF, True, SPOTIFY_OFF_SECONDS)
    if youtube_service.configured():
        return youtube_service.search_music(topic, category, n, page=rnd, audience=audience)
    return None


def _stored(kind, category, n, page, seed=None):
    """Real (non-demo) items we saved earlier, `n` per page. Newest first, or in a seed-specific order (different every
    visit, stable while scrolling one visit). Used when live search is unavailable."""
    query = (Session.query(ContentItem)
             .filter(ContentItem.content_type == kind, ContentItem.provider != "demo", ContentItem.category == category))
    if seed is None:
        query = query.order_by(ContentItem.id.desc())
    else:
        query = query.order_by(((ContentItem.id * (int(seed) % 9973 * 2 + 1)) % 100003), ContentItem.id)
    rows = query.offset((max(1, page) - 1) * n).limit(n).all()
    return [dict(provider=r.provider, provider_content_id=r.provider_content_id, content_type=r.content_type,
                 title=r.title, description=r.description, thumbnail_url=r.thumbnail_url, canonical_url=r.canonical_url,
                 category=r.category, tags=json.loads(r.tags_json or "[]"),
                 attribution=json.loads(r.attribution_json or "{}")) for r in rows]


def fetch(kind, category="objects", q="", page=1, n=8, block=None, age=None, seed=None):
    """kind: picture | video | short | song. Returns (list[dict], notice|None). Never raises.
    `age` (3-25, or None) picks the age band's search words, audience word and demo labels.
    `seed` (pictures only) makes this visit show different pictures from the last one (see _topic_round)."""
    if kind != "picture":
        seed = None                                     # videos/songs cost provider quota and keep their steady behaviour
    topic, rnd = _topic_round(category, q, page, age, seed)
    notice = None
    items = None
    try:
        items = _provider_items(kind, topic, category, rnd, n, age)
        if seed is not None and items == [] and rnd > 1 and not (q or "").strip():
            items = _provider_items(kind, topic, category, (page - 1) // max(1, len(age_service.keywords_for(
                category if category in CATEGORIES else "objects", age) or [1])) + 1, n, age)   # started too deep: fall back to the first pages
    except ServiceError as exc:
        current_app.logger.warning("provider failure (%s): %s", kind, exc)
        notice = exc.user_message
    if items is None:                                   # provider missing or failed
        try:
            items = _stored(kind, category, n, page, seed) or None
        except Exception as exc:                        # a database hiccup must not break the page
            current_app.logger.warning("saved-items lookup failed (%s): %s", kind, exc)
            items = None
        if items:
            notice = "Live search is busy right now, so you are seeing items saved earlier." if notice else None
    if items is None:
        if notice is None:
            if kind == "video" and not youtube_service.configured():
                notice = "Live video search isn't set up yet. You can still watch this sample video."
            else:
                notice = "Showing demo content. Add API keys in .env to see real results."
        if kind == "picture":
            items = demo_service.pictures(category, page, n, age, offset=_demo_offset(seed, n))
        elif kind in ("video", "short"):
            items = demo_service.videos(category, page, n, short=(kind == "short"), age=age)
        else:
            items = demo_service.songs(category, page, n, age)
        if q:   # demo content ignores free text, but keep a polite match on the topic
            items = [dict(i, title=f"{q.title()} · {i['title']}") for i in items] if len(q) < 40 else items
    items = safety.filter_items(items, block)
    if seed is not None and kind == "picture":          # same photos can still arrive in the same order: mix them per visit
        items = list(items)
        random.Random(f"{seed}:{page}:mix").shuffle(items)
    return items, notice


def _demo_offset(seed, n):
    """Demo art has no real catalogue; start each visit a few pages further in so it does not look identical either."""
    return 0 if seed is None else (int(seed) % 5) * n * 3


def fetch_models(kind, category, q, page, n, block, age=None, seed=None):
    dicts, notice = fetch(kind, category, q, page, n, block, age, seed)
    return upsert_many(dicts), notice


def thumb_for(i):
    """Prefer the stored image, then derive a YouTube frame, then use themed demo art."""
    if i.thumbnail_url:
        return i.thumbnail_url
    video_id = youtube_video_id(i)
    if video_id:
        return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    return f"/demo-art/{i.category if i.category in CATEGORIES else 'objects'}/1.svg"


def youtube_video_id(item):
    if isinstance(item, dict):
        provider = item.get("provider")
        provider_content_id = item.get("provider_content_id")
        att = item.get("attribution") or {}
        canonical_url = item.get("canonical_url") or ""
    else:
        provider = item.provider
        provider_content_id = item.provider_content_id
        att = json.loads(item.attribution_json or "{}")
        canonical_url = item.canonical_url or ""
    candidate = provider_content_id if provider == "youtube" else att.get("youtube_video_id")
    if isinstance(candidate, str) and re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        return candidate

    url = canonical_url
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host == "youtu.be":
            candidate = parsed.path.strip("/").split("/")[0]
        elif (host == "youtube.com" or host.endswith(".youtube.com")
              or host == "youtube-nocookie.com" or host.endswith(".youtube-nocookie.com")):
            parts = [part for part in parsed.path.split("/") if part]
            candidate = (parse_qs(parsed.query).get("v") or [None])[0]
            if not candidate and len(parts) >= 2 and parts[0] in ("embed", "shorts", "live", "v"):
                candidate = parts[1]
        else:
            candidate = None
    except ValueError:
        candidate = None
    if candidate and re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        return candidate
    fallback = provider_content_id if provider == "youtube" else att.get("youtube_video_id")
    return fallback if isinstance(fallback, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", fallback) else None


def serialise(items, profile_id):
    ids = [i.id for i in items]
    favs = {f for (f,) in Session.query(Favorite.content_item_id).filter(Favorite.child_profile_id == profile_id,
                                                                         Favorite.content_item_id.in_(ids or [0])).all()}
    last = {}
    for cid, t in (Session.query(Interaction.content_item_id, Interaction.interaction_type)
                   .filter(Interaction.child_profile_id == profile_id, Interaction.content_item_id.in_(ids or [0]),
                           Interaction.interaction_type.in_(["like", "dislike"])).order_by(Interaction.id)):
        last[cid] = t
    out = []
    for i in items:
        att = json.loads(i.attribution_json or "{}")
        embed = None
        video_id = youtube_video_id(i) if i.content_type in ("video", "short", "song") else None
        if video_id:
            embed = f"https://www.youtube-nocookie.com/embed/{video_id}?rel=0&modestbranding=1"
        elif i.provider == "spotify":
            embed = f"https://open.spotify.com/embed/track/{i.provider_content_id}"
        # (titles saved earlier with &amp; are repaired here too)
        out.append({"id": i.id, "type": i.content_type, "title": html.unescape(i.title),
                    "thumb": thumb_for(i), "url": i.canonical_url,
                    "provider": i.provider, "provider_content_id": i.provider_content_id,
                    "video_id": video_id, "demo": i.provider == "demo", "embed": embed, "category": i.category,
                    "category_label": CATEGORIES.get(i.category, {}).get("label", i.category), "attribution": att,
                    "favorite": i.id in favs, "reaction": last.get(i.id)})
    return out


def related_bundle(profile_id, content, block, age=None):
    """Pictures + videos + songs related to one liked picture/video/song (via anonymous topic keywords)."""
    terms = rec.related_terms(content, age=age)
    hidden = rec.disliked_ids(profile_id) | {content.id}
    bundle, notices = {}, []
    for key, kind, n in (("pictures", "picture", 6), ("videos", "video", 4), ("songs", "song", 4)):
        found = []
        for t in terms:
            models, notice = fetch_models(kind, content.category, t, 1, n, block, age)
            if notice:
                notices.append(notice)
            found += [m for m in models if m.id not in hidden and m not in found]
        bundle[key] = serialise(found[:n], profile_id)
    return bundle, (notices[0] if notices else None)
