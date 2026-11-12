"""The 2D My World for children: a colourful island map with a stop for each interest, and one themed room per stop.

Built on the existing My World engine (services/world_service.py), not instead of it:
  * theme colours, caregiver settings and hidden stops come from world_service;
  * "Watched" comes from watched_service (what the child really opened, recorded by the activity tracker);
  * "Recommended" is loaded by the room page from the existing, safety-filtered /api/pictures|videos|music|shots endpoints,
    so the caregiver's blocklist, age rules and "not for me" choices apply exactly as they do everywhere else.
Everything is scoped to the signed-in child (g.child); no child id is ever taken from the request.
Nothing is inferred about the child: a star only says "you opened this a lot", and skipping a stop never changes anything.

Artwork: each stop is drawn as an original SVG (templates/_world_art.html). To use your own illustrations instead, drop a PNG/WebP named
after the stop (soccer, music, home, basketball, food, animals, nature, colors, pictures, videos, shots) into static/images/world/ and it is used automatically.
"""
import os
from flask import current_app, url_for
from database.db import Session
from database.models import Favorite
from services import settings_service, watched_service, world_service as ws
from services.categories import CATEGORIES

# the map, in reading order. land = where the stop sits on the wide map (% of width, % of height).
# cat/q = the topic and search words its room uses; scope = which recorded activity belongs to it; hide = the caregiver setting that hides it.
STOPS = {
    "soccer":     dict(label="Soccer Stop", icon="soccer-ball", color="#2e9d57", blurb="Goals, kicks and teamwork.", land=(15.5, 40.0), cat="sports", q="football", kinds=("videos", "pictures"), scope="sports", hide="sports", hello="Let's kick a goal!"),
    "music":      dict(label="Music Stop", icon="music", color="#7c4dd1", blurb="Songs to listen to and dance to.", land=(35.5, 33.0), cat="music", q="", kinds=("music", "videos"), scope="music", hide="music", hello="Let's enjoy some music!"),
    "home":       dict(label="My Home", icon="house", color="#1f78f0", blurb="Your favourite things, all in one cosy place.", land=(53.0, 31.0), cat=None, q="", kinds=(), scope="home", hide=None, hello="Welcome home!"),
    "basketball": dict(label="Basketball Stop", icon="basketball", color="#f0801f", blurb="Bounce, pass and score.", land=(70.5, 33.0), cat="sports", q="basketball", kinds=("videos", "pictures"), scope="sports", hide="sports", hello="Let's shoot some hoops!"),
    "food":       dict(label="Food Stop", icon="apple", color="#f0506a", blurb="Yummy things to look at.", land=(88.0, 38.0), cat="food", q="", kinds=("pictures", "videos"), scope="food", hide="food", hello="Yum! What shall we look at?"),
    "animals":    dict(label="Animals Stop", icon="paw-print", color="#f09a1f", blurb="Furry, feathery and fun friends.", land=(12.5, 72.0), cat="animals", q="", kinds=("pictures", "videos"), scope="animals", hide="animals", hello="Come and meet some friends!"),
    "nature":     dict(label="Nature Stop", icon="trees", color="#2e9d57", blurb="Forests, flowers and the great outdoors.", land=(30.5, 70.0), cat="nature", q="", kinds=("pictures", "videos"), scope="nature", hide="nature", hello="Let's explore outside!"),
    "colors":     dict(label="Colors & Shapes", icon="shapes", color="#7c4dff", blurb="Rainbows, shapes and balloons.", land=(46.5, 75.0), cat="colors", q="", kinds=("pictures", "videos"), scope="colors", hide="colors", hello="Let's find some colours!"),
    "pictures":   dict(label="Pictures Stop", icon="image", color="#2b7de0", blurb="Look at colourful pictures.", land=(60.0, 68.0), cat=None, q="", kinds=("pictures",), scope="pictures", hide=None, hello="Look at all the pictures!"),
    "videos":     dict(label="Videos Stop", icon="clapperboard", color="#e0483f", blurb="Watch videos, one tap at a time.", land=(70.5, 68.0), cat=None, q="", kinds=("videos",), scope="videos", hide=None, hello="Time for a video!"),
    "shots":      dict(label="Shorts Stop", icon="smartphone", color="#8a4fd6", blurb="Quick, short clips.", land=(82.5, 71.0), cat=None, q="", kinds=("shots",), scope="shots", hide=None, hello="Quick and fun clips!"),
    "journey":    dict(label="My Journey", icon="calendar", color="#9a6a3a", blurb="See everything you have done.", land=(8.0, 93.0), cat=None, q="", kinds=(), scope="home", hide=None, hello="Look how far you have come!"),
}
ORDER = tuple(STOPS)
MAIN_STOPS = tuple(k for k in ORDER if k != "journey")        # the journey is the wooden sign; the rest are buildings on islands
KIND_LABELS = {"pictures": ("Pictures", "image"), "videos": ("Videos", "clapperboard"), "music": ("Music", "music"), "shots": ("Shorts", "zap")}

