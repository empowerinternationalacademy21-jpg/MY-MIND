from datetime import timedelta

from database.db import Session
from database.models import ChildProfile, Subscription, User, utcnow
from services import plan_service
from services.plan_config import FREE_CHILD_PROFILE_LIMIT, PAID_CHILD_PROFILE_LIMIT
from conftest import ONB, PW


def test_free_plan_feature_gates_and_profile_limit(client, app):
    client.register("freeparent")
    client.post("/subscription/select", {"plan": "free"})
    with app.app_context():
        user = Session.query(User).filter_by(username="freeparent").one()
        assert plan_service.current_plan(user.id) == "free"
        assert plan_service.can_use(user.id, "dashboard_basic")
        assert not plan_service.can_use(user.id, "export_report")
        assert plan_service.history_days(user.id) == 7
        assert plan_service.child_limit(user.id) == FREE_CHILD_PROFILE_LIMIT == 1
    assert client.post("/onboarding", ONB).status_code == 302
    response = client.post("/caretaker/children/add", {"display_name": "Second", "avatar": "smile", "consent": "yes"})
    assert response.status_code == 302
    assert "upgrade" in client.get("/caretaker/children").get_data(as_text=True).lower()
    with app.app_context():
        assert Session.query(ChildProfile).filter_by(caregiver_user_id=user.id).count() == 1


def test_paid_plan_add_child_and_child_login_selects_correct_profile(ready, app):
    result = ready.post("/caretaker/children/add", {
        "display_name": "Alex", "avatar": "star", "age": "8", "consent": "yes",
    })
    assert result.status_code == 302
    with app.app_context():
        children = Session.query(ChildProfile).order_by(ChildProfile.id).all()
        assert len(children) == 2 and children[1].child_username
        child_name = children[1].child_username
    ready.post("/logout")
    login = ready.login(child_name, PW)
    assert login.status_code == 302 and login.location.endswith("/world")
    page = ready.get("/world")
    assert page.status_code == 200 and b"Alex's World" in page.data
    assert ready.get("/caretaker").status_code == 403


def test_paid_profile_limit_constant_and_expiry_keeps_extra_children_read_only(ready, app):
    ready.post("/caretaker/children/add", {"display_name": "Extra", "avatar": "star", "consent": "yes"})
    with app.app_context():
        user = Session.query(User).filter_by(username="mum").one()
        sub = Session.query(Subscription).filter_by(user_id=user.id, status="active").one()
        sub.expires_at = utcnow() - timedelta(seconds=1)
        Session.commit()
        assert PAID_CHILD_PROFILE_LIMIT >= 10
        children = Session.query(ChildProfile).filter_by(caregiver_user_id=user.id).order_by(ChildProfile.id).all()
        assert plan_service.current_plan(user.id) == "free"
        assert plan_service.child_is_read_only(user.id, children[0]) is False
        assert plan_service.child_is_read_only(user.id, children[1]) is True
        assert not plan_service.can_use(user.id, "export_report")
    assert ready.get("/home").status_code == 200
    assert ready.get("/caretaker/report.csv").status_code == 302


def test_cancel_at_period_end_preserves_current_access(ready, app):
    with app.app_context():
        sub = Session.query(Subscription).filter_by(status="active").one()
        period_end = sub.expires_at
    response = ready.post("/subscription/cancel")
    assert response.status_code == 302
    with app.app_context():
        sub = Session.query(Subscription).filter_by(status="active").one()
        assert sub.cancel_at_period_end and sub.expires_at == period_end
        assert plan_service.has_basic_access(sub.user_id)
