"""My World stop activity (real, per child, per stop) and administrator island management."""
import json
import uuid
from datetime import timedelta

from conftest import CPW, Client
from database.db import Session
from database.models import ActivityEvent, Asset3D, ChildProfile, ContentItem, User, utcnow
from services import settings_service
from services.ai3d import islands


# ------------------------------------------------------------------ helpers
def item(kind, category, title=None, tags=None):
    row = ContentItem(provider="demo", provider_content_id=str(uuid.uuid4())[:12], content_type=kind, title=title or f"{category} {kind}",
                      thumbnail_url="https://example.test/t.jpg", category=category, tags_json=json.dumps(tags or []),
                      attribution_json=json.dumps({"artist": "Test Artist"}))
    Session.add(row)
    Session.flush()
    return row


def event(child_id, it, kind, seconds=60, ago=timedelta(minutes=5), **kw):
    at = utcnow() - ago
    Session.add(ActivityEvent(child_id=child_id, stop="videos", content_id=it.id, content_title=it.title, event_type=kind, duration_seconds=seconds,
                              client_event_id=str(uuid.uuid4()), created_at=at, last_active_at=at + timedelta(seconds=seconds),
                              content_type=it.content_type, category=it.category, **kw))


def my_child(app):
    with app.app_context():
        return Session.query(ChildProfile).first().id


def island(app, name, status="published"):
    with app.app_context():
        a = Asset3D(category="island", archetype="island_base", kind="landmark", name=name, provider="manual", status=status, stage="done",
                    glb_filename=f"{name}-{uuid.uuid4().hex[:6]}.glb")
        Session.add(a)
        Session.commit()
        return a.id


def status_of(app, asset_id):
    with app.app_context():
        row = Session.get(Asset3D, asset_id)
        return row.status if row else None


def default_setting(app):
    with app.app_context():
        return settings_service.get("default_island_id")


def base_id(client):
    base = client.get("/api/world").get_json()["island_base"]
    return base["id"] if base else None


# ------------------------------------------------------------------ Part 1: stop activity
def seed(app):
    cid = my_child(app)
    with app.app_context():
        football = item("video", "sports", "Football Highlights")
        song = item("song", "music", "Happy Song")
        pic = item("picture", "animals", "Cute Dog")
        clip = item("short", "animals", "Funny Cat Clip")
        food = item("picture", "food", "Ice Cream")
        event(cid, football, "watch", 600, completed=True, completion_pct=90, replay_count=1, measured=True)
        event(cid, song, "listen", 200, timedelta(days=2), completed=True)
        event(cid, pic, "look", 30)
        event(cid, pic, "open", 0, timedelta(minutes=6))
        event(cid, clip, "watch", 20, replay_count=3)
        event(cid, food, "look", 15)
        Session.commit()
        return {"football": football.id, "song": song.id, "pic": pic.id, "clip": clip.id, "food": food.id}


def titles(resp):
    return sorted(i["content"]["title"] for i in resp.get_json()["items"])


def test_each_stop_shows_only_its_own_real_content(app, ready):
    seed(app)
    assert titles(ready.get("/api/world/stop/sports/activity")) == ["Football Highlights"]
    assert titles(ready.get("/api/world/stop/music/activity")) == ["Happy Song"]
    assert titles(ready.get("/api/world/stop/animals/activity")) == ["Cute Dog", "Funny Cat Clip"]       # pictures AND shorts of that category
    assert titles(ready.get("/api/world/stop/pictures/activity")) == ["Cute Dog", "Ice Cream"]           # a media stop: by content type
    assert titles(ready.get("/api/world/stop/videos/activity")) == ["Football Highlights"]
    assert titles(ready.get("/api/world/stop/shots/activity")) == ["Funny Cat Clip"]
    assert len(titles(ready.get("/api/world/stop/home/activity"))) == 5                                   # the hub shows everything
    assert titles(ready.get("/api/world/stop/vehicles/activity")) == []                                   # nothing unrelated leaks in


