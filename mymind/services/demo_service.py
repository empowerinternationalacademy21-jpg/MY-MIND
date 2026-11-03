"""Deterministic DEMO content, used when API keys are missing or a provider is down.
Everything here is labelled as demo content in the UI (provider == 'demo')."""
import os, re
from services.categories import CATEGORIES

_ICON_CACHE = {}


def _icon_inner(name):
    if not _ICON_CACHE:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "_icons.html")
        for m in re.finditer(r'<symbol id="i-([a-z0-9-]+)"[^>]*>(.*?)</symbol>', open(path, encoding="utf-8").read(), re.S):
            _ICON_CACHE[m.group(1)] = m.group(2)
    return _ICON_CACHE.get(name, "")

def _kw(category, i):
    kws = CATEGORIES.get(category, CATEGORIES["objects"])["keywords"]
    return kws[i % len(kws)]

def _slice(items, page, n):
    return items[(page - 1) * n: page * n] if page > 0 else items[:n]

def pictures(category, page=1, n=8):
    cat = category if category in CATEGORIES else "objects"
    out = []
    for i in range((page - 1) * n, page * n):
        kw = _kw(cat, i)
        out.append(dict(provider="demo", provider_content_id=f"pic-{cat}-{i}", content_type="picture",
                        title=f"{kw.title()} (demo picture)", description="Demo illustration",
                        thumbnail_url=f"/demo-art/{cat}/{i}.svg", canonical_url="", category=cat,
                        tags=[kw, cat], attribution={"source": "MyMind demo art"}))
    return out

def videos(category, page=1, n=6, short=False):
    cat = category if category in CATEGORIES else "objects"
    out = []
    for i in range((page - 1) * n, page * n):
        kw = _kw(cat, i)
        out.append(dict(provider="demo", provider_content_id=f"{'short' if short else 'vid'}-{cat}-{i}",
                        content_type="short" if short else "video",
                        title=f"{kw.title()} for kids (demo {'short' if short else 'video'})", description="Demo placeholder. Add a YouTube API key to see real videos.",
                        thumbnail_url=f"/demo-art/{cat}/{i + 20}.svg", canonical_url="", category=cat,
                        tags=[kw, cat], attribution={"source": "demo"}))
    return out

def songs(category, page=1, n=6):
    cat = category if category in CATEGORIES else "objects"
    out = []
    for i in range((page - 1) * n, page * n):
        kw = _kw(cat, i)
        out.append(dict(provider="demo", provider_content_id=f"song-{cat}-{i}", content_type="song",
                        title=f"{kw.title()} Song (demo)", description="Demo placeholder. Add Spotify credentials to see real tracks.",
                        thumbnail_url=f"/demo-art/{cat}/{i + 40}.svg", canonical_url="", category=cat,
                        tags=[kw, cat], attribution={"artist": "Demo Artist", "album": "Demo Album"}))
    return out

PALETTE = ["#ffe3e8", "#e3f2ff", "#e6f7e1", "#fff3d1", "#efe5ff", "#dcf5f1"]

def art_svg(category, n):
    cat = category if category in CATEGORIES else "objects"
    meta = CATEGORIES[cat]
    bg = PALETTE[n % len(PALETTE)]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300" role="img" aria-label="{meta["label"]} demo illustration">'
            f'<rect width="400" height="300" fill="{bg}"/><circle cx="{80 + (n*53)%240}" cy="{60 + (n*37)%90}" r="{50 + n%3*12}" fill="{meta["color"]}" opacity=".18"/>'
            f'<circle cx="{300 - (n*29)%200}" cy="{230 - (n*17)%60}" r="{40 + n%4*9}" fill="{meta["color"]}" opacity=".25"/>'
            f'<g transform="translate(140 80) scale(5)" fill="none" stroke="#14233f" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">{_icon_inner(meta["icon"])}</g>'
            f'<text x="200" y="272" font-size="16" text-anchor="middle" fill="#42526e" font-family="sans-serif">demo picture</text></svg>')
