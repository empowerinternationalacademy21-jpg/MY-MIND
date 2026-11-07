"""My World: the adaptive island map. Everything here is driven by saved data and is editable by the caregiver.

* Themes apply only after REPEATED positive evidence (score >= 3 and >= 3 child actions) or an interest the caregiver confirmed.
  One click never changes the world; skips, views and dislikes never create a theme; close runners-up stay "Mixed".
  Sports themes (football / basketball) come only from the sports zones the caregiver picks, never from guesses.
* Every theme comes with a plain-language reason. Nothing is a diagnosis: these are observations of choices.
* Stops are data (STOP_DEFS), so adding one is a data change, not a code change.
"""
from database.db import Session
from database.models import ContentItem, Favorite, utcnow
from services import settings_service, world_library_service as wl
from services import recommendation_service as rec
from services.ai3d import library as a3d_library
from services.categories import CATEGORIES

QUALIFY_SCORE, QUALIFY_EVIDENCE = 3.0, 3
CLOSE_RATIO = 0.8                       # a runner-up within 80% of the leader keeps the world "Mixed"
DECOR_TIERS = (3, 6, 10)                # evidence needed for tier 1, 2, 3
DECOR_COUNTS = (0, 3, 6, 10)
STRENGTH = {"light": 0.5, "balanced": 1.0, "strong": 1.5}

THEMES = {
    "football":   {"label": "Football", "icon": "bike", "sky": ("#6ec1ff", "#dff3ff"), "water": ("#1f8fd0", "#58c4f0"), "grass": "#4fbf4a", "sand": "#f1dfa5", "accent": "#ffffff"},
    "basketball": {"label": "Basketball", "icon": "bike", "sky": ("#ffb36b", "#ffe9cf"), "water": ("#2a86c9", "#5bb8e8"), "grass": "#7fbf55", "sand": "#f3d9a4", "accent": "#ff8a2b"},
    "music":      {"label": "Music", "icon": "music", "sky": ("#a58bff", "#f0e6ff"), "water": ("#4d6fd6", "#8aa4f2"), "grass": "#6bc07a", "sand": "#efe0b6", "accent": "#9a5bd9"},
    "food":       {"label": "Food & Ice-cream", "icon": "apple", "sky": ("#ff9fb5", "#ffe8ee"), "water": ("#35a0d8", "#7fd0f0"), "grass": "#8ccf5e", "sand": "#f6dfae", "accent": "#f9566a"},
    "colors":     {"label": "Colors & Shapes", "icon": "shapes", "sky": ("#8fa8ff", "#ece8ff"), "water": ("#3a8ee0", "#79c3f5"), "grass": "#5cc98a", "sand": "#f2e0b0", "accent": "#7c4dff"},
    "animals":    {"label": "Animals", "icon": "paw-print", "sky": ("#ffd36b", "#fff2cf"), "water": ("#2f98d3", "#69c8ee"), "grass": "#78c24a", "sand": "#f0d9a0", "accent": "#f5a623"},
    "nature":     {"label": "Nature", "icon": "trees", "sky": ("#7fd6c8", "#e2f7f1"), "water": ("#2a95c8", "#62cdea"), "grass": "#4caf3f", "sand": "#ecdca8", "accent": "#2e8b57"},
    "vehicles":   {"label": "Vehicles", "icon": "car", "sky": ("#7aaeff", "#e0edff"), "water": ("#2678cf", "#5aaef0"), "grass": "#68b858", "sand": "#eedcaa", "accent": "#2f80ed"},
    "art":        {"label": "Art", "icon": "brush", "sky": ("#ffa27a", "#ffeadd"), "water": ("#3b8fd6", "#7cc4f1"), "grass": "#86c765", "sand": "#f4ddb0", "accent": "#e8590c"},
    "mixed":      {"label": "Mixed", "icon": "sparkles", "sky": ("#7fb8ff", "#e6f1ff"), "water": ("#2a8fd2", "#62c5ee"), "grass": "#5fbf55", "sand": "#f0dfaa", "accent": "#1f78f0"},
}
# interest categories whose evidence builds each theme (football/basketball are deliberately absent: they need caregiver-chosen zones)
THEME_CATS = {"music": ("music", "dancing"), "food": ("food",), "colors": ("colors", "toys"), "animals": ("animals",),
              "nature": ("nature", "water"), "vehicles": ("vehicles",), "art": ("art", "stories")}
