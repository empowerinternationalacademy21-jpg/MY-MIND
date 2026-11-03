"""Pexels image search (server-side). We store only URLs + attribution — never the image files.
Pexels requires attribution to the photographer / Pexels; we keep it in attribution_json and show it."""
import requests
from flask import current_app
from services.cache import cache_get, cache_set
from services.errors import ServiceError


def configured():
    return bool(current_app.config.get("PEXELS_API_KEY"))


def map_photo(p, category):
    return dict(provider="pexels", provider_content_id=str(p["id"]), content_type="picture",
                title=(p.get("alt") or "Photo")[:300], description=p.get("alt") or "",
                thumbnail_url=(p.get("src") or {}).get("large") or (p.get("src") or {}).get("medium", ""),
                canonical_url=p.get("url", ""), category=category, tags=[],
                attribution={"photographer": p.get("photographer", ""), "photographer_url": p.get("photographer_url", ""),
                             "source": "Pexels", "source_url": "https://www.pexels.com"})


def search_images(query, category="objects", page=1, per_page=8):
    query = (query or "").strip()[:80]
    if not query:
        return []
    per_page = max(1, min(int(per_page), 20))
    page = max(1, min(int(page), 20))
    key = ("px", query, category, page, per_page)
    hit = cache_get(key)
    if hit is not None:
        return hit
    try:
        r = requests.get("https://api.pexels.com/v1/search", params={"query": query, "per_page": per_page, "page": page},
                         headers={"Authorization": current_app.config["PEXELS_API_KEY"]}, timeout=8)
    except requests.RequestException as exc:
        raise ServiceError("Pictures are unavailable right now.", str(exc))
    if r.status_code == 429:
        raise ServiceError("Picture search is busy. Showing demo pictures.", "rate limited")
    if r.status_code != 200:
        raise ServiceError("Pictures are unavailable right now.", f"http {r.status_code}")
    items = [map_photo(p, category) for p in r.json().get("photos", [])]
    cache_set(key, items, 3600)       # short cache, consistent with provider rules (no long-term hoarding)
    return items