# paths between stops on the wide map (pairs of keys), and which of them get a wooden bridge
LINKS = (("soccer", "music"), ("music", "home"), ("home", "basketball"), ("basketball", "food"), ("soccer", "animals"), ("animals", "nature"),
         ("nature", "colors"), ("colors", "pictures"), ("pictures", "videos"), ("videos", "shots"), ("food", "shots"), ("music", "nature"),
         ("home", "pictures"), ("basketball", "videos"))
BRIDGES = (("nature", "colors"), ("videos", "shots"))

WIDE_W, WIDE_H = 1672, 680            # the wide map's drawing grid
TALL_W = 100                          # the phone map's width; its height depends on how many stops there are


SETTING_HIDDEN, SETTING_ORDER = "world2d_hidden", "world2d_order"
ART_KINDS = ("stop2d", "room2d")            # WorldAsset.kind values for the 2D artwork the admin uploads (stored in the database + asset folder)


def admin_hidden():
    """Stops the admin switched off for everybody (the journey sign can never be switched off)."""
    raw = settings_service.get(SETTING_HIDDEN) or ""
    return {k for k in raw.split(",") if k in STOPS and k != "journey"}


def ordered_keys():
    """Stop keys in the admin's phone-map order. Anything not listed keeps its built-in place after the listed ones."""
    raw = [k for k in (settings_service.get(SETTING_ORDER) or "").split(",") if k in STOPS and k != "journey"]
    seen = []
    for k in raw + [k for k in ORDER if k != "journey"]:
        if k not in seen:
            seen.append(k)
    return tuple(seen) + ("journey",)


def admin_art(kind, key):
    """URL of the newest active artwork the admin uploaded for this stop/room, or None."""
    from database.models import WorldAsset
    row = (Session.query(WorldAsset).filter_by(kind=kind, stop=key, active=True).order_by(WorldAsset.id.desc()).first())
    return f"/world-assets/{row.filename}" if row else None


def _shots_ok(user):
    return settings_service.get("shots_enabled") == "1" and settings_service.caregiver_settings(user.id)["shots_enabled"]


def _shown(key, w, shots_ok):
    """On the map unless the caregiver hid it (Sports hides both ball stops) or switched Shorts off. Never waits for 'evidence'."""
    d = STOPS[key]
    if key in admin_hidden():
        return False
    if d["hide"] and d["hide"] in w["hidden_stops"]:
        return False
    return not (key == "shots" and not shots_ok)


def sprite(key):
    """Artwork for a stop: what the admin uploaded, else a file in static/images/world/, else None (the built-in drawing)."""
    art = admin_art("stop2d", key)
    if art:
        return art
    folder = os.path.join(current_app.static_folder, "images", "world")
    for ext in ("png", "webp"):
        if os.path.isfile(os.path.join(folder, f"{key}.{ext}")):
            return url_for("static", filename=f"images/world/{key}.{ext}")
    return None


def tall_layout(keys):
    """[(key, x, y)] for the phone map: stops zig-zag between two columns, evenly spaced down the island (pure, easy to test)."""
    n = len(keys)
    height = 36 * n + 50
    top, bottom = 24.0, height - 28.0
    step = (bottom - top) / (n - 1) if n > 1 else 0
    return height, [(k, 26 if i % 2 == 0 else 74, round(top + i * step, 1)) for i, k in enumerate(keys)]


