"""Spotify Web API (client-credentials flow, server-side). Metadata + Spotify embeds/links only.
We do NOT assume full-song streaming or preview URLs; playback is via Spotify's official embed.

Spotify's Development Mode rules (since Feb 2026): search returns at most 10 results per request, and the Spotify
account that OWNS the app (the developer dashboard account) must have an active Premium subscription, otherwise the
API answers 403. The error message Spotify sends back is now included in the log line so the cause is visible."""
import time
import requests
from flask import current_app
from services.cache import cache_get, cache_set
from services.errors import ServiceError

_token = {"value": None, "exp": 0}
MAX_LIMIT = 10            # Development Mode cap for /search


def configured():
    c = current_app.config
    return bool(c.get("SPOTIFY_CLIENT_ID") and c.get("SPOTIFY_CLIENT_SECRET"))


def _err_text(r):
    """Short, log-safe description of a Spotify error response."""
    try:
        j = r.json()
        e = j.get("error")
        if isinstance(e, dict):
            return str(e.get("message") or e)[:200]
        return str(j.get("error_description") or e or j)[:200]
    except ValueError:
        return (r.text or "")[:200]


def _access_token():
    if _token["value"] and _token["exp"] > time.time() + 30:
        return _token["value"]
    c = current_app.config
    try:
        r = requests.post("https://accounts.spotify.com/api/token", data={"grant_type": "client_credentials"},
                          auth=(c["SPOTIFY_CLIENT_ID"], c["SPOTIFY_CLIENT_SECRET"]), timeout=8)
    except requests.RequestException as exc:
        raise ServiceError("Music is unavailable right now.", str(exc))
    if r.status_code != 200:
        raise ServiceError("Music is unavailable right now.", f"token http {r.status_code}: {_err_text(r)}")
    j = r.json()
    _token.update(value=j["access_token"], exp=time.time() + int(j.get("expires_in", 3600)))
    return _token["value"]


def _api(path, params, retry=True):
    try:
        r = requests.get(f"https://api.spotify.com/v1/{path}", params=params,
                         headers={"Authorization": f"Bearer {_access_token()}"}, timeout=8)
    except requests.RequestException as exc:
        raise ServiceError("Music is unavailable right now.", str(exc))
    if r.status_code == 401 and retry:      # expired token -> refresh once
        _token["value"] = None
        return _api(path, params, retry=False)
    if r.status_code == 429:
        raise ServiceError("Music search is busy. Please try again in a moment.", "rate limited")
    if r.status_code != 200:
        raise ServiceError("Music is unavailable right now.", f"http {r.status_code}: {_err_text(r)}")
    return r.json()


def map_track(t, category):
    images = (t.get("album") or {}).get("images") or []
    art = images[1]["url"] if len(images) > 1 else (images[0]["url"] if images else "")
    artists = ", ".join(a.get("name", "") for a in t.get("artists", []))
    return dict(provider="spotify", provider_content_id=t["id"], content_type="song", title=t.get("name", "")[:300],
                description=f"{artists} — {(t.get('album') or {}).get('name', '')}"[:300], thumbnail_url=art,
                canonical_url=(t.get("external_urls") or {}).get("spotify", ""), category=category, tags=[],
                attribution={"artist": artists, "album": (t.get("album") or {}).get("name", ""), "source": "Spotify",
                             "explicit": bool(t.get("explicit")),
                             "duration": int(t.get("duration_ms", 0) / 1000) or None})


def search_tracks(query, category="music", max_results=8, page=1):
    """One page of tracks. `page` > 1 uses Spotify's `offset`, so endless scrolling keeps returning new songs."""
    query = (query or "").strip()[:80]
    if not query:
        return []
    page = max(1, int(page or 1))
    limit = MAX_LIMIT                                  # always ask for the maximum; explicit tracks are filtered out below
    key = ("sp", query, category, max_results, page)
    hit = cache_get(key)
    if hit is not None:
        return hit
    data = _api("search", {"q": query, "type": "track", "limit": limit, "offset": (page - 1) * limit})
    items = [map_track(t, category) for t in data.get("tracks", {}).get("items", []) if t and t.get("id")]
    items = [i for i in items if not i["attribution"].get("explicit")]       # skip explicit tracks
    cache_set(key, items, 3600)
    return items