def test_details_filters_and_empty_state(app, ready):
    seed(app)
    video = ready.get("/api/world/stop/sports/activity").get_json()["items"][0]
    assert video["views"] == 1 and video["minutes"] == 10.0 and video["completion_pct"] == 90 and video["replays"] == 1 and video["completed"]
    assert video["content"]["thumbnail_url"] and video["last_date"]
    song = ready.get("/api/world/stop/music/activity").get_json()["items"][0]
    assert song["artist"] == "Test Artist" and song["plays"] == 1 and song["seconds"] == 200
    clip = ready.get("/api/world/stop/shots/activity").get_json()["items"][0]
    assert clip["replays"] == 3 and clip["plays"] == 4
    data = ready.get("/api/world/stop/home/activity").get_json()
    assert data["counts"] == {"video": 1, "song": 1, "picture": 2, "short": 1, "all": 5}
    assert titles(ready.get("/api/world/stop/home/activity?type=picture")) == ["Cute Dog", "Ice Cream"]
    assert titles(ready.get("/api/world/stop/home/activity?type=short")) == ["Funny Cat Clip"]
    pic = [i for i in ready.get("/api/world/stop/animals/activity").get_json()["items"] if i["content"]["type"] == "picture"][0]
    assert pic["interactions"] == 2                                                                       # one look + one open
    old = ready.get("/api/world/stop/home/activity?start=2000-01-01&end=2000-01-02").get_json()
    assert old["items"] == [] and old["any_activity"] is False                                            # date filter works
    assert ready.get("/api/world/stop/vehicles/activity").get_json()["any_activity"] is False             # client shows the empty-state message
    assert ready.get("/api/world/stop/nonsense/activity").status_code == 404


def test_new_activity_appears_immediately_and_pages(app, ready):
    cid = my_child(app)
    assert ready.get("/api/world/stop/pictures/activity").get_json()["total"] == 0
    with app.app_context():
        for n in range(30):
            event(cid, item("picture", "art", f"Art {n}"), "look", 10, timedelta(minutes=n))
        Session.commit()
    first = ready.get("/api/world/stop/pictures/activity?per_page=12").get_json()
    assert first["total"] == 30 and len(first["items"]) == 12 and first["has_more"] and first["items"][0]["content"]["title"] == "Art 0"
    last = ready.get("/api/world/stop/pictures/activity?per_page=12&page=3").get_json()
    assert len(last["items"]) == 6 and not last["has_more"]


def test_record_detail_is_scoped_to_the_stop_and_the_child(app, ready):
    ids = seed(app)
    detail = ready.get(f"/api/world/stop/sports/activity/{ids['football']}").get_json()
    assert detail["content"]["title"] == "Football Highlights" and detail["viewer"]["title"] and detail["records"][0]["action"] == "watch"
    assert detail["totals"]["minutes"] == 10.0
    assert ready.get(f"/api/world/stop/music/activity/{ids['football']}").status_code == 404           # football video does not belong at the music stop
    assert ready.get("/api/world/stop/sports/activity/999999").status_code == 404


def test_only_the_childs_own_caregiver_can_read_it(app, ready):
    seed(app)
    anonymous = Client(app)
    assert anonymous.get("/api/world/stop/sports/activity").status_code in (302, 401, 403)
    other = Client(app)
    other.register("dad")
    assert other.get("/api/world/stop/sports/activity").status_code in (302, 401, 403, 404)           # a different family sees nothing of this child
    with app.app_context():                                                                             # the child's own session is refused too
        username = Session.query(ChildProfile).first().caregiver.child_username
    ready.post("/logout")
    assert ready.login(username, CPW).status_code == 302
    assert ready.get("/api/world/stop/sports/activity").status_code == 403


def test_one_childs_activity_never_appears_in_a_sibling_world(app, ready):
    first = my_child(app)
    assert ready.post("/caretaker/children/add", {"display_name": "Alex", "avatar": "star", "age": "8", "consent": "yes",
                                                   "child_password": "Alex!Secret8901"}).status_code == 302
    with app.app_context():
        second = Session.query(ChildProfile).order_by(ChildProfile.id.desc()).first().id
        uid = Session.query(ChildProfile).order_by(ChildProfile.id.desc()).first().public_uid
        event(first, item("video", "sports", "Only For First"), "watch", 120)
        Session.commit()
    with app.app_context():
        from services import activity_analytics_service as an
        from services import world_service as ws
        scope = ws.activity_scope("sports")
        assert [i["content"]["title"] for i in an.stop_activity(first, scope)["items"]] == ["Only For First"]
        assert an.stop_activity(second, scope)["items"] == []                                       # the sibling has nothing at that stop
        owned = an.stop_content_records(second, scope, Session.query(ContentItem).filter_by(title="Only For First").one().id)
        assert owned is None or owned["records"] == []                                              # and cannot read the first child's records either


def test_world_page_exposes_the_panel_only_to_caregivers(app, ready):
    page = ready.get("/world").data
    assert b'data-can-see-activity="1"' in page
    with app.app_context():
        username = Session.query(ChildProfile).first().caregiver.child_username
    ready.post("/logout")
    ready.login(username, CPW)
    assert b'data-can-see-activity="0"' in ready.get("/world").data