ZONES = {"football": "football", "basketball": "basketball", "swimming": "swimming", "athletics": "running track", "cycling": "cycling"}
FLAVORS = ("vanilla", "chocolate", "strawberry", "mango", "banana", "lemon")

# key: label, icon, x, y (0-100 map grid), colour, blurb, evidence categories, shelf (endpoint, params), tier ("core" always there, "extra" appears with the interest)
STOP_DEFS = {
    "home":     dict(label="Home", icon="house", x=50, y=90, color="#1f78f0", blurb="Your favourite things, all in one cosy place.", cats=(), shelf=None, tier="core"),
    "pictures": dict(label="Pictures", icon="image", x=22, y=74, color="#2bb3a6", blurb="Look at colourful pictures.", cats=(), shelf=("/api/pictures", {}), tier="core"),
    "videos":   dict(label="Videos", icon="clapperboard", x=78, y=74, color="#ef6f9a", blurb="Watch videos, one tap at a time.", cats=(), shelf=("/api/videos", {}), tier="core"),
    "shots":    dict(label="Shorts", icon="smartphone", x=50, y=64, color="#9a5bd9", blurb="Quick, short clips.", cats=(), shelf=("/api/shots", {}), tier="core"),
    "music":    dict(label="Music", icon="music", x=16, y=50, color="#9a5bd9", blurb="Songs to listen to and dance to.", cats=("music", "dancing"), shelf=("/api/music", {"category": "music"}), tier="core"),
    "sports":   dict(label="Sports", icon="bike", x=50, y=42, color="#2bb3a6", blurb="Games, goals and moving about.", cats=("sports",), shelf=("/api/pictures", {"category": "sports"}), tier="core"),
    "food":     dict(label="Food & Ice-cream", icon="apple", x=84, y=50, color="#f9566a", blurb="Yummy things to look at.", cats=("food",), shelf=("/api/pictures", {"category": "food"}), tier="core"),
    "colors":   dict(label="Colors & Shapes", icon="shapes", x=28, y=26, color="#7c4dff", blurb="Rainbows, shapes and balloons.", cats=("colors", "toys"), shelf=("/api/pictures", {"category": "colors"}), tier="core"),
    "nature":   dict(label="Nature", icon="trees", x=72, y=26, color="#4caf3f", blurb="Forests, flowers and the great outdoors.", cats=("nature", "water", "places"), shelf=("/api/pictures", {"category": "nature"}), tier="core"),
    "animals":  dict(label="Animals", icon="paw-print", x=8, y=24, color="#f5a623", blurb="Furry, feathery and fun friends.", cats=("animals",), shelf=("/api/pictures", {"category": "animals"}), tier="extra"),
    "vehicles": dict(label="Vehicles", icon="car", x=92, y=26, color="#2f80ed", blurb="Cars, trains, planes and boats.", cats=("vehicles",), shelf=("/api/pictures", {"category": "vehicles"}), tier="extra"),
    "art":      dict(label="Art", icon="brush", x=50, y=12, color="#e8590c", blurb="Painting, drawing and making.", cats=("art", "stories", "cartoons"), shelf=("/api/pictures", {"category": "art"}), tier="extra"),
}
PATH_ORDER = ("home", "pictures", "music", "colors", "animals", "art", "nature", "vehicles", "food", "videos", "shots", "sports")   # bridges follow this walk
DECOR_KIND = {"sports": "balls", "music": "notes", "food": "treats", "colors": "shapes", "nature": "trees", "animals": "paws", "vehicles": "cones", "art": "paint"}

DEFAULTS = {"theme": "auto", "island": "auto", "strength": "balanced", "interests": [], "sports_zones": [], "rotation": True, "animation": True,
            "hidden_stops": [], "decor_off": [], "baseline": {}}


class WorldError(ValueError):
    pass


# ---------------------------------------------------------------- settings
def get_settings(user_id):
    cg = settings_service.caregiver_settings(user_id)
    w = dict(DEFAULTS)
    stored = cg.get("world") or {}
    if isinstance(stored, dict):
        w.update({k: v for k, v in stored.items() if k in DEFAULTS})
    w["sound"] = bool(cg.get("sound_on", True))
    w["real_people"] = bool(cg.get("show_real_people", False))
    w["reduced_motion"] = bool(cg.get("reduced_motion", False))
    return w


def _list_of(value, allowed, field):
    if not isinstance(value, list) or len(value) > 40:
        raise WorldError(f"{field} must be a list.")
    out = []
    for v in value:
        if v not in allowed:
            raise WorldError(f"{field} contains an unknown value.")
        if v not in out:
            out.append(v)
    return out


