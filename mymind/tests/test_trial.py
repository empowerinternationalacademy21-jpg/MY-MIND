from datetime import timedelta
from conftest import Client, subscribe_and_approve, ONB
from database.db import Session
from database.models import Subscription, utcnow
from services import settings_service


def enable_trial(app, days="30"):
    with app.app_context():
        settings_service.set_value("trial_days", days); Session.commit()


def test_new_user_gets_free_trial_and_access(app, client):
    enable_trial(app)
    r = client.register()
    assert "/onboarding" in r.location                       # no payment step needed
    assert client.post("/onboarding", ONB).status_code == 302
    assert client.get("/home").status_code == 200
    with app.app_context():
        s = Session.query(Subscription).one()
        assert s.plan_code == "trial" and s.amount == 0 and s.status == "active" and (s.expires_at - s.starts_at).days == 30


def test_expired_trial_downgrades_to_free_until_paid_plan(app, client, admin):
    enable_trial(app)
    client.register(); client.post("/onboarding", ONB)
    with app.app_context():
        s = Session.query(Subscription).one(); s.expires_at = utcnow() - timedelta(minutes=1); Session.commit()
    r = client.get("/home")
    assert r.status_code == 200
    assert client.get("/api/feed").status_code == 200
    assert "/subscription" in client.get("/caretaker/report.csv").location
    assert b"now on Free" in client.get("/subscription/").data
    subscribe_and_approve(app, client, admin, ref="AFTERTRIAL1")          # paying reopens it
    assert client.get("/home").status_code == 200


def test_paying_during_trial_stacks_after_trial(app, client, admin):
    enable_trial(app)
    client.register()
    subscribe_and_approve(app, client, admin, plan="weekly", ref="EARLYPAY1")
    with app.app_context():
        trial = Session.query(Subscription).filter_by(plan_code="trial").one()
        paid = Session.query(Subscription).filter_by(plan_code="weekly").one()
        assert paid.starts_at >= trial.expires_at and (paid.expires_at - paid.starts_at).days == 7


def test_trial_disabled_and_only_once(app, client):
    r = client.register()                                    # trial_days = 0 in fixture
    assert "/subscription" in r.location
    enable_trial(app, "14")
    c2 = Client(app); c2.register("dad")
    with app.app_context():
        assert Session.query(Subscription).filter_by(plan_code="trial").count() == 1
        from services import payment_service
        from database.models import User
        u = Session.query(User).filter_by(username="dad").one()
        assert payment_service.start_trial(u) is None        # a second trial is refused
