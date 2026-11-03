"""YouTube Data API v3 (server-side only). Playback uses the official embedded player.
We never scrape, download or rehost videos. Results are filtered through safeSearch=strict,
embeddable-only, our own keyword blocklist, and (for 'shots') a short-duration check.

Three kinds of search share one engine:  video | short | song  (song = YouTube's Music category, so a song plays as
a music video: you get both the audio and the picture from the official player).

Endless scrolling: page 1 is a normal search. Later pages for the *same* query reuse YouTube's `nextPageToken`
(kept in the cache), so every page returns new items. One search costs 100 quota units, so results are cached.
"""
import html
import re
import requests
from flask import current_app
from services.cache import cache_get, cache_set
from services.errors import ServiceError

API = "https://www.googleapis.com/youtube/v3"
SHORT_MAX_SECONDS = 60
SONG_MIN_SECONDS, SONG_MAX_SECONDS = 30, 600     # skip tiny clips and hour-long mixes
MUSIC_CATEGORY_ID = "10"
CACHE_SECONDS = 3600
MAX_PAGE_DEPTH = 8          # never walk more than this many token pages for one query
END = "END"                 # marker stored when YouTube has no further page


def configured():
    return bool(current_app.config.get("YOUTUBE_API_KEY"))


def _get(path, params):
    params = dict(params, key=current_app.config["YOUTUBE_API_KEY"])
    try:
        r = requests.get(f"{API}/{path}", params=params, timeout=8)
    except requests.RequestException as exc:
        raise ServiceError("Videos are unavailable right now.", str(exc))
    if r.status_code == 403 and "quota" in r.text.lower():
        raise ServiceError("Video search has reached its daily limit. Showing demo content.", "quota")
    if r.status_code != 200:
        raise ServiceError("Videos are unavailable right now.", f"http {r.status_code}: {r.text[:200]}")
    return r.json()


def parse_duration(iso):
    m = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 10 ** 6
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def get_video_metadata(ids):
    """videos.list -> {id: {duration, embeddable, made_for_kids}}"""
    if not ids:
        return {}
    data = _get("videos", {"part": "contentDetails,status", "id": ",".join(ids)})
    out = {}
    for it in data.get("items", []):
        out[it["id"]] = {"duration": parse_duration(it.get("contentDetails", {}).get("duration")),
                         "embeddable": it.get("status", {}).get("embeddable", False),
                         "made_for_kids": it.get("status", {}).get("madeForKids", False)}
    return out


def map_item(raw, category, short=False, duration=None, kind=None):
    """kind: 'video' | 'short' | 'song' (defaults from `short` for older callers)."""
    kind = kind or ("short" if short else "video")
    sn = raw["snippet"]
    vid = raw["id"]["videoId"] if isinstance(raw["id"], dict) else raw["id"]
    thumbs = sn.get("thumbnails", {})
    thumb = ((thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
             or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg")          # always a picture, even if the API sent none
    channel = html.unescape(sn.get("channelTitle", ""))       # the API returns HTML-escaped text (&amp; &#39; ...)
    att = {"channel": channel, "source": "YouTube", "duration": duration}
    if kind == "song":
        att["artist"] = re.sub(r"\s*-\s*Topic$", "", channel)       # auto-generated artist channels end in " - Topic"
    return dict(provider="youtube", provider_content_id=vid, content_type=kind,
                title=html.unescape(sn.get("title", ""))[:300], description=html.unescape(sn.get("description") or "")[:500],
                thumbnail_url=thumb, canonical_url=f"https://www.youtube.com/watch?v={vid}", category=category,
                tags=[], attribution=att)


def _search(query, category, max_results, kind, page):
    query = (query or "").strip()[:80]
    if not query:
        return []
    page = max(1, int(page or 1))
    key = ("yt", query, category, max_results, kind, page)
    hit = cache_get(key)
    if hit is not None:
        return hit

    token = None
    if page > 1:
        token = cache_get(("ytnext", query, kind, page - 1))
        if token is None and page - 1 <= MAX_PAGE_DEPTH:
            _search(query, category, max_results, kind, page - 1)              # fills the token cache
            token = cache_get(("ytnext", query, kind, page - 1))
        if token is None or token == END:
            cache_set(key, [], CACHE_SECONDS)
            return []                                                          # no more results for this query

    q = {"video": f"{query} kids", "short": f"{query} kids #shorts", "song": f"{query} kids song"}[kind]
    ask = min(max_results * (4 if kind == "short" else 2), 50)
    params = {"part": "snippet", "type": "video", "q": q, "maxResults": ask,
              "safeSearch": "strict", "videoEmbeddable": "true", "videoSyndicated": "true",
              "relevanceLanguage": "en", "videoDuration": "short" if kind == "short" else "any"}
    if kind == "song":
        params["videoCategoryId"] = MUSIC_CATEGORY_ID
    if token:
        params["pageToken"] = token
    data = _get("search", params)
    cache_set(("ytnext", query, kind, page), data.get("nextPageToken") or END, CACHE_SECONDS)

    raws = [r for r in data.get("items", []) if r.get("id", {}).get("videoId")]
    meta = get_video_metadata([r["id"]["videoId"] for r in raws])
    items, seen = [], set()
    for r in raws:
        vid = r["id"]["videoId"]
        m = meta.get(vid)
        if not m or not m["embeddable"] or vid in seen:
            continue                      # unavailable / not embeddable / duplicate
        if kind == "short" and m["duration"] > SHORT_MAX_SECONDS:
            continue
        if kind == "song" and not (SONG_MIN_SECONDS <= m["duration"] <= SONG_MAX_SECONDS):
            continue
        seen.add(vid)
        items.append(map_item(r, category, kind=kind, duration=m["duration"]))
    items = items[:max_results * 2]
    cache_set(key, items, CACHE_SECONDS)
    return items


def search_videos(query, category="objects", max_results=8, short=False, page=1):
    """Videos or shorts. Raises ServiceError on failure (caller falls back to saved items / demo).

    `max_results` is the page size we aim for; because non-embeddable / too-long videos are filtered out we ask YouTube
    for more and return everything that passes (up to 2x), so pages stay full instead of shrinking.
    """
    return _search(query, category, max_results, "short" if short else "video", page)


def search_music(query, category="music", max_results=8, page=1):
    """Songs from YouTube's Music category, played through the official embed (audio + video)."""
    return _search(query, category, max_results, "song", page)