def _tall_path(points):
    if not points:
        return ""
    d = "M%.1f,%.1f" % points[0]
    px, py = points[0]
    for x, y in points[1:]:
        ym = (py + y) / 2
        d += " C%.1f,%.1f %.1f,%.1f %.1f,%.1f" % (px, ym, x, ym, x, y)
        px, py = x, y
    return d


def _blob(cx, cy, rx, ry, seed):
    """A friendly wobbly island outline around (cx, cy). Deterministic, so a page always looks the same."""
    import math
    pts = []
    for i in range(10):
        a = i / 10 * 2 * math.pi
        wob = 1 + 0.07 * math.sin(a * 3 + seed) + 0.04 * math.cos(a * 2 + seed * 1.7)
        pts.append((cx + math.cos(a) * rx * wob, cy + math.sin(a) * ry * wob))
    d = "M%.1f,%.1f" % ((pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2)
    for i in range(10):
        p, q = pts[i], pts[(i + 1) % 10]
        d += " Q%.1f,%.1f %.1f,%.1f" % (p[0], p[1], (p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    return d + " Z"


def wide_scene(keys):
    """Islands, paths, bridges and trees for the wide map, as plain numbers for the template to print (pure)."""
    import math
    pos = {k: (STOPS[k]["land"][0] / 100 * WIDE_W, STOPS[k]["land"][1] / 100 * WIDE_H) for k in keys}
    islands = [{"d": _blob(x, y + 28, 125, 84, i * 1.3), "cliff": _blob(x, y + 46, 125, 84, i * 1.3), "x": round(x), "y": round(y)} for i, (k, (x, y)) in enumerate(pos.items()) if k != "journey"]
    paths = []
    for a, b in LINKS:
        if a in pos and b in pos and "journey" not in (a, b):
            (x1, y1), (x2, y2) = pos[a], pos[b]
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2 + 36 * (1 if (x1 + y2) % 2 else -1)
            paths.append("M%.0f,%.0f Q%.0f,%.0f %.0f,%.0f" % (x1, y1 + 60, mx, my + 60, x2, y2 + 60))
    bridges = []
    for a, b in BRIDGES:
        if a in pos and b in pos:
            (x1, y1), (x2, y2) = pos[a], pos[b]
            bridges.append({"x": round((x1 + x2) / 2), "y": round((y1 + y2) / 2 + 62), "r": round(math.degrees(math.atan2(y2 - y1, x2 - x1)), 1)})
    trees = []
    for i, (k, (x, y)) in enumerate(pos.items()):
        if k == "journey":
            continue
        for j, ang in enumerate((200, 235, 300, 335, 20, 160)):         # around the rim, never over the building or its label
            r = math.radians(ang + i * 7)
            trees.append({"x": round(x + math.cos(r) * (100 + 14 * (j % 2))), "y": round(y + 28 + math.sin(r) * (60 + 8 * (j % 2))), "s": round(0.75 + 0.12 * ((i + j) % 3), 2)})
    flowers = [{"x": round(x + dx), "y": round(y + dy)} for k, (x, y) in pos.items() if k != "journey" for dx, dy in ((-56, 62), (66, 58), (-8, 78))]
    return {"islands": islands, "paths": paths, "bridges": bridges, "trees": trees, "flowers": flowers}


def scene(user, child):
    """Everything the map page needs."""
    w = ws.get_settings(user.id)
    interests, found = ws.activity_interests(child.id)
    theme_key, _, _ = ws.resolve_theme(interests, w)
    keys = [k for k in ordered_keys() if _shown(k, w, _shots_ok(user))]
    return _scene(keys, theme_key, found, child.display_name, child.avatar, bool(w["animation"]) and not w["reduced_motion"],
                  lambda k: url_for("my_world.room", key=k))


def preview_scene(admin_url):
    """The map as a caregiver-free sample (no child, no caregiver settings): every stop the admin has not switched off. admin_url(key) -> link."""
    keys = [k for k in ordered_keys() if k not in admin_hidden()]
    return _scene(keys, "mixed", [], "Sample", None, True, admin_url)


def _scene(keys, theme_key, found, name, avatar, motion, link):
    theme = ws.THEMES[theme_key]
    height, tall = tall_layout(keys)
    tall_pos = {k: (x, y) for k, x, y in tall}
    stops = []
    for key in keys:
        d = STOPS[key]
        inter = ws.stop_interest(d["scope"], found) if d["scope"] in ws.STOP_DEFS and key not in ("journey", "home") else None
        x, y = tall_pos[key]
        stops.append({"key": key, "label": d["label"], "icon": d["icon"], "color": d["color"], "blurb": d["blurb"], "sprite": sprite(key), "url": link(key),
                      "x": x, "y": round(y / height * 100, 2), "lx": d["land"][0], "ly": d["land"][1], "star": bool(inter and inter["level"] > 0),
                      "sign": key == "journey"})
    decor_icon = theme["icon"] if theme_key != "mixed" else "flower-2"
    trees = [(4 if i % 2 == 0 else 96, 40 + i * 46) for i in range((height - 60) // 46)]
    return {"child": {"name": name, "avatar": avatar}, "stops": stops, "w": TALL_W, "h": height,
            "path": _tall_path([(50, 6)] + [(s["x"], s["y"] * height / 100) for s in stops if not s["sign"]]),
            "trees": trees, "wide": wide_scene(keys), "ww": WIDE_W, "wh": WIDE_H, "decor_icon": decor_icon,
            "palette": {k: theme[k] for k in ("sky", "water", "grass", "sand", "accent")}, "theme_label": theme["label"] if theme_key != "mixed" else "",
            "motion": motion}


def preview_room(key):
    """A room with no child behind it (for the admin to see the artwork). The lists stay empty."""
    d = STOPS.get(key)
    if d is None:
        return None
    theme = ws.THEMES["mixed"]
    return {"key": key, "label": d["label"], "icon": d["icon"], "color": d["color"], "blurb": d["blurb"], "hello": d["hello"], "cat": d["cat"], "q": d["q"],
            "kinds": [{"key": k, "label": KIND_LABELS[k][0], "icon": KIND_LABELS[k][1]} for k in d["kinds"]],
            "palette": {k: theme[k] for k in ("sky", "grass", "accent")}, "characters": [], "interior": None, "zones": [], "flavors": [], "sprite": sprite(key),
            "room_art": _room_art(key), "watched": {"items": [], "total": 0}, "favorites": [],
            "milestones": [{"icon": "play", "label": "Things I watched", "value": 0}, {"icon": "heart", "label": "My favourites", "value": 0}, {"icon": "sparkles", "label": "Topics I tried", "value": 0}] if key == "journey" else None,
            "motion": True, "watched_title": {"music": "Your Watched Songs", "journey": "Things I did"}.get(key, "You watched")}


def set_layout(admin, hidden, order):
    """Save which stops are off and the phone-map order. Unknown keys are ignored; the journey sign stays."""
    hidden = [k for k in dict.fromkeys(hidden) if k in STOPS and k != "journey"]
    if len(hidden) >= len(MAIN_STOPS):
        raise ValueError("Keep at least one stop switched on.")
    order = [k for k in dict.fromkeys(order) if k in STOPS and k != "journey"]
    settings_service.set_value(SETTING_HIDDEN, ",".join(hidden))
    settings_service.set_value(SETTING_ORDER, ",".join(order))
    from services import auth_service
    auth_service.audit(admin.id, "world2d_layout", "setting", None, f"{len(hidden)} off")
    Session.commit()


def set_art(admin, kind, key, raw):
    """Upload artwork for a stop (kind 'stop2d') or a room scene ('room2d'). It replaces the previous upload; the built-in drawing returns on reset."""
    import os as _os, secrets
    from database.models import WorldAsset
    from services import auth_service, world_library_service as wl
    if kind not in ART_KINDS or key not in STOPS:
        raise wl.WorldError("Please choose a stop.")
    if not raw:
        raise wl.WorldError("Please choose an image file.")
    data, w, h = wl.reencode(raw)
    filename = secrets.token_hex(16) + ".webp"
    with open(_os.path.join(wl.asset_dir(), filename), "wb") as fh:
        fh.write(data)
    old = Session.query(WorldAsset).filter_by(kind=kind, stop=key).all()
    row = WorldAsset(kind=kind, stop=key, name=f"{STOPS[key]['label']} {'building' if kind == 'stop2d' else 'room'}", filename=filename, width=w, height=h,
                     rights_confirmed=True, uploaded_by=admin.id)
    Session.add(row)
    Session.flush()
    for o in old:                                   # one artwork per stop/room: delete the previous files
        try:
            _os.remove(_os.path.join(wl.asset_dir(), o.filename))
        except OSError:
            pass
        Session.delete(o)
    auth_service.audit(admin.id, "world2d_art_set", "world_asset", row.id, f"{kind}/{key}")
    Session.commit()
    return row


def reset_art(admin, kind, key):
    """Remove the uploaded artwork so the built-in drawing is used again."""
    import os as _os
    from database.models import WorldAsset
    from services import auth_service, world_library_service as wl
    rows = Session.query(WorldAsset).filter_by(kind=kind, stop=key).all() if kind in ART_KINDS and key in STOPS else []
    for o in rows:
        try:
            _os.remove(_os.path.join(wl.asset_dir(), o.filename))
        except OSError:
            pass
        Session.delete(o)
    if rows:
        auth_service.audit(admin.id, "world2d_art_reset", "world_asset", None, f"{kind}/{key}")
    Session.commit()
    return len(rows)


def room(user, child, key):
    """Data for one room, or None when there is no such stop (or the caregiver hid it)."""
    d = STOPS.get(key)
    if d is None:
        return None
    w = ws.get_settings(user.id)
    shots_ok = _shots_ok(user)
    if not _shown(key, w, shots_ok):
        return None
    interests, _ = ws.activity_interests(child.id)
    theme_key, _, _ = ws.resolve_theme(interests, w)
    theme = ws.THEMES[theme_key]
    out = {"key": key, "label": d["label"], "icon": d["icon"], "color": d["color"], "blurb": d["blurb"], "hello": d["hello"], "cat": d["cat"], "q": d["q"],
           "kinds": [{"key": k, "label": KIND_LABELS[k][0], "icon": KIND_LABELS[k][1]} for k in d["kinds"] if k != "shots" or shots_ok],
           "palette": {k: theme[k] for k in ("sky", "grass", "accent")}, "characters": [], "interior": None, "zones": [], "flavors": [], "sprite": sprite(key),
           "room_art": _room_art(key), "watched": {"items": [], "total": 0}, "favorites": [], "milestones": None,
           "motion": bool(w["animation"]) and not w["reduced_motion"]}
    out["watched_title"] = {"music": "Your Watched Songs", "journey": "Things I did"}.get(key, "You watched")
    if key == "journey":
        out["watched"] = watched_service.watched(user, child, ws.activity_scope("home"), limit=24)
        out["milestones"] = _milestones(child, out["watched"]["total"], interests)
        return out
    detail = ws.stop_detail(user, child, d["scope"], force=True) or {}
    out["watched"] = detail.get("watched") or out["watched"]
    out["characters"] = [c["url"] for c in (detail.get("characters") or [])[:3]]
    out["interior"] = detail.get("interior")
    if key == "home":
        out["favorites"] = detail.get("favorites") or []
    elif key in ("food",):
        out["flavors"] = detail.get("flavors") or []
    return out


def _room_art(key):
    """Room picture: what the admin uploaded, else static/images/world/room-<key>.png, else None for the built-in drawing."""
    art = admin_art("room2d", key)
    if art:
        return art
    folder = os.path.join(current_app.static_folder, "images", "world")
    for ext in ("png", "webp"):
        if os.path.isfile(os.path.join(folder, f"room-{key}.{ext}")):
            return url_for("static", filename=f"images/world/room-{key}.{ext}")
    return None


def _milestones(child, watched_total, interests):
    """Three happy counters. Counts only: no scores, no comparisons, nothing that reads as a judgement."""
    favourites = Session.query(Favorite).filter(Favorite.child_profile_id == child.id).count()
    topics = len([i for i in interests if i["category"] in CATEGORIES and i["evidence"] > 0])
    return [{"icon": "play", "label": "Things I watched", "value": watched_total},
            {"icon": "heart", "label": "My favourites", "value": favourites},
            {"icon": "sparkles", "label": "Topics I tried", "value": topics}]
