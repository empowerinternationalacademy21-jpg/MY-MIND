"""My World: theme engine, stops, decorations, caregiver controls and the world API."""
import io
import pytest
from PIL import Image
from database.db import Session
from database.models import Asset3D, ChildProfile, Interaction, WorldAsset, utcnow
from services import recommendation_service as rec
from services import world_service as ws
from conftest import Client


def child_id(app):
    with app.app_context():
        return Session.query(ChildProfile).one().id


def like(app, category, n=3, kind="like"):
    with app.app_context():
        cid = Session.query(ChildProfile).one().id
        for _ in range(n):
            rec.record_interaction(cid, None, kind, category=category)


def world(c):
    return c.get("/api/world").get_json()


def stops(w):
    return {s["key"]: s for s in w["stops"]}


def settings(c, **kw):
    return c.jpost("/api/world/settings", kw)


def art(admin, kind="character", stop="music", theme="", zone="", name="Buddy", real=False):
    buf = io.BytesIO(); Image.new("RGB", (64, 64), (30, 120, 200)).save(buf, "PNG")
    form = {"kind": kind, "stop": stop, "zone": zone, "theme": theme, "name": name, "caption": "hi", "rights_confirmed": "on",
            "source_note": "Licensed, contract 7" if real else "", "image": (io.BytesIO(buf.getvalue()), "a.png")}
    if real:
        form["is_real_person"] = "on"
    admin.post("/admin/world/upload", form, content_type="multipart/form-data")


# ------------------------------------------------------------------ the map itself
def test_fresh_world_has_core_stops_a_path_and_a_calm_mixed_theme(ready):
    w = world(ready)
    s = stops(w)
    core = {"home", "pictures", "videos", "shots", "music", "sports", "food", "colors", "nature"}
    assert set(s) == core | {"animals"}                                                  # animals was ticked in the questionnaire, so its stop is open
    assert w["theme"]["key"] == "mixed" and "Not enough repeated choices" in w["theme"]["reason"] and w["theme"]["source"] == "auto"
    assert all(set(s[k]) >= {"x", "y", "label", "icon", "color", "decor"} and 0 <= s[k]["x"] <= 100 and 0 <= s[k]["y"] <= 100 for k in s)
    nodes = {n for b in w["bridges"] for n in b}
    assert nodes == set(s) and len(w["bridges"]) == len(s) - 1                         # one connected walk through every island
    assert w["child"]["name"] == "Sunny" and set(w["theme"]["palette"]) == {"sky", "water", "grass", "sand", "accent"}
    assert w["settings"]["rotation"] is True and w["settings"]["animation"] is True and w["rotation_seconds"] >= 30


def test_world_api_is_private(app, ready, admin):
    anon = Client(app)
    for url in ("/api/world", "/api/world/stop/home"):
        assert anon.get(url).status_code in (302, 401, 403) and admin.get(url).status_code in (302, 403)
    assert anon.jpost("/api/world/settings", {"theme": "art"}).status_code in (302, 401, 403)
    assert anon.jpost("/api/world/reset-theme", {}).status_code in (302, 401, 403)


# ------------------------------------------------------------------ the theme engine
def test_one_click_never_themes_the_world_and_negative_signals_never_create_themes(app, ready):
    like(app, "music", 1)
    assert world(ready)["theme"]["key"] == "mixed"                                       # score 3 but a single action
    like(app, "music", 20, kind="skip"); like(app, "food", 6, kind="dislike")
    assert world(ready)["theme"]["key"] == "mixed"
    like(app, "music", 2)
    t = world(ready)["theme"]
    assert t["key"] == "music" and "chosen 3 times" in t["reason"] and "nothing else is close" in t["reason"]


def test_close_runners_up_stay_mixed_and_a_clear_leader_wins(app, ready):
    like(app, "nature", 3); like(app, "food", 3)
    t = world(ready)["theme"]
    assert t["key"] == "mixed" and "Food & Ice-cream and Nature" in t["reason"] and "equally liked" in t["reason"]
    like(app, "nature", 3)
    assert world(ready)["theme"]["key"] == "nature"


def test_sports_themes_need_the_caregivers_zones(app, ready):
    like(app, "sports", 4)
    assert world(ready)["theme"]["key"] == "mixed"                                       # never guessed from evidence alone
    settings(ready, sports_zones=["football"])
    assert world(ready)["theme"]["key"] == "football"
    settings(ready, sports_zones=["basketball"])
    assert world(ready)["theme"]["key"] == "basketball"
    settings(ready, sports_zones=["football", "basketball"])
    assert world(ready)["theme"]["key"] == "mixed"
    settings(ready, sports_zones=["swimming"])                                           # swimming has no theme of its own
    assert world(ready)["theme"]["key"] == "mixed"


def test_manual_theme_confirmed_interests_and_reset(app, ready):
    r = settings(ready, theme="art")
    assert r.status_code == 200 and r.get_json()["theme"] == {**r.get_json()["theme"], "key": "art", "source": "manual"}
    assert "caregiver chose" in r.get_json()["theme"]["reason"]
    settings(ready, theme="auto", interests=["animals"])
    t = world(ready)["theme"]
    assert t["key"] == "animals" and "confirmed" in t["reason"]
    assert "animals" in stops(world(ready))                                              # a ticked interest unlocks its stop
    settings(ready, interests=[])
    like(app, "music", 3)
    assert world(ready)["theme"]["key"] == "music"
    with app.app_context():
        before = Session.query(Interaction).count()
    r = ready.jpost("/api/world/reset-theme", {})
    assert r.get_json()["theme"]["key"] == "mixed" and r.get_json()["settings"]["theme"] == "auto"
    with app.app_context():
        assert Session.query(Interaction).count() == before                              # history is never deleted
    like(app, "music", 3)
    assert world(ready)["theme"]["key"] == "music"                                       # fresh evidence builds the theme again


def test_extra_stops_appear_only_with_the_interest(app, ready):
    s = stops(world(ready))
    assert "animals" in s and s["animals"]["extra"] and not ({"vehicles", "art"} & set(s))
    like(app, "vehicles", 1, kind="like")
    like(app, "art", 1, kind="skip")                                                     # a skip is not interest
    s = stops(world(ready))
    assert "vehicles" in s and s["vehicles"]["extra"] and "art" not in s


# ------------------------------------------------------------------ decorations
@pytest.mark.parametrize("evidence,tier,count", [(0, 0, 0), (2, 0, 0), (3, 1, 3), (5, 1, 3), (6, 2, 6), (9, 2, 6), (10, 3, 10), (25, 3, 10)])
def test_decorations_grow_with_evidence(app, ready, evidence, tier, count):
    like(app, "nature", evidence)
    d = stops(world(ready))["nature"]["decor"]
    assert (d["tier"], d["count"], d["kind"]) == (tier, count, "trees")


def test_strength_and_decorations_off(app, ready):
    like(app, "nature", 10)
    assert settings(ready, strength="light").get_json()["stops"][-1] is not None
    assert stops(world(ready))["nature"]["decor"]["count"] == 5
    settings(ready, strength="strong")
    assert stops(world(ready))["nature"]["decor"]["count"] == 15
    settings(ready, strength="balanced", decor_off=["nature"])
    d = stops(world(ready))["nature"]["decor"]
    assert d["count"] == 0 and d["tier"] == 3                                            # tier reflects evidence; the caregiver just turned props off


# ------------------------------------------------------------------ caregiver controls
def test_settings_are_validated_and_persist(app, ready):
    for bad in ({"theme": "neon"}, {"strength": "max"}, {"interests": ["unicorns"]}, {"sports_zones": "football"}, {"hidden_stops": ["../x"]},
                {"rotation": "yes"}, {"animation": 1}, {"sound": "on"}, {"real_people": None}, {"sneaky": True}, {"decor_off": ["nowhere"]}):
        r = settings(ready, **bad)
        assert r.status_code == 400 and r.get_json()["error"], bad
    assert ready.jpost("/api/world/settings", ["not", "a", "dict"]).status_code == 400
    r = settings(ready, rotation=False, animation=False, sound=False, real_people=True, strength="strong", sports_zones=["swimming", "swimming"])
    assert r.status_code == 200
    s = r.get_json()["settings"]
    assert (s["rotation"], s["animation"], s["sound"], s["real_people"], s["strength"], s["sports_zones"]) == (False, False, False, True, "strong", ["swimming"])
    assert world(ready)["settings"] == s                                                 # persisted
    cg = ready.get("/settings").get_data(as_text=True)
    assert 'name="show_real_people" checked' in cg.replace("\n", " ") or "show_real_people" in cg


