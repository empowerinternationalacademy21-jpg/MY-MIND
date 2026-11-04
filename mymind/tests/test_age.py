"""Age-appropriate content (ages 3-25)."""
import pytest
from conftest import Client, subscribe_and_approve, ONB
from database.db import Session
from database.models import ChildProfile
from services import age_service as A, content_service as cs
from services.categories import CATEGORIES, LEGACY_CATEGORIES


def _set_age(app, age):
    with app.app_context():
        Session.query(ChildProfile).one().age_years = age
        Session.commit()


def test_parse_age_and_bands():
    assert A.parse_age("") is None and A.parse_age(None) is None and A.parse_age(" 7 ") == 7
    for bad in ("2", "26", "abc", "7.5", "-3"):
        with pytest.raises(A.AgeError):
            A.parse_age(bad)
    edges = {3: "little", 5: "little", 6: "young", 8: "young", 9: "tween", 12: "tween", 13: "teen", 17: "teen", 18: "adult", 25: "adult"}
    for age, key in edges.items():
        assert A.band_key(age) == key
    assert A.band_key(2) is None and A.band_key(26) is None and A.band_key(None) is None and A.band_for(None) is None


def test_no_age_keeps_original_behaviour():
    assert A.allowed_categories(None) == list(LEGACY_CATEGORIES)
    assert A.audience_for(None) == "kids" and A.extra_blocklist(None) == []
    assert A.keywords_for("animals", None) == CATEGORIES["animals"]["keywords"]


def test_every_band_category_and_keyword_exists():
    for key, b in A.BANDS.items():
        for c in b["categories"]:
            assert c in CATEGORIES, (key, c)
            assert A.keywords_for(c, b["min"]), (key, c)
        assert set(b["keywords"]) <= set(b["categories"]), key


def test_categories_and_keywords_change_with_age():
    assert "toys" in A.allowed_categories(4) and "toys" not in A.allowed_categories(10)
    assert "careers" not in A.allowed_categories(8) and "careers" in A.allowed_categories(15) and "careers" in A.allowed_categories(22)
    assert A.keywords_for("animals", 4) != A.keywords_for("animals", 15)
    assert A.audience_for(4) == "kids" and A.audience_for(15) == "" and A.audience_for(22) == ""
    assert "dating" in A.extra_blocklist(8) and A.extra_blocklist(20) == []
    assert list(A.categories_for(15, ["animals", "toys", "careers"])) == ["animals", "careers"]


def test_blocklist_includes_age_words(app):
    with app.app_context():
        assert "dating" in cs.blocklist_for({"avoid_keywords": ""}, 7)
        assert "dating" not in cs.blocklist_for({"avoid_keywords": ""}, 19)


def test_migration_adds_column(app):
    with app.app_context():
        assert "age_years" in [c["name"] for c in __import__("sqlalchemy").inspect(Session.get_bind()).get_columns("child_profiles")]


def test_onboarding_stores_age_and_rejects_bad_age(app, client, admin):
    client.register(); subscribe_and_approve(app, client, admin)
    assert client.post("/onboarding", dict(ONB, age="30")).status_code == 400
    assert client.post("/onboarding", dict(ONB, age="abc")).status_code == 400
    assert client.post("/onboarding", dict(ONB, age="11")).status_code == 302
    with app.app_context():
        assert Session.query(ChildProfile).one().age_years == 11


def test_settings_age_save_validate_and_blank_keeps(app, ready):
    assert ready.post("/settings/preferences", {"display_name": "Sunny", "age": "16"}).status_code == 302
    with app.app_context():
        assert Session.query(ChildProfile).one().age_years == 16
    ready.post("/settings/preferences", {"display_name": "Sunny", "age": "99"})          # rejected, unchanged
    ready.post("/settings/preferences", {"display_name": "Sunny", "age": ""})            # blank, unchanged
    with app.app_context():
        assert Session.query(ChildProfile).one().age_years == 16
    page = ready.get("/settings").get_data(as_text=True)
    assert 'name="age"' in page and "Teens" in page


def test_feed_and_listings_follow_age(app, ready):
    _set_age(app, 15)
    home = ready.get("/home").get_data(as_text=True)
    assert 'data-cat="careers"' in home and 'data-cat="toys"' not in home
    assert 'data-cat="toys"' not in ready.get("/pictures").get_data(as_text=True)
    r = ready.get("/api/pictures?category=toys").get_json()                              # not offered at 15 -> ignored
    assert r["category"] != "toys"
    items = ready.get("/api/pictures?category=careers").get_json()["items"]
    assert items and all(i["category"] == "careers" for i in items)
    titles = " ".join(i["title"].lower() for i in items)
    assert any(k in titles for k in A.keywords_for("careers", 15))
    vids = ready.get("/api/videos?category=careers").get_json()["items"]
    assert vids and all("for teens" in v["title"] for v in vids)
    feed = ready.get("/api/feed").get_json()
    allowed = set(A.allowed_categories(15))
    assert all(s["category"] in allowed for s in feed["sections"])


def test_little_child_gets_little_content(app, ready):
    _set_age(app, 4)
    home = ready.get("/home").get_data(as_text=True)
    assert 'data-cat="toys"' in home and 'data-cat="careers"' not in home
    vids = ready.get("/api/videos?category=animals").get_json()["items"]
    assert vids and all("for kids" in v["title"] for v in vids)


def test_export_includes_age(app, ready):
    _set_age(app, 9)
    assert '"age_years": 9' in ready.get("/settings/export").get_data(as_text=True).replace('":9', '": 9')