def update_settings(user_id, raw):
    """Validate a partial update (unknown keys are refused) and save it. Returns the new settings."""
    if not isinstance(raw, dict):
        raise WorldError("Settings must be an object.")
    cur = get_settings(user_id)
    world, top = {k: cur[k] for k in DEFAULTS}, {}
    for key, value in raw.items():
        if key == "theme":
            if value != "auto" and value not in THEMES:
                raise WorldError("Unknown theme.")
            world["theme"] = value
        elif key == "island":
            if island_locked():          # the administrator's island applies to everyone: keep the stored choice, ignore this one
                continue
            ok = {"auto", "classic"} | {str(a.id) for a in a3d_library.island_bases()}
            if not isinstance(value, str) or value not in ok:
                raise WorldError("That island look is not available.")
            world["island"] = value
        elif key == "strength":
            if value not in STRENGTH:
                raise WorldError("Unknown strength.")
            world["strength"] = value
        elif key == "interests":
            world["interests"] = _list_of(value, tuple(THEME_CATS) + ("sports",), "interests")
        elif key == "sports_zones":
            world["sports_zones"] = _list_of(value, tuple(ZONES), "sports_zones")
        elif key == "hidden_stops":
            world["hidden_stops"] = [s for s in _list_of(value, tuple(STOP_DEFS), "hidden_stops") if s != "home"]
        elif key == "decor_off":
            world["decor_off"] = _list_of(value, tuple(STOP_DEFS), "decor_off")
        elif key in ("rotation", "animation"):
            if not isinstance(value, bool):
                raise WorldError(f"{key} must be true or false.")
            world[key] = value
        elif key == "sound":
            if not isinstance(value, bool):
                raise WorldError("sound must be true or false.")
            top["sound_on"] = value
        elif key == "real_people":
            if not isinstance(value, bool):
                raise WorldError("real_people must be true or false.")
            top["show_real_people"] = value
        else:
            raise WorldError(f"Unknown setting: {key}")
    settings_service.save_caregiver_settings(user_id, {"world": world, **top})
    return get_settings(user_id)


# ---------------------------------------------------------------- theme engine
def _by_category(interests):
    return {i["category"]: i for i in interests}


def resolve_theme(interests, w):
    """-> (key, reason, source). Pure function of saved data, so it is easy to test and to explain."""
    if w["theme"] != "auto" and w["theme"] in THEMES:
        return w["theme"], "A caregiver chose this style.", "manual"
    base, cats = w.get("baseline") or {}, _by_category(interests)
    cand = {}
    for theme, members in THEME_CATS.items():
        score = sum(max(0.0, cats[c]["score"]) for c in members if c in cats)
        ev = sum(max(0, cats[c]["evidence"] - int(base.get(c, 0))) for c in members if c in cats)
        if score >= QUALIFY_SCORE and ev >= QUALIFY_EVIDENCE:
            cand[theme] = (score, ev, "choices")
        elif theme in w["interests"]:
            cand[theme] = (max(score, QUALIFY_SCORE + 0.5), ev, "confirmed")
    sports = cats.get("sports")                                   # sports themes need the caregiver's zones as well as real evidence
    s_ok = bool(sports and sports["score"] >= QUALIFY_SCORE and sports["evidence"] - int(base.get("sports", 0)) >= QUALIFY_EVIDENCE) or "sports" in w["interests"]
    if s_ok:
        s_score = max(sports["score"] if sports else 0.0, QUALIFY_SCORE + 0.5 if "sports" in w["interests"] else 0.0)
        s_ev = max(0, (sports["evidence"] if sports else 0) - int(base.get("sports", 0)))
        for zone in ("football", "basketball"):
            if zone in w["sports_zones"]:
                cand[zone] = (s_score, s_ev, "confirmed" if "sports" in w["interests"] and s_ev < QUALIFY_EVIDENCE else "choices")
    if not cand:
        return "mixed", "Not enough repeated choices yet, so the world stays a mix. Themes appear after a few positive choices.", "auto"
    ranked = sorted(cand.items(), key=lambda kv: (-kv[1][0], THEMES[kv[0]]["label"]))      # ties break by name so the reason text is stable
    top, (score, ev, how) = ranked[0]
    if len(ranked) > 1 and ranked[1][1][0] >= CLOSE_RATIO * score:
        names = " and ".join(THEMES[k]["label"] for k, _ in ranked[:2])
        return "mixed", f"{names} are about equally liked, so the world stays a mix.", "auto"
    label = THEMES[top]["label"]
    if how == "confirmed":
        return top, f"A caregiver confirmed {label} as an interest.", "auto"
    return top, f"{label} was chosen {ev} times with clear enjoyment, and nothing else is close.", "auto"