def test_hide_stops_but_never_home_and_shorts_follow_the_switches(app, ready, admin):
    settings(ready, hidden_stops=["food", "home", "music"])
    s = stops(world(ready))
    assert "food" not in s and "music" not in s and "home" in s
    assert all(b[0] in s and b[1] in s for b in world(ready)["bridges"])
    assert ready.get("/api/world/stop/food").status_code == 404
    settings(ready, hidden_stops=[])
    assert "shots" in stops(world(ready))
    ready.post("/settings/preferences", {"display_name": "Sunny", "screen_time_minutes": "30"})          # unticking Shorts
    assert "shots" not in stops(world(ready))


def test_real_people_setting_flows_through_to_the_world(app, ready, admin):
    art(admin, stop="sports", name="Star", real=True); art(admin, stop="sports", name="Fox")
    assert stops(world(ready))["sports"]["characters"] == 1
    settings(ready, real_people=True)
    assert stops(world(ready))["sports"]["characters"] == 2


# ------------------------------------------------------------------ stop detail
def test_stop_detail_shelves_zones_flavors_and_home_favorites(app, ready):
    d = ready.get("/api/world/stop/sports").get_json()
    assert d["shelf"] == {"endpoint": "/api/pictures", "params": {"category": "sports"}}
    assert [z["key"] for z in d["zones"]] == list(ws.ZONES) and d["zones"][3]["q"] == "running track"
    settings(ready, sports_zones=["football", "cycling"])
    assert [z["key"] for z in ready.get("/api/world/stop/sports").get_json()["zones"]] == ["football", "cycling"]
    f = ready.get("/api/world/stop/food").get_json()
    assert [x["key"] for x in f["flavors"]] == list(ws.FLAVORS) and f["flavors"][1]["q"] == "chocolate ice cream"
    assert ready.get("/api/world/stop/videos").get_json()["shelf"]["endpoint"] == "/api/videos"
    assert ready.get("/api/world/stop/music").get_json()["shelf"]["params"] == {"category": "music"}
    h = ready.get("/api/world/stop/home").get_json()
    assert h["shelf"] is None and h["favorites"] == []
    for bad in ("nope", "..", "vehicles", "ART"):                                        # unknown, or an extra stop not unlocked yet
        assert ready.get(f"/api/world/stop/{bad}").status_code == 404


def test_characters_follow_theme_zone_and_ride_alongside_3d_friends(app, ready, admin):
    art(admin, stop="sports", zone="football", theme="football", name="Keeper")
    art(admin, stop="sports", zone="swimming", name="Swimmer")
    art(admin, stop="sports", zone="", theme="music", name="Drummer")
    art(admin, kind="interior", stop="sports", name="Pitch")
    names = lambda: sorted(c["name"] for c in ready.get("/api/world/stop/sports").get_json()["characters"])
    assert names() == ["Drummer", "Keeper", "Swimmer"]                                   # mixed world, no zones chosen: nothing is filtered out
    like(app, "sports", 4); settings(ready, sports_zones=["football"])                   # football theme + football zone only
    assert names() == ["Keeper"]
    d = ready.get("/api/world/stop/sports").get_json()
    assert d["interior"].startswith("/world-assets/") and d["rotation"] is True and d["rotation_seconds"] >= 30
    with app.app_context():
        Session.add(Asset3D(category="sports", archetype="trophy", kind="item", name="Cup", provider="meshy", status="published", stage="done",
                            glb_filename="1-glb-aa.glb", clips_json='{"walk": "1-walk-aa.glb"}', options_json="{}", tasks_json="{}", prompt="p"))
        Session.add(Asset3D(category="sports", archetype="trophy", kind="item", name="Hidden", provider="meshy", status="review", stage="done",
                            glb_filename="2-glb-bb.glb", options_json="{}", tasks_json="{}", prompt="p"))
        Session.commit()
    f = ready.get("/api/world/stop/sports").get_json()["friends3d"]
    assert [x["name"] for x in f] == ["Cup"] and f[0]["clips"] == ["walk"] and f[0]["glb"].endswith("/glb")
    assert stops(world(ready))["sports"]["friends3d"] == 1


