"""Seeds a throw-away MyMind instance with realistic data and serves it for the browser tests (default port 5055)."""
import io, os, shutil, sys, json, tempfile
from pathlib import Path
os.environ["MYMIND_NO_AUTOAPP"] = "1"
ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT); sys.path.insert(0, ROOT + "/tests")
from PIL import Image, ImageDraw
from app import create_app
from database.db import Session
from database.models import Asset3D, ChildProfile
from services import auth_service, cache, recommendation_service as rec, settings_service
from conftest import Client, ONB, subscribe_and_approve
from glb_factory import make_solid_glb, make_island_glb, make_house_glb
from services.ai3d import library, optimize

base = tempfile.mkdtemp(prefix="mymind-e2e-")
app = create_app({"TESTING": True, "DATABASE_URL": f"sqlite:///{base}/d.db", "SECRET_KEY": "dev-secret", "YOUTUBE_API_KEY": "", "SPOTIFY_CLIENT_ID": "",
                  "SPOTIFY_CLIENT_SECRET": "", "PEXELS_API_KEY": "", "WORLD_ASSET_DIR": f"{base}/world", "AI3D_PRIVATE_DIR": f"{base}/ai3d", "SESSION_COOKIE_SECURE": False})
with app.app_context():
    auth_service.create_admin("boss", "AdminPass123!x"); settings_service.set_value("trial_days", "0"); Session.commit()
admin = Client(app); admin.login("boss", "AdminPass123!x")
mum = Client(app); mum.register(); subscribe_and_approve(app, mum, admin); mum.post("/onboarding", ONB)

def face(color, bg, eyes="#17325f"):
    im = Image.new("RGB", (256, 256), bg); d = ImageDraw.Draw(im)
    d.ellipse((28, 28, 228, 228), fill=color); d.ellipse((84, 96, 108, 128), fill=eyes); d.ellipse((148, 96, 172, 128), fill=eyes)
    d.arc((78, 120, 178, 196), 20, 160, fill=eyes, width=7); b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()
def field():
    im = Image.new("RGB", (800, 240), "#7fd37a"); d = ImageDraw.Draw(im)
    for i in range(0, 800, 100): d.rectangle((i, 0, i + 50, 240), fill="#74c870")
    d.rectangle((20, 20, 780, 220), outline="white", width=5); d.ellipse((350, 70, 450, 170), outline="white", width=5)
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()
def up(kind, stop, name, raw, zone="", theme=""):
    admin.post("/admin/world/upload", {"kind": kind, "stop": stop, "zone": zone, "theme": theme, "name": name, "caption": f"{name} says hi!", "rights_confirmed": "on",
                                       "image": (io.BytesIO(raw), "a.png")}, content_type="multipart/form-data")
up("character", "sports", "Goalie Gus", face("#ffb347", "#d6f0ff"), zone="football"); up("character", "sports", "Hoop Hana", face("#ff8fa3", "#ffe9cf"))
up("character", "music", "Drummer Dee", face("#c9a8ff", "#f0e6ff")); up("character", "food", "Scoop Sam", face("#ffd6e0", "#ffe8ee"))
up("character", "nature", "Fern Fox", face("#ff9a56", "#e2f7f1")); up("interior", "sports", "Pitch", field())
with app.app_context():
    cid = Session.query(ChildProfile).one().id
    for cat, n in (("music", 7), ("nature", 4), ("food", 3), ("sports", 4), ("animals", 1), ("vehicles", 1)):
        for _ in range(n): rec.record_interaction(cid, None, "like", category=cat)
    d = library.private_dir()
    open(f"{d}/1-glb-seed.glb", "wb").write(optimize.optimize(make_solid_glb((0.98, 0.45, 0.2, 1.0), radius=0.6))[0])
    open(f"{d}/1-bob-seed.glb", "wb").write(make_solid_glb((0.98, 0.45, 0.2, 1.0), animated=True, radius=0.6))
    Session.add(Asset3D(category="sports", archetype="soccer_ball", kind="item", name="Bouncy Ball", caption="A friendly ball", provider="meshy", status="published", stage="done",
                        glb_filename="1-glb-seed.glb", clips_json='{"bob": "1-bob-seed.glb"}', options_json="{}", tasks_json="{}", prompt="p", stats_json=json.dumps({"triangles": 432, "bytes": 9000, "optimizer": "gltf-transform"})))
    # island kit: an AI-made island base and a house landmark for Home (everything else keeps the built-in look)
    open(f"{d}/2-glb-seed.glb", "wb").write(optimize.optimize(make_island_glb())[0]); open(f"{d}/3-glb-seed.glb", "wb").write(make_house_glb())
    for jid, cat, arch, name, fn in ((2, "island", "lm_island", "Island base", "2-glb-seed.glb"), (3, "home", "lm_home", "Home", "3-glb-seed.glb")):
        Session.add(Asset3D(category=cat, archetype=arch, kind="landmark", name=name, provider="meshy", status="published", stage="done", glb_filename=fn, clips_json="{}",
                            options_json="{}", tasks_json="{}", prompt="p", stats_json=json.dumps({"triangles": 100, "bytes": 5000})))
    Session.commit()
mum.jpost("/api/world/settings", {"sports_zones": ["football", "swimming"]})
print("seeded; serving", flush=True)
app.run(port=int(os.environ.get("PORT", "5055")), threaded=True, use_reloader=False)
