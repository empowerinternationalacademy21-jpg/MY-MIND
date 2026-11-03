"""My World art library: admin uploads are validated, re-encoded and served only to eligible viewers."""
import io
import os
import re
import pytest
from PIL import Image
from database.db import Session
from database.models import AuditLog, WorldAsset


def png(w=64, h=48, color=(200, 40, 40), exif=False):
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    if exif:
        ex = img.getexif(); ex[0x010F] = "SecretCamera"                          # camera make written into the upload
        img.save(buf, "JPEG", exif=ex)
    else:
        img.save(buf, "PNG")
    return buf.getvalue()


def upload(admin, raw, filename="a.png", **over):
    form = {"kind": "character", "stop": "sports", "zone": "football", "theme": "football", "name": "Goalie", "caption": "A friendly goalie",
            "rights_confirmed": "on", "source_note": ""}
    form.update(over)
    form = {k: v for k, v in form.items() if v is not None}
    form["image"] = (io.BytesIO(raw), filename)
    return admin.post("/admin/world/upload", form, content_type="multipart/form-data", follow_redirects=True)


def rows(app):
    with app.app_context():
        return Session.query(WorldAsset).all()


def test_upload_is_reencoded_to_webp_with_metadata_stripped(app, admin):
    r = upload(admin, png(exif=True), "photo.jpg")
    assert "Art added" in r.get_data(as_text=True)
    with app.app_context():
        a = Session.query(WorldAsset).one()
        assert re.fullmatch(r"[0-9a-f]{32}\.webp", a.filename) and a.width == 64 and a.height == 48 and a.rights_confirmed
        path = os.path.join(app.config["WORLD_ASSET_DIR"], a.filename)
        img = Image.open(path)
        assert img.format == "WEBP" and len(img.getexif()) == 0 and b"SecretCamera" not in open(path, "rb").read()
        assert any(x.action == "world_asset_added" for x in Session.query(AuditLog).all())
        assert os.listdir(app.config["WORLD_ASSET_DIR"]) == [a.filename]            # the original upload is not kept


def test_large_images_are_scaled_down(app, admin):
    upload(admin, png(4000, 3000))
    with app.app_context():
        a = Session.query(WorldAsset).one(); assert max(a.width, a.height) == 2048


@pytest.mark.parametrize("raw,name,msg", [
    (b"just some text pretending to be a picture", "x.png", "could not be read"),
    (b"GIF89a" + b"\x00" * 40, "x.gif", "could not be read"),
    (png()[:-30], "cut.png", "could not be read"),
    (png(8, 8), "tiny.png", "too small"),
])
def test_bad_files_are_refused(app, admin, raw, name, msg):
    r = upload(admin, raw, name)
    assert msg in r.get_data(as_text=True) and rows(app) == []


def test_pixel_bomb_is_refused(app, admin):
    buf = io.BytesIO(); Image.new("L", (9000, 9000), 0).save(buf, "PNG")                    # ~81M pixels, tiny file
    r = upload(admin, buf.getvalue())
    assert "could not be read" in r.get_data(as_text=True) and rows(app) == []


def test_rights_real_person_and_field_rules(app, admin):
    assert "right to use" in upload(admin, png(), rights_confirmed=None).get_data(as_text=True)
    assert "source or licence" in upload(admin, png(), is_real_person="on", source_note="").get_data(as_text=True)
    assert "valid kind" in upload(admin, png(), kind="weird").get_data(as_text=True)
    assert "valid stop" in upload(admin, png(), stop="../../etc").get_data(as_text=True)
    assert "only applies to the Sports" in upload(admin, png(), stop="music", zone="football").get_data(as_text=True)
    assert "choose a valid" in upload(admin, png(), zone="polo").get_data(as_text=True)
    assert "valid stop" in upload(admin, png(), stop="").get_data(as_text=True)
    assert rows(app) == []
    assert "Art added" in upload(admin, png(), kind="background", stop="", zone="").get_data(as_text=True) and len(rows(app)) == 1


def test_oversize_upload_is_rejected(app, admin):
    app.config["WORLD_UPLOAD_MAX_BYTES"] = 2000
    noisy = io.BytesIO(); Image.frombytes("RGB", (200, 200), os.urandom(120000)).save(noisy, "PNG")
    r = upload(admin, noisy.getvalue())
    assert rows(app) == [] and ("too large" in r.get_data(as_text=True) or r.status_code == 413)


def test_only_admins_can_manage_the_library(app, ready, client):
    assert client.get("/admin/world/").status_code in (302, 403)
    assert ready.get("/admin/world/").status_code == 403
    assert ready.post("/admin/world/upload", {"kind": "character"}).status_code == 403
    assert ready.post("/admin/world/1/delete").status_code == 403


def test_caregiver_serving_rules_and_real_person_toggle(app, ready, admin):
    upload(admin, png(), name="Fox")                     # original art
    upload(admin, png(color=(10, 10, 200)), name="Star", is_real_person="on", source_note="Licensed from Photo Agency, contract 12")
    with app.app_context():
        safe = Session.query(WorldAsset).filter_by(is_real_person=False).one(); real = Session.query(WorldAsset).filter_by(is_real_person=True).one()
        safe_f, real_f = safe.filename, real.filename
    assert ready.get(f"/world-assets/{safe_f}").status_code == 200
    assert ready.get(f"/world-assets/{safe_f}").headers["Content-Type"] == "image/webp"
    assert ready.get(f"/world-assets/{real_f}").status_code == 404                       # real people: off by default
    api = ready.get("/api/world-assets").get_json()["assets"]
    assert [a["name"] for a in api] == ["Fox"] and "Fox" in ready.get("/world").get_data(as_text=True)
    assert "Not affiliated" not in ready.get("/world").get_data(as_text=True)
    ready.post("/settings/preferences", {"display_name": "Sunny", "screen_time_minutes": "30", "show_real_people": "on"})
    assert ready.get(f"/world-assets/{real_f}").status_code == 200
    api = ready.get("/api/world-assets?kind=character").get_json()["assets"]
    star = [a for a in api if a["real_person"]][0]
    assert "Not affiliated" in star["disclaimer"] and "Not affiliated" in ready.get("/world").get_data(as_text=True)
    # bad names never touch the disk
    for bad in ("../app.py", "..%2fapp.py", "x.webp", "0" * 32 + ".png", "0" * 32 + ".webp"):
        assert ready.get(f"/world-assets/{bad}").status_code == 404
    assert Client_anon(app).get(f"/world-assets/{safe_f}").status_code == 302          # not logged in


def Client_anon(app):
    from conftest import Client
    return Client(app)


def test_hide_show_delete(app, ready, admin):
    upload(admin, png(), name="Fox")
    with app.app_context():
        a = Session.query(WorldAsset).one(); aid, fn = a.id, a.filename
    path = os.path.join(app.config["WORLD_ASSET_DIR"], fn)
    assert admin.get(f"/admin/world/{aid}/preview").status_code == 200
    admin.post(f"/admin/world/{aid}/hide")
    assert ready.get(f"/world-assets/{fn}").status_code == 404 and ready.get("/api/world-assets").get_json()["assets"] == []
    assert admin.get(f"/admin/world/{aid}/preview").status_code == 200                       # admin can still see it
    admin.post(f"/admin/world/{aid}/show")
    assert ready.get(f"/world-assets/{fn}").status_code == 200
    assert admin.post(f"/admin/world/{aid}/explode").status_code == 404
    admin.post(f"/admin/world/{aid}/delete")
    assert rows(app) == [] and not os.path.exists(path) and admin.post("/admin/world/999/delete").status_code == 404
