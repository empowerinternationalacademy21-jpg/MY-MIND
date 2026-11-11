"""The 2D My World for children: a flat, friendly island with ten stops, and one themed room per stop.

This sits on top of the existing My World engine (services/world_service.py) and does not replace it:
  * the theme, caregiver settings, hidden stops and sports zones all come from world_service;
  * "Watched" comes from watched_service (what the child really opened, recorded by the activity tracker);
  * "Recommended" is loaded by the room page from the existing, safety-filtered /api/pictures|videos|music|shots endpoints,
    so the caregiver's blocklist, age rules and "not for me" choices apply exactly as they do everywhere else.
Everything is scoped to the signed-in child's id (g.child); nothing here takes a child id from the request.
Nothing is inferred about the child: a star only says "you opened this a lot", and skipping a stop never changes anything.
"""
from database.db import Session
from database.models import Favorite
from services import settings_service, watched_service, world_service as ws
from services.categories import CATEGORIES

# the ten stops, in the order they wind down the island
ORDER = ("music", "sports", "animals", "nature", "food", "colors", "pictures", "videos", "shots", "journey")

JOURNEY = dict(label="My Journey", icon="rocket", color="#ff8a3d", blurb="See everything you have done.")

# what each room offers: the topic (?category=) and the kinds of content, first = shown first
ROOMS = {
    "music":    dict(cat="music",   kinds=("music", "videos")),
    "sports":   dict(cat="sports",  kinds=("videos", "pictures")),
    "animals":  dict(cat="animals", kinds=("pictures", "videos")),
    "nature":   dict(cat="nature",  kinds=("pictures", "videos")),
    "food":     dict(cat="food",    kinds=("pictures", "videos")),
    "colors":   dict(cat="colors",  kinds=("pictures", "videos")),
    "pictures": dict(cat=None,      kinds=("pictures",)),
    "videos":   dict(cat=None,      kinds=("videos",)),
    "shots":    dict(cat=None,      kinds=("shots",)),
    "journey":  dict(cat=None,      kinds=()),
}
KIND_LABELS = {"pictures": ("Pictures", "image"), "videos": ("Videos", "clapperboard"), "music": ("Music", "music"), "shots": ("Shorts", "zap")}

# a few friendly things floating around the island (x, y in the 100 x 220 scene)
DECOR_SPOTS = ((6, 24), (94, 40), (7, 74), (93, 100), (6, 128), (94, 158), (7, 194), (93, 224))
TREES = ((4, 50), (96, 68), (4, 104), (96, 132), (4, 164), (96, 186), (4, 222), (96, 238))
FLOWERS = ((50, 18), (46, 66), (54, 112), (50, 146), (46, 182), (54, 212), (50, 236))
CLOUDS = ((18, 7, 1.0), (72, 12, 0.8), (40, 92, 0.7))

SCENE_W, SCENE_H = 100, 250


def _label(key):
    return JOURNEY["label"] if key == "journey" else ws.STOP_DEFS[key]["label"]


def _def(key):
    return JOURNEY if key == "journey" else ws.STOP_DEFS[key]


def _shown(key, w, shots_ok):
    """A stop is on the island unless the caregiver hid it or switched Shorts off. The first nine are always there (no waiting for 'evidence')."""
    if key == "journey":
        return True
    if key in w["hidden_stops"]:
        return False
    return not (key == "shots" and not shots_ok)


def _shots_ok(user):
    return settings_service.get("shots_enabled") == "1" and settings_service.caregiver_settings(user.id)["shots_enabled"]


def _path(points):
    """Smooth 'M x,y C ...' road through the stops."""
    if not points:
        return ""
    d = "M%.1f,%.1f" % points[0]
    px, py = points[0]
    for x, y in points[1:]:
        ym = (py + y) / 2
        d += " C%.1f,%.1f %.1f,%.1f %.1f,%.1f" % (px, ym, x, ym, x, y)
        px, py = x, y
    return d


