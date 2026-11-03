from datetime import date, timedelta
from conftest import PW, Client, subscribe_and_approve
from database.db import Session
from database.models import User, Subscription, PaymentVerificationRequest, AuditLog, utcnow


def test_registration_and_password_hashing(app, client):
    r = client.register("mum")
    assert r.status_code == 302 and "/subscription" in r.location
    with app.app_context():
        u = Session.query(User).filter_by(username="mum").one()
        assert u.password_hash.startswith("$argon2id$") and PW not in u.password_hash


def test_duplicate_username_rejected_by_app_and_db(app, client):
    client.register("Mum")
    r = Client(app).register("mum")
    assert r.status_code == 400 and b"already taken" in r.data
    import pytest
    from sqlalchemy.exc import IntegrityError
    with app.app_context():
        Session.add(User(username="mum", password_hash="x"))
        with pytest.raises(IntegrityError):
            Session.commit()
        Session.rollback()


def test_input_validation(client):
    for name, pw in (("a", PW), ("bad name!", PW), ("okname", "short1"), ("okname", "alllettersnodigits")):
        assert client.register(name, pw).status_code == 400
    assert client.post("/register", {"username": "okname", "password": PW, "confirm": "different1234"}).status_code == 400


def test_login_logout_and_protection(client):
    client.register("mum"); client.post("/logout")
    assert client.get("/home").status_code == 302          # protected
    assert client.login("mum", "wrong-password1").status_code == 401
    assert client.login("mum").status_code == 302
    client.post("/logout")
    assert "/login" in client.get("/home").location


def test_login_rate_limit(client):
    client.register("mum"); client.post("/logout")
    for _ in range(5):
        client.login("mum", "badpassword123")
    assert client.login("mum").status_code == 429


def test_csrf_enforced(app):
    c = app.test_client()
    r = c.post("/login", data={"username": "x", "password": "y"})
    assert r.status_code == 302 and "/login" in r.location


def test_payment_flow_requires_admin_approval(app, client, admin):
    client.register()
    assert "/subscription" in client.get("/home").location          # no access yet
    client.post("/subscription/select", {"plan": "monthly"})
    with app.app_context():
        sub = Session.query(Subscription).one()
        assert sub.amount == 50 and sub.status == "pending_payment"
    r = client.post(f"/subscription/verify/{sub.id}", {"payment_reference": "TXN-9981", "payment_date": date.today().isoformat()})
    assert r.status_code == 302
    assert "/subscription" in client.get("/onboarding").location     # still pending -> blocked
    assert b"submitted" in client.get("/subscription/").data
    with app.app_context():
        assert Session.query(Subscription).one().status == "pending_verification"
        rid = Session.query(PaymentVerificationRequest).one().id
    admin.post(f"/admin/payments/{rid}/approve", {"note": "seen in bank"})
    assert client.get("/onboarding").status_code == 200
    with app.app_context():
        s = Session.query(Subscription).one()
        assert s.status == "active" and (s.expires_at - s.starts_at).days == 30


def test_plan_prices(app, client):
    client.register()
    for code, price in (("weekly", 25), ("monthly", 50), ("yearly", 250)):
        client.post("/subscription/select", {"plan": code})
        with app.app_context():
            assert Session.query(Subscription).first().amount == price


def test_rejection_and_duplicate_approval_prevented(app, client, admin):
    client.register()
    sid, rid = subscribe_and_approve(app, client, admin)
    r = admin.post(f"/admin/payments/{rid}/approve", {})          # second approval
    assert b"already decided" in admin.get("/admin/payments").data or r.status_code == 302
    with app.app_context():
        assert Session.query(Subscription).filter_by(status="active").count() == 1
        assert Session.query(AuditLog).filter_by(action="payment_approved").count() == 1
    c2 = Client(app); c2.register("dad")
    sid2, rid2 = subscribe_and_approve(app, c2, admin, ref="TXN7777")
    c3 = Client(app); c3.register("aunt")
    c3.post("/subscription/select", {"plan": "weekly"})
    with app.app_context():
        sub3 = Session.query(Subscription).filter_by(status="pending_payment").one()
    c3.post(f"/subscription/verify/{sub3.id}", {"payment_reference": "TXN5555", "payment_date": date.today().isoformat()})
    with app.app_context():
        rid3 = Session.query(PaymentVerificationRequest).filter_by(payment_reference="TXN5555").one().id
    admin.post(f"/admin/payments/{rid3}/reject", {"note": "not found"})
    assert "/subscription" in c3.get("/home").location
    with app.app_context():
        assert Session.query(Subscription).filter_by(id=sub3.id).one().status == "rejected"


def test_duplicate_payment_reference_rejected(app, client, admin):
    client.register(); subscribe_and_approve(app, client, admin, ref="SAMEREF1")
    c2 = Client(app); c2.register("dad"); c2.post("/subscription/select", {"plan": "weekly"})
    with app.app_context():
        sid = Session.query(Subscription).filter_by(status="pending_payment").one().id
    r = c2.post(f"/subscription/verify/{sid}", {"payment_reference": "sameref1", "payment_date": date.today().isoformat()})
    assert r.status_code == 400


def test_subscription_expiry_blocks_access(app, ready):
    home = ready.get("/home")
    assert home.status_code == 200
    assert b"fd-workspace" in home.data and b"Explore spaces" in home.data
    with app.app_context():
        s = Session.query(Subscription).one(); s.expires_at = utcnow() - timedelta(days=1); Session.commit()
    r = ready.get("/home")
    assert r.status_code == 302 and "/subscription" in r.location
    assert ready.jpost("/api/react", {"content_id": 1, "type": "like"}).status_code in (302, 403)
    with app.app_context():
        assert Session.query(Subscription).one().status == "expired"


def test_admin_routes_protected(app, ready, client):
    assert ready.get("/admin/").status_code == 403
    assert Client(app).get("/admin/").status_code == 302


def test_admin_settings_and_whatsapp_link(app, admin, ready):
    admin.post("/admin/settings", {"whatsapp_number": "+256 700 000000", "contact_phone": "+256700000000", "bank_name": "Test Bank",
                                   "bank_account_name": "Emtrixz", "bank_account_number": "000111", "payment_instructions": "Pay.",
                                   "weekly_price": "25", "weekly_days": "7", "monthly_price": "50", "monthly_days": "30",
                                   "yearly_price": "250", "yearly_days": "365", "shots_enabled": "on"})
    from services import settings_service
    with app.app_context():
        assert settings_service.whatsapp_url(settings_service.get("whatsapp_number")).startswith("https://wa.me/256700000000")
    assert admin.post("/admin/settings", {"whatsapp_number": "<script>", "weekly_price": "1", "weekly_days": "1"}).status_code == 302


def test_placeholders_when_unconfigured(app, client):
    client.register(); client.post("/subscription/select", {"plan": "weekly"})
    with app.app_context():
        sid = Session.query(Subscription).one().id
    assert b"NOT SET" in client.get(f"/subscription/payment/{sid}").data


def test_suspended_account_blocked(app, ready, admin):
    with app.app_context():
        uid = Session.query(User).filter_by(username="mum").one().id
    admin.post(f"/admin/users/{uid}/status")
    assert "/login" in ready.get("/home").location
