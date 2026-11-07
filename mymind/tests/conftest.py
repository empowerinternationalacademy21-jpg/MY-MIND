import os, sys
os.environ["MYMIND_NO_AUTOAPP"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest
from datetime import date, timedelta
from app import create_app
from database.db import Session
from database.models import User
from services import auth_service, cache

PW = "Sup3rSecret!pw"
CPW = "Kid!Secret4567"          # the first child's OWN password (never the caretaker's)


@pytest.fixture()
def app(tmp_path):
    cache.rate_reset(); cache.cache_clear()
    fake = None
    db_url = f"sqlite:///{tmp_path}/t.db"
    if os.environ.get("MYMIND_TEST_BACKEND") == "hrana":      # run the whole suite through the Turso HTTP driver
        from fake_turso import FakeTurso
        fake = FakeTurso(str(tmp_path / "turso.db")); db_url = fake.url
    a = create_app({"TESTING": True, "DATABASE_URL": db_url, "SECRET_KEY": "test-secret",
                    "YOUTUBE_API_KEY": "", "SPOTIFY_CLIENT_ID": "", "SPOTIFY_CLIENT_SECRET": "", "PEXELS_API_KEY": "",
                    "WORLD_ASSET_DIR": str(tmp_path / "world_assets"), "AI3D_PRIVATE_DIR": str(tmp_path / "ai3d_private")})
    with a.app_context():
        auth_service.create_admin("boss", "AdminPass123!x")
        from services import settings_service
        settings_service.set_value("trial_days", "0"); Session.commit()   # legacy tests assume no trial
    yield a
    if fake:
        fake.stop()


class Client:
    def __init__(self, app):
        self.c = app.test_client(); self.app = app

    def token(self):
        self.c.get("/privacy")
        with self.c.session_transaction() as s:
            return s.get("csrf", "")

    def post(self, url, data=None, **kw):
        data = dict(data or {}); data["csrf_token"] = self.token()
        return self.c.post(url, data=data, **kw)

    def jpost(self, url, payload):
        return self.c.post(url, json=payload, headers={"X-CSRFToken": self.token()})

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def register(self, name="mum", pw=PW):
        return self.post("/register", {"username": name, "password": pw, "confirm": pw})

    def login(self, name, pw=PW):
        return self.post("/login", {"username": name, "password": pw})


@pytest.fixture()
def client(app):
    return Client(app)


@pytest.fixture()
def admin(app):
    c = Client(app); c.login("boss", "AdminPass123!x"); return c


def subscribe_and_approve(app, caregiver, admin, plan="weekly", ref="TXN12345"):
    caregiver.post("/subscription/select", {"plan": plan})
    from database.models import Subscription, PaymentVerificationRequest
    with app.app_context():
        sub = Session.query(Subscription).order_by(Subscription.id.desc()).first(); sid = sub.id
    caregiver.post(f"/subscription/verify/{sid}", {"payment_reference": ref, "payment_date": date.today().isoformat(), "note": ""})
    with app.app_context():
        rid = Session.query(PaymentVerificationRequest).filter_by(subscription_id=sid).first().id
    admin.post(f"/admin/payments/{rid}/approve", {"note": "ok"})
    return sid, rid


ONB = {"consent": "yes", "display_name": "Sunny", "child_password": CPW, "avatar": "smile", "interests": ["animals", "music"], "activities": ["dance"]}


@pytest.fixture()
def ready(app, client, admin):
    """A caregiver with an approved subscription and finished onboarding."""
    client.register()
    subscribe_and_approve(app, client, admin)
    client.post("/onboarding", ONB)
    return client