# ---------------------------------------------------------------- stops, decorations, characters
def _unlocked(key, cats, w, shots_ok):
    d = STOP_DEFS[key]
    if key in w["hidden_stops"] and key != "home":
        return False
    if key == "shots" and not shots_ok:
        return False
    if d["tier"] == "extra":
        c = d["cats"][0]
        return bool((c in cats and cats[c]["score"] > 0) or key in w["interests"])
    return True


def _evidence(key, cats, interests):
    members = STOP_DEFS[key]["cats"]
    if not members:
        return sum(max(0, i["evidence"]) for i in interests)
    return sum(max(0, cats[c]["evidence"]) for c in members if c in cats)


def decorations(key, evidence, w):
    tier = sum(1 for t in DECOR_TIERS if evidence >= t)
    count = 0 if key in w["decor_off"] else int(round(DECOR_COUNTS[tier] * STRENGTH[w["strength"]]))
    return {"tier": tier, "count": count, "kind": DECOR_KIND.get(key, "flowers")}


def characters_for(key, theme, w):
    out = []
    for a in wl.visible(w["real_people"], kind="character", stop=key, theme=theme if theme != "mixed" else None):
        if key == "sports" and w["sports_zones"] and a.zone and a.zone not in w["sports_zones"]:
            continue
        out.append(wl.as_dict(a))
    return out


def friends3d_for(key):
    return [a for a in a3d_library.published() if a.category == key]


def island_locked():
    """True when the administrator applies ONE island to every user's world (personal choices are ignored)."""
    return settings_service.get("island_lock") == "1"


def _island_choice(w):
    """-> (chosen asset or None, option list). 'auto' = the administrator's default island (else the newest published);
    'classic' = the built-in look. While the island is locked, everyone gets the administrator's island and no picker is offered."""
    bases = a3d_library.island_bases()
    by_id = {str(a.id): a for a in bases}
    locked = island_locked()
    pick = "auto" if locked else w.get("island", "auto")
    if pick == "classic":
        chosen = None
    else:
        chosen = by_id.get(pick) or a3d_library.default_island()            # 'auto', unknown or unpublished choices fall back to the default island
    options = ([{"key": "classic", "label": "Classic (built-in)"}] + [{"key": str(a.id), "label": a.name or f"Island {a.id}", "caption": a.caption} for a in bases]) if bases and not locked else []
    return chosen, options


def island_settings(user_id):
    """-> (options, current key) for the Settings page picker. options is empty until an island is published."""
    w = get_settings(user_id)
    _, options = _island_choice(w)
    keys = {o["key"] for o in options}
    return options, (w["island"] if w["island"] in keys else "auto")


