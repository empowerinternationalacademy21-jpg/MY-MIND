"""The administrator's 3D island applies to every user's My World (server-side, so on every device)."""
from database.db import Session
from database.models import Asset3D


def _island(app, name):
    with app.app_context():
        a = Asset3D(category="island", archetype="island_base", kind="landmark", name=name, provider="manual",
                    status="published", stage="done", glb_filename=f"{name}.glb")
        Session.add(a); Session.commit()
        return a.id


def _base_id(client):
    base = client.get("/api/world").get_json()["island_base"]
    return base["id"] if base else None


def test_default_island_only_reaches_people_without_a_personal_choice(app, ready, admin):
    first, second = _island(app, "beach"), _island(app, "forest")
    assert ready.jpost("/api/world/settings", {"island": str(first)}).status_code == 200
    admin.post("/admin/3d/island", {"island": str(second)})            # no lock: default only
    assert _base_id(ready) == first                                     # personal choice still wins


def test_locked_island_replaces_personal_choices_everywhere(app, ready, admin):
    first, second = _island(app, "beach"), _island(app, "forest")
    ready.jpost("/api/world/settings", {"island": str(first)})
    assert _base_id(ready) == first
    admin.post("/admin/3d/island", {"island": str(second), "lock": "on"})
    assert _base_id(ready) == second                                    # same answer on any device: it comes from the server
    data = ready.get("/api/world").get_json()
    assert data["island_locked"] is True and data["options"]["islands"] == []
    changed = ready.jpost("/api/world/settings", {"island": str(first)})   # a personal change is ignored while locked
    assert changed.status_code == 200 and _base_id(ready) == second
    assert b'name="island"' not in ready.get("/settings").data           # the picker is hidden


def test_admin_can_lock_the_classic_look_and_unlock_again(app, ready, admin):
    first = _island(app, "beach")
    admin.post("/admin/3d/island", {"island": "classic", "lock": "on"})
    assert _base_id(ready) is None
    admin.post("/admin/3d/island", {"island": str(first)})              # unlocked, default = beach
    assert _base_id(ready) == first
    assert ready.get("/api/world").get_json()["island_locked"] is False


def test_use_this_island_for_everyone_button_and_admin_only(app, ready, admin):
    island = _island(app, "beach")
    assert ready.post("/admin/3d/island", {"island": str(island), "lock": "on"}).status_code == 403
    assert admin.post(f"/admin/3d/{island}/island-for-everyone").status_code == 302
    assert _base_id(ready) == island
    assert admin.post("/admin/3d/island", {"island": "999999"}).status_code == 302   # unknown island refused
    assert _base_id(ready) == island