def test_theme_filter_for_characters_in_the_mixed_world(app, ready, admin):
    art(admin, stop="music", theme="food", name="ChefOnly"); art(admin, stop="music", theme="", name="Anyone")
    got = sorted(c["name"] for c in ready.get("/api/world/stop/music").get_json()["characters"])
    assert got == ["Anyone", "ChefOnly"]                                                 # mixed world: no theme filtering
    like(app, "music", 3)                                                                # music theme now: food-only art steps aside
    got = sorted(c["name"] for c in ready.get("/api/world/stop/music").get_json()["characters"])
    assert got == ["Anyone"]
    like(app, "food", 12)                                                                # food overtakes music: the food art returns
    assert world(ready)["theme"]["key"] == "food"
    assert sorted(c["name"] for c in ready.get("/api/world/stop/music").get_json()["characters"]) == ["Anyone", "ChefOnly"]


# ------------------------------------------------------------------ the page and its static assets
import json as _json
import re as _re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def embedded(page):
    m = _re.search(r'<script type="application/json" id="world-data">(.*?)</script>', page, _re.S)
    assert m, "world-data block missing"
    return _json.loads(m.group(1))


def test_page_embeds_the_same_payload_as_the_api_and_loads_every_asset(app, ready):
    html = ready.get("/world").get_data(as_text=True)
    assert embedded(html) == world(ready)
    for needle in ('id="world3d"', "css/world3d.css", "vendor/three-gltf.min.js", "js/asset3d.js", "js/world/scene.js", "js/world/ui.js",
                   'id="w3d-stage"', 'id="w3d-sheet"', 'id="w3d-gear"', 'id="w3d-list"'):
        assert needle in html, needle
    assert "my_world.js" not in html                                                     # the old client-only map script is gone
    for url in _re.findall(r'(?:src|href)="(/static/[^"]+)"', html):
        assert ready.get(url).status_code == 200, url


def test_embedded_json_cannot_break_out_of_its_script_tag(app, ready):
    ready.post("/settings/preferences", {"display_name": "Sam</script><script>alert(1)</script>", "screen_time_minutes": "30"})
    html = ready.get("/world").get_data(as_text=True)
    block = _re.search(r'id="world-data">(.*?)</script>', html, _re.S).group(1)
    assert "</script" not in block and "<script" not in block.lower()
    assert "<script>alert(1)" not in html                                                # neither in the JSON block nor anywhere else in the page


@pytest.mark.parametrize("path", ["vendor/three-gltf.min.js", "vendor/draco/draco_decoder.wasm", "vendor/draco/draco_wasm_wrapper.js", "vendor/THREE-LICENSE.txt",
                                  "js/world/scene.js", "js/world/ui.js", "js/asset3d.js", "css/world3d.css", "css/asset3d.css", "css/family.css"])
def test_static_files_exist_and_are_served(ready, path):
    r = ready.get("/static/" + path)
    assert r.status_code == 200 and len(r.data) > 200


def test_every_icon_the_world_uses_exists_in_the_sprite():
    sprite = (ROOT / "templates" / "_icons.html").read_text(encoding="utf-8")
    used = {d["icon"] for d in ws.STOP_DEFS.values()} | {t["icon"] for t in ws.THEMES.values()}
    used |= {"plus", "minus", "locate-fixed", "sliders-horizontal", "x", "sparkles", "chevron-right", "triangle-alert", "lock", "shield-check", "box", "image", "ban"}
    missing = sorted(i for i in used if f'id="i-{i}"' not in sprite)
    assert not missing, f"icons missing from the sprite: {missing}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("script", ["js/world/scene.js", "js/world/ui.js", "js/asset3d.js", "js/parent_links.js", "js/verify.js"])
def test_front_end_scripts_parse(script):
    r = subprocess.run(["node", "--check", str(ROOT / "static" / script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_stops_are_data_adding_one_needs_no_code_changes(app, ready, monkeypatch):
    monkeypatch.setitem(ws.STOP_DEFS, "space", dict(label="Space", icon="sparkles", x=60, y=8, color="#3b4cca", blurb="Stars and rockets.", cats=("space",),
                                                   shelf=("/api/pictures", {"category": "places"}), tier="core"))
    monkeypatch.setattr(ws, "PATH_ORDER", ws.PATH_ORDER + ("space",))
    s = stops(world(ready))
    assert "space" in s and s["space"]["decor"]["kind"] == "flowers" and ["sports", "space"] in world(ready)["bridges"]
    d = ready.get("/api/world/stop/space").get_json()
    assert d["label"] == "Space" and d["shelf"]["params"] == {"category": "places"}
    settings(ready, hidden_stops=["space"])
    assert "space" not in stops(world(ready))