def payload(user, child):
    w = get_settings(user.id)
    interests = rec.get_interests(child.id)
    cats = _by_category(interests)
    theme, reason, source = resolve_theme(interests, w)
    shots_ok = settings_service.get("shots_enabled") == "1" and settings_service.caregiver_settings(user.id)["shots_enabled"]
    stops = []
    kit = a3d_library.landmarks()                       # published island-kit models; anything missing falls back to the built-in procedural look
    island, island_options = _island_choice(w)
    badges = {}
    for a in wl.visible(w["real_people"], kind="island", theme=theme if theme != "mixed" else None):          # uploaded island art becomes the stop's badge
        badges.setdefault(a.stop, wl.as_dict(a)["url"])
    for key, d in STOP_DEFS.items():
        if not _unlocked(key, cats, w, shots_ok):
            continue
        ev = _evidence(key, cats, interests)
        chars = characters_for(key, theme, w)
        stops.append({"key": key, "label": d["label"], "icon": d["icon"], "x": d["x"], "y": d["y"], "color": d["color"], "blurb": d["blurb"],
                      "evidence": ev, "decor": decorations(key, ev, w), "characters": len(chars), "chars": [c["url"] for c in chars[:6]],
                      "friends3d": len(friends3d_for(key)), "extra": d["tier"] == "extra", "badge": badges.get(key),
                      "landmark3d": ({"id": kit[key].id, "url": f"/assets3d/{kit[key].id}/glb"} if key in kit else None)})
    keys = [s["key"] for s in stops]
    walk = [k for k in PATH_ORDER if k in keys]
    bridges = [[walk[i], walk[i + 1]] for i in range(len(walk) - 1)]
    t = THEMES[theme]
    return {"child": {"name": child.display_name, "avatar": child.avatar},
            "theme": {"key": theme, "label": t["label"], "icon": t["icon"], "reason": reason, "source": source, "palette": {k: t[k] for k in ("sky", "water", "grass", "sand", "accent")}},
            "stops": stops, "bridges": bridges, "island_locked": island_locked(),
            "island_base": ({"id": island.id, "url": f"/assets3d/{island.id}/glb"} if island else None),
            "backgrounds": [a["url"] for a in (wl.as_dict(x) for x in wl.visible(w["real_people"], kind="background", theme=theme if theme != "mixed" else None))][:1],
            "settings": {k: w[k] for k in ("theme", "island", "strength", "interests", "sports_zones", "rotation", "animation", "hidden_stops", "decor_off", "sound", "real_people")},
            "reduced_motion": w["reduced_motion"],
            "rotation_seconds": max(30, int(_rotation_seconds())),
            "options": {"islands": island_options, "themes": [{"key": k, "label": v["label"]} for k, v in THEMES.items()], "strengths": list(STRENGTH),
                        "interests": [{"key": k, "label": (THEMES[k]["label"] if k in THEMES else "Sports")} for k in tuple(THEMES_FOR_TICK)],
                        "zones": list(ZONES), "stops": [{"key": k, "label": STOP_DEFS[k]["label"]} for k in STOP_DEFS if k != "home"]}}


THEMES_FOR_TICK = ("music", "food", "colors", "animals", "nature", "vehicles", "art", "sports")


def _rotation_seconds():
    from flask import current_app
    return current_app.config.get("WORLD_ROTATION_SECONDS", 300)


def stop_detail(user, child, key):
    w = get_settings(user.id)
    interests = rec.get_interests(child.id)
    cats = _by_category(interests)
    shots_ok = settings_service.get("shots_enabled") == "1" and settings_service.caregiver_settings(user.id)["shots_enabled"]
    if key not in STOP_DEFS or not _unlocked(key, cats, w, shots_ok):
        return None
    theme, _, _ = resolve_theme(interests, w)
    d = STOP_DEFS[key]
    out = {"key": key, "label": d["label"], "icon": d["icon"], "blurb": d["blurb"], "color": d["color"],
           "characters": characters_for(key, theme, w), "rotation": bool(w["rotation"]), "rotation_seconds": max(30, int(_rotation_seconds())),
           "interior": None, "zones": [], "flavors": [], "shelf": None, "favorites": None,
           "friends3d": [{"id": a.id, "name": a.name, "caption": a.caption, "glb": f"/assets3d/{a.id}/glb",
                          "clips": a3d_library.clip_names(a)} for a in friends3d_for(key)]}
    inter = wl.visible(w["real_people"], kind="interior", stop=key, theme=theme if theme != "mixed" else None)
    if inter:
        out["interior"] = wl.as_dict(inter[0])["url"]
    if key == "sports":
        out["zones"] = [{"key": z, "q": ZONES[z]} for z in (w["sports_zones"] or ZONES)]
    if key == "food":
        out["flavors"] = [{"key": f, "q": f"{f} ice cream"} for f in FLAVORS]
    if d["shelf"]:
        out["shelf"] = {"endpoint": d["shelf"][0], "params": d["shelf"][1]}
    if key == "home":
        from services import content_service as cs
        favs = (Session.query(ContentItem).join(Favorite, Favorite.content_item_id == ContentItem.id)
                .filter(Favorite.child_profile_id == child.id).order_by(Favorite.id.desc()).limit(24).all())
        out["favorites"] = cs.serialise(favs, child.id)
    return out


def reset_theme(user_id, child):
    """Forget the evidence collected so far when choosing a theme. Nothing is deleted: choices, favourites and decorations stay."""
    w = get_settings(user_id)
    interests = rec.get_interests(child.id)
    baseline = {i["category"]: int(i["evidence"]) for i in interests}
    world = {k: w[k] for k in DEFAULTS}
    world.update(theme="auto", baseline=baseline)
    settings_service.save_caregiver_settings(user_id, {"world": world})
    return get_settings(user_id)