# ------------------------------------------------------------------ Part 2: island management
def test_admin_pages_show_every_island_with_default_and_status(app, admin):
    first, second = island(app, "beach"), island(app, "forest")
    page = admin.get("/admin/3d/islands")
    assert page.status_code == 200 and b"3D WORLD &amp; ISLAND MANAGEMENT" in page.data
    assert b"beach" in page.data and b"forest" in page.data and b"DEFAULT" in page.data
    assert b"3D WORLD &amp; ISLAND MANAGEMENT" in admin.get("/admin/3d/").data
    assert admin.get("/admin/3d/islands").status_code == 200


def test_only_administrators_can_manage_islands(app, ready):
    a = island(app, "beach")
    assert ready.get("/admin/3d/islands").status_code == 403
    for path, data in (("/admin/3d/islands/default", {"id": a, "confirm": "yes"}), ("/admin/3d/islands/delete", {"ids": a, "confirm": "yes"}),
                       ("/admin/3d/islands/delete-all", {"phrase": "DELETE ALL", "confirm": "yes"}), ("/admin/3d/islands/restore", {"id": a}),
                       ("/admin/3d/islands/purge", {"ids": a, "confirm": "yes"})):
        assert ready.post(path, data).status_code == 403, path
    assert status_of(app, a) == "published"


def test_set_default_persists_and_every_child_uses_it(app, ready, admin):
    first, second = island(app, "beach"), island(app, "forest")
    assert admin.post("/admin/3d/islands/default", {"id": second}).status_code == 302            # no confirmation: refused
    assert default_setting(app) != str(second)
    admin.post("/admin/3d/islands/default", {"id": first, "confirm": "yes"})
    assert default_setting(app) == str(first) and base_id(ready) == first
    ready.jpost("/api/world/settings", {"island": str(second)})                                     # a personal choice is ignored (locked for everyone)
    assert base_id(ready) == first
    admin.post("/admin/3d/islands/default", {"id": second, "confirm": "yes"})
    assert default_setting(app) == str(second) and base_id(ready) == second                         # persisted server-side
    with app.app_context():
        assert sum(1 for a in islands.library.island_bases() if str(a.id) == settings_service.get("default_island_id")) == 1   # exactly one default


def test_unpublished_or_unknown_islands_cannot_become_default(app, admin):
    live, draft = island(app, "beach"), island(app, "wip", status="review")
    admin.post("/admin/3d/islands/default", {"id": live, "confirm": "yes"})
    admin.post("/admin/3d/islands/default", {"id": draft, "confirm": "yes"})
    admin.post("/admin/3d/islands/default", {"id": 987654, "confirm": "yes"})
    assert default_setting(app) == str(live)


def test_delete_needs_confirmation_and_is_soft(app, admin):
    first, second = island(app, "beach"), island(app, "forest")
    admin.post("/admin/3d/islands/default", {"id": first, "confirm": "yes"})
    admin.post("/admin/3d/islands/delete", {"ids": second})                                         # no confirm: nothing happens
    assert status_of(app, second) == "published"
    admin.post("/admin/3d/islands/delete", {"ids": second, "confirm": "yes"})
    assert status_of(app, second) == "deleted"                                                      # recoverable, row and files kept
    assert b"forest" not in admin.get("/admin/3d/islands").data.split(b"Recently deleted")[0]
    assert b"Recently deleted" in admin.get("/admin/3d/islands").data
    admin.post("/admin/3d/islands/restore", {"id": second})
    assert status_of(app, second) == "published"


def test_default_island_is_protected_from_delete_single_and_bulk(app, admin):
    first, second, third = island(app, "beach"), island(app, "forest"), island(app, "city")
    admin.post("/admin/3d/islands/default", {"id": first, "confirm": "yes"})
    admin.post("/admin/3d/islands/delete", {"ids": first, "confirm": "yes"})
    assert status_of(app, first) == "published"
    admin.post("/admin/3d/islands/delete", {"ids": [first, second, third], "confirm": "yes"})       # one protected island blocks the whole selection
    assert [status_of(app, i) for i in (first, second, third)] == ["published"] * 3
    admin.post("/admin/3d/islands/default", {"id": second, "confirm": "yes"})                      # choose another default first ...
    admin.post("/admin/3d/islands/delete", {"ids": first, "confirm": "yes"})                        # ... then the old one can go
    assert status_of(app, first) == "deleted" and default_setting(app) == str(second)