def layout(keys):
    """[(key, x, y)]: stops zig-zag between two columns, evenly spaced down the island (pure, so it is easy to test)."""
    n = len(keys)
    top, bottom = 24.0, SCENE_H - 26.0
    step = (bottom - top) / (n - 1) if n > 1 else 0
    return [(k, 26 if i % 2 == 0 else 74, round(top + i * step, 1)) for i, k in enumerate(keys)]


def scene(user, child):
    """Everything the map page needs."""
    w = ws.get_settings(user.id)
    interests, found = ws.activity_interests(child.id)
    theme_key, _, _ = ws.resolve_theme(interests, w)
    theme = ws.THEMES[theme_key]
    shots_ok = _shots_ok(user)
    keys = [k for k in ORDER if _shown(k, w, shots_ok)]
    stops = []
    for key, x, y in layout(keys):
        d = _def(key)
        inter = ws.stop_interest(key, found) if key in ws.STOP_DEFS else None
        stops.append({"key": key, "label": d["label"], "icon": d["icon"], "color": d["color"], "blurb": d["blurb"], "x": x, "y": y,
                      "pct_x": round(x, 1), "pct_y": round(y / SCENE_H * 100, 2), "star": bool(inter and inter["level"] > 0)})
    decor_icon = theme["icon"] if theme_key != "mixed" else "flower-2"
    return {"child": {"name": child.display_name}, "stops": stops, "path": _path([(50, 6)] + [(s["x"], s["y"]) for s in stops]),
            "palette": {k: theme[k] for k in ("sky", "water", "grass", "sand", "accent")}, "theme_label": theme["label"] if theme_key != "mixed" else "",
            "decor": [{"x": x, "y": y, "icon": decor_icon if i % 2 == 0 else "flower-2", "i": i} for i, (x, y) in enumerate(DECOR_SPOTS)],
            "trees": TREES, "flowers": FLOWERS, "clouds": CLOUDS, "w": SCENE_W, "h": SCENE_H,
            "motion": bool(w["animation"]) and not w["reduced_motion"]}


def room(user, child, key):
    """Data for one room, or None when there is no such stop (or the caregiver hid it)."""
    if key not in ROOMS:
        return None
    w = ws.get_settings(user.id)
    shots_ok = _shots_ok(user)
    if not _shown(key, w, shots_ok):
        return None
    interests, _ = ws.activity_interests(child.id)
    theme_key, _, _ = ws.resolve_theme(interests, w)
    theme = ws.THEMES[theme_key]
    d = _def(key)
    cfg = ROOMS[key]
    out = {"key": key, "label": d["label"], "icon": d["icon"], "color": d["color"], "blurb": d["blurb"], "cat": cfg["cat"],
           "kinds": [{"key": k, "label": KIND_LABELS[k][0], "icon": KIND_LABELS[k][1]} for k in cfg["kinds"] if k != "shots" or shots_ok],
           "palette": {k: theme[k] for k in ("sky", "grass", "accent")}, "characters": [], "interior": None, "zones": [], "flavors": [],
           "watched": {"items": [], "total": 0}, "milestones": None, "motion": bool(w["animation"]) and not w["reduced_motion"]}
    if key == "journey":
        out["watched"] = watched_service.watched(user, child, ws.activity_scope("home"), limit=24)
        out["milestones"] = _milestones(child, out["watched"]["total"], interests)
        return out
    detail = ws.stop_detail(user, child, key, force=True) or {}
    out["watched"] = detail.get("watched") or out["watched"]
    out["characters"] = [c["url"] for c in (detail.get("characters") or [])[:3]]
    out["interior"] = detail.get("interior")
    out["zones"] = detail.get("zones") or []
    out["flavors"] = detail.get("flavors") or []
    return out


def _milestones(child, watched_total, interests):
    """Three happy counters. Counts only: no scores, no comparisons, nothing that reads as a judgement."""
    favourites = Session.query(Favorite).filter(Favorite.child_profile_id == child.id).count()
    topics = len([i for i in interests if i["category"] in CATEGORIES and i["evidence"] > 0])
    return [{"icon": "play", "label": "Things I watched", "value": watched_total},
            {"icon": "heart", "label": "My favourites", "value": favourites},
            {"icon": "sparkles", "label": "Topics I tried", "value": topics}]
