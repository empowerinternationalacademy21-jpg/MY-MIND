"""One family username, separate passwords: caretaker dashboard vs each child's own world."""
from conftest import CPW, ONB, PW
from database.db import Session
from database.models import ChildProfile, User
from services import plan_service, settings_service
from services.plan_config import FREE_CHILD_PROFILE_LIMIT, TRIAL_CHILD_PROFILE_LIMIT

ALEX_PW = "Alex!Secret8901"


def _add(client, name, password):
    return client.post("/caretaker/children/add", {"display_name": name, "avatar": "star", "age": "8",
                                                    "consent": "yes", "child_password": password})


def test_same_username_caretaker_and_child_passwords_open_different_pages(ready):
    ready.post("/logout")
    assert ready.login("mum", PW).location.endswith("/caretaker")
    ready.post("/logout")
    assert ready.login("mum", CPW).location.endswith("/world")
    assert b"Sunny" in ready.get("/world").data
    assert ready.get("/caretaker").status_code == 403          # a child can never open caretaker pages
    ready.post("/logout")
    assert ready.login("mum", "wrong-password1").status_code == 401


def test_several_children_each_open_their_own_world(ready, app):
    assert _add(ready, "Alex", ALEX_PW).status_code == 302
    assert _add(ready, "Bea", "Bea!Secret1357x").status_code == 302
    with app.app_context():
        assert Session.query(ChildProfile).count() == 3
    ready.post("/logout")
    assert ready.login("mum", ALEX_PW).location.endswith("/world")
    assert b"Alex's World" in ready.get("/world").data
    ready.post("/logout")
    assert ready.login("mum", "Bea!Secret1357x").location.endswith("/world")
    assert b"Bea's World" in ready.get("/world").data
    ready.post("/logout")
    assert ready.login("mum", CPW).location.endswith("/world")
    assert b"Sunny's World" in ready.get("/world").data


def test_child_password_must_be_different_from_caretaker_and_siblings(ready, app):
    _add(ready, "Same as mum", PW)
    _add(ready, "Same as Sunny", CPW)
    _add(ready, "No password", "")
    with app.app_context():
        assert Session.query(ChildProfile).count() == 1        # all three were refused
    assert _add(ready, "Alex", ALEX_PW).status_code == 302
    with app.app_context():
        assert Session.query(ChildProfile).count() == 2


def test_caretaker_can_reset_a_child_password(ready, app):
    with app.app_context():
        uid = Session.query(ChildProfile).one().public_uid
    assert ready.post(f"/caretaker/children/{uid}/password", {"child_password": "Fresh!Secret9753"}).status_code == 302
    ready.post("/logout")
    assert ready.login("mum", CPW).status_code == 401
    assert ready.login("mum", "Fresh!Secret9753").location.endswith("/world")


def test_child_has_own_settings_page_and_can_change_own_password(ready):
    ready.post("/logout")
    ready.login("mum", CPW)
    assert ready.get("/me/settings").status_code == 200
    assert ready.get("/settings").status_code == 403
    changed = ready.post("/me/settings", {"action": "password", "current": CPW,
                                          "new": "Newer!Secret2468", "confirm": "Newer!Secret2468"})
    assert changed.status_code == 302
    ready.post("/logout")
    assert ready.login("mum", CPW).status_code == 401
    assert ready.login("mum", "Newer!Secret2468").location.endswith("/world")
    ready.post("/logout")
    ready.login("mum", PW)
    assert ready.get("/me/settings").status_code == 302        # caretakers use their own settings


def test_free_plan_manages_one_child_not_ten(client, app):
    client.register("freeparent")
    client.post("/subscription/select", {"plan": "free"})
    assert client.post("/onboarding", ONB).status_code == 302
    assert _add(client, "Second", ALEX_PW).status_code == 302
    with app.app_context():
        user = Session.query(User).filter_by(username="freeparent").one()
        assert plan_service.child_limit(user.id) == FREE_CHILD_PROFILE_LIMIT == 1
        assert Session.query(ChildProfile).filter_by(caregiver_user_id=user.id).count() == 1


def test_free_trial_also_manages_one_child(client, app):
    with app.app_context():
        settings_service.set_value("trial_days", "30"); Session.commit()
    client.register("trialparent")
    assert client.post("/onboarding", ONB).status_code == 302
    assert _add(client, "Second", ALEX_PW).status_code == 302
    with app.app_context():
        user = Session.query(User).filter_by(username="trialparent").one()
        assert plan_service.current_plan(user.id) == "trial"
        assert plan_service.child_limit(user.id) == TRIAL_CHILD_PROFILE_LIMIT == 1
        assert Session.query(ChildProfile).filter_by(caregiver_user_id=user.id).count() == 1