def test_automatic_default_is_protected_too(app, admin):
    only = island(app, "beach")                                                                      # nothing chosen: the newest published one is used
    admin.post("/admin/3d/islands/delete", {"ids": only, "confirm": "yes"})
    assert status_of(app, only) == "published"


def test_bulk_delete_removes_only_the_selection(app, admin):
    keep, a, b = island(app, "beach"), island(app, "forest"), island(app, "city")
    admin.post("/admin/3d/islands/default", {"id": keep, "confirm": "yes"})
    admin.post("/admin/3d/islands/delete", {"ids": [a, b], "confirm": "yes"})
    assert [status_of(app, i) for i in (keep, a, b)] == ["published", "deleted", "deleted"]


def test_delete_all_needs_the_phrase_resets_default_and_keeps_everything_else(app, ready, admin):
    a, b = island(app, "beach"), island(app, "forest")
    admin.post("/admin/3d/islands/default", {"id": a, "confirm": "yes"})
    cid = my_child(app)
    with app.app_context():
        landmark = Asset3D(category="music", archetype="lm_music", kind="landmark", name="Music place", provider="manual", status="published",
                           stage="done", glb_filename="m.glb")
        friend = Asset3D(category="food", archetype="cupcake", kind="item", name="Cupcake", provider="manual", status="published", stage="done",
                         glb_filename="c.glb")
        Session.add_all([landmark, friend])
        event(cid, item("video", "sports"), "watch", 60)
        Session.commit()
        keep_ids, users, events = [landmark.id, friend.id], Session.query(User).count(), Session.query(ActivityEvent).count()
    admin.post("/admin/3d/islands/delete-all", {"confirm": "yes", "phrase": "delete"})              # wrong phrase
    assert status_of(app, a) == "published"
    admin.post("/admin/3d/islands/delete-all", {"confirm": "yes", "phrase": "DELETE ALL"})
    assert status_of(app, a) == status_of(app, b) == "deleted"
    assert default_setting(app) == "" and settings_service_lock(app) == "0"                         # nothing points at a deleted island
    assert base_id(ready) is None                                                                   # children fall back to the built-in map
    with app.app_context():
        assert [Session.get(Asset3D, i).status for i in keep_ids] == ["published", "published"]    # place landmarks and friends untouched
        assert Session.query(User).count() == users and Session.query(ActivityEvent).count() == events
    assert b"No default world yet" in admin.get("/admin/3d/islands").data                           # setup state


def settings_service_lock(app):
    with app.app_context():
        return settings_service.get("island_lock")


def test_purge_keeps_files_another_asset_still_uses(app, admin, tmp_path):
    import os
    a, b = island(app, "beach"), island(app, "forest")
    with app.app_context():
        from services.ai3d import library
        shared = "shared-model.glb"
        for i in (a, b):
            Session.get(Asset3D, i).glb_filename = shared
        Session.get(Asset3D, a).status = "deleted"
        Session.commit()
        open(os.path.join(library.private_dir(), shared), "wb").write(b"x")
    admin.post("/admin/3d/islands/purge", {"ids": a, "confirm": "yes"})
    assert status_of(app, a) is None and status_of(app, b) == "published"
    with app.app_context():
        from services.ai3d import library
        assert os.path.exists(os.path.join(library.private_dir(), "shared-model.glb"))              # still referenced by another island
    admin.post("/admin/3d/islands/purge", {"ids": b, "confirm": "yes"})                              # not in the trash: refused
    assert status_of(app, b) == "published"


def test_the_old_delete_button_cannot_destroy_the_default_island(app, admin):
    a, b = island(app, "beach"), island(app, "forest")
    admin.post("/admin/3d/islands/default", {"id": a, "confirm": "yes"})
    admin.post(f"/admin/3d/{a}/delete")
    assert status_of(app, a) == "published"
    admin.post(f"/admin/3d/{b}/delete")
    assert status_of(app, b) == "deleted"


def test_deleting_islands_never_touches_child_activity(app, ready, admin):
    cid = my_child(app)
    a, b = island(app, "beach"), island(app, "forest")
    with app.app_context():
        event(cid, item("song", "music"), "listen", 90)
        Session.commit()
        before = Session.query(ActivityEvent).count()
    admin.post("/admin/3d/islands/default", {"id": a, "confirm": "yes"})
    admin.post("/admin/3d/islands/delete", {"ids": b, "confirm": "yes"})
    admin.post("/admin/3d/islands/delete-all", {"confirm": "yes", "phrase": "DELETE ALL"})
    admin.post("/admin/3d/islands/purge", {"all": "yes", "confirm": "yes"})
    with app.app_context():
        assert Session.query(ActivityEvent).count() == before
