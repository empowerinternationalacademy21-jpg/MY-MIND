from database.db import Session
from database.models import ChildProfile, User, utcnow
from conftest import PW


def test_edit_and_archive_child_keeps_profile_data_but_disables_login(ready, app):
    ready.post("/caretaker/children/add", {"display_name": "Mika", "avatar": "star", "age": "7", "consent": "yes",
                                            "child_password": "Mika!Secret2468"})
    with app.app_context():
        child = Session.query(ChildProfile).filter_by(display_name="Mika").one()
        child_id, child_username = child.id, child.child_username
    edit = ready.post(f"/caretaker/children/{child_id}/edit", {
        "display_name": "Mika Rose", "avatar": "flower-2", "age": "8",
    })
    assert edit.status_code == 302
    with app.app_context():
        child = Session.get(ChildProfile, child_id)
        assert child.display_name == "Mika Rose" and child.age_years == 8
    assert ready.post(f"/caretaker/children/{child_id}/archive").status_code == 302
    with app.app_context():
        child = Session.get(ChildProfile, child_id)
        assert child.archived_at is not None
    ready.post("/logout")
    assert ready.login(child_username, PW).status_code == 401


def test_paid_child_limit_is_enforced_server_side(ready, app):
    with app.app_context():
        user = Session.query(User).filter_by(username="mum").one()
        for index in range(2, 11):
            Session.add(ChildProfile(caregiver_user_id=user.id, display_name=f"Child {index}",
                                     avatar="smile", child_username=f"mum.kid{index}", created_at=utcnow()))
        Session.commit()
        user_id = user.id
    result = ready.post("/caretaker/children/add", {
        "display_name": "Eleventh", "avatar": "smile", "consent": "yes",
    })
    assert result.status_code == 302
    with app.app_context():
        assert Session.query(ChildProfile).filter_by(caregiver_user_id=user_id, archived_at=None).count() == 10
    assert "upgrade" in ready.get("/caretaker/children").get_data(as_text=True).lower()
