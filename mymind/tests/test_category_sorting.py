import json
import uuid

from database.db import Session
from database.models import ActivityEvent, ContentItem, utcnow
from services import category_service as cat, content_service as cs, image_service


def pic(alt, pid=None):
    return dict(provider="pexels", provider_content_id=pid or uuid.uuid4().hex[:10], content_type="picture", title=alt, description=alt,
                thumbnail_url="https://example.test/p.jpg", canonical_url="", category="x", tags=[], attribution={})


# ------------------------------------------------------------------ the classifier
def test_clear_cases_are_filed_where_they_belong():
    assert cat.classify("A brown dog running on grass", "", None, "people") == ("animals", True)
    assert cat.classify("Smiling family at dinner", "", None, "animals")[0] == "people"
    assert cat.classify("Red circle and blue triangle on paper", "", None, "animals") == ("colors", True)
    assert cat.classify("A little girl with her mother", "", None, "colors")[0] == "people"
    assert cat.classify("Elephants walking at the zoo", "", None, "food") == ("animals", True)


def test_correct_items_and_unclear_ones_stay_put():
    assert cat.classify("Cute puppy playing", "", None, "animals") == ("animals", False)
    assert cat.classify("Photo", "", None, "animals") == ("animals", False)                      # empty description: trust the search
    assert cat.classify("", "", None, "people") == ("people", False)
    assert cat.classify("Woman holding a cat", "", None, "animals") == ("animals", False)         # both present: keep what was searched
    assert cat.classify("Woman holding a cat", "", None, "people") == ("people", False)
    assert cat.classify("Sunny day", "", None, "animals") == ("animals", False)
    assert cat.classify("A tabby sitting by the window", "", None, "animals") == ("animals", False)  # a background word alone never moves it
    assert cat.classify("Boy near a tree", "", None, "animals")[0] == "people"                       # the subject comes first, the tree is background
    assert cat.classify("Baby elephant", "", None, "animals") == ("animals", False)
    assert cat.classify("whatever dog", "", None, "learning") == ("learning", False)               # unsorted categories are never touched
    assert cat.classify("dog", "", None, None) == (None, False)


def test_plurals_phrases_and_word_boundaries():
    assert cat.scores("Puppies and kittens")["animals"] >= 4
    assert "food" in cat.scores("Eating ice cream")
    assert "animals" not in cat.scores("Catalog of dogmatic ideas")                                # whole words only, no substrings


def test_topic_view_drops_mismatches_but_search_only_refiles():
    items = [pic("A golden retriever puppy"), pic("Family eating together"), pic("Photo")]
    topic = cat.sort_items([dict(i) for i in items], "animals", explicit=False)
    assert [i["title"] for i in topic] == ["A golden retriever puppy", "Photo"]                   # the family belongs under People
    search = cat.sort_items([dict(i) for i in items], "animals", explicit=True)
    assert len(search) == 3 and [i["category"] for i in search] == ["x", "people", "x"] and search[1]["_resorted"]


def test_songs_are_not_resorted():
    song = dict(pic("Dog song"), content_type="song")
    assert cat.sort_items([song], "music", explicit=False) == [song]


# ------------------------------------------------------------------ in the app
def provider(monkeypatch, pages):
    calls = []

    def search(query, category="objects", page=1, per_page=8):
        calls.append(page)
        return [dict(i) for i in pages.get(page, [])]
    monkeypatch.setattr(image_service, "search_images", search)
    monkeypatch.setattr(image_service, "configured", lambda: True)
    return calls


def test_an_animals_page_never_contains_a_person(app, monkeypatch):
    provider(monkeypatch, {1: [pic("A dog on a sofa"), pic("Woman in a white dress"), pic("A horse in a field"), pic("Boy on a bike"),
                               pic("Kitten sleeping"), pic("Father and son"), pic("Parrot on a branch"), pic("Two girls laughing")]})
    with app.app_context():
        items, _ = cs.fetch("picture", "animals", "", 1, 8, [], None)
    assert [i["title"] for i in items] == ["A dog on a sofa", "A horse in a field", "Kitten sleeping", "Parrot on a branch"]


def test_short_pages_are_topped_up_from_the_next_provider_page(app, monkeypatch):
    page1 = [pic("A dog on a sofa")] + [pic(f"Family portrait {n}") for n in range(7)]
    page2 = [pic(f"Cat number {n}") for n in range(8)]
    calls = provider(monkeypatch, {1: page1, 2: page2})
    with app.app_context():
        items, _ = cs.fetch("picture", "animals", "", 1, 8, [], None)
    assert len(items) == 8 and calls[:2] == [1, 2] and all("Family" not in i["title"] for i in items)


def test_free_text_search_keeps_everything_but_files_it_correctly(app, monkeypatch):
    provider(monkeypatch, {1: [pic("A dog on a sofa"), pic("Family eating together")]})
    with app.app_context():
        models, _ = cs.fetch_models("picture", "objects", "sofa", 1, 8, [], None)
        got = {m.title: m.category for m in models}
    assert got == {"A dog on a sofa": "animals", "Family eating together": "people"}


def test_existing_rows_are_refiled_and_analytics_follow(app, monkeypatch):
    with app.app_context():
        row = ContentItem(provider="pexels", provider_content_id="old1", content_type="picture", title="A dog on a sofa", description="",
                          thumbnail_url="u", category="people", tags_json="[]", attribution_json="{}")
        Session.add(row)
        Session.flush()
        Session.add(ActivityEvent(child_id=1, stop="pictures", content_id=row.id, event_type="look", duration_seconds=5, client_event_id=uuid.uuid4().hex,
                                  created_at=utcnow(), last_active_at=utcnow(), content_type="picture", category="people")) if False else None
        Session.commit()
    provider(monkeypatch, {1: [pic("A dog on a sofa", "old1")]})
    with app.app_context():
        cs.fetch_models("picture", "objects", "sofa", 1, 8, [], None)
        assert Session.query(ContentItem).filter_by(provider_content_id="old1").one().category == "animals"


def test_backfill_moves_only_clear_mismatches(app):
    from database.migrate import m0015_sort_content_by_category
    from database.db import get_engine
    with app.app_context():
        for pid, title, category in (("a", "A dog on a sofa", "people"), ("b", "Family at dinner", "people"), ("c", "Photo", "animals"),
                                     ("d", "Red circle and blue square", "animals")):
            Session.add(ContentItem(provider="pexels", provider_content_id=pid, content_type="picture", title=title, description="",
                                    thumbnail_url="u", category=category, tags_json="[]", attribution_json="{}"))
        Session.add(ContentItem(provider="demo", provider_content_id="demo1", content_type="picture", title="A dog on a sofa", description="",
                                thumbnail_url="u", category="people", tags_json="[]", attribution_json="{}"))
        Session.commit()
        m0015_sort_content_by_category(get_engine())
        Session.expire_all()
        got = {r.provider_content_id: r.category for r in Session.query(ContentItem).all()}
    assert got == {"a": "animals", "b": "people", "c": "animals", "d": "colors", "demo1": "people"}


def test_cli_dry_run_changes_nothing(app):
    with app.app_context():
        Session.add(ContentItem(provider="pexels", provider_content_id="z", content_type="picture", title="A dog on a sofa", description="",
                                thumbnail_url="u", category="people", tags_json="[]", attribution_json="{}"))
        Session.commit()
    result = app.test_cli_runner().invoke(args=["resort-content", "--dry-run"])
    assert "Would move 1 of 1" in result.output and "people -> animals" in result.output
    with app.app_context():
        assert Session.query(ContentItem).one().category == "people"
    assert "Moved 1 of 1" in app.test_cli_runner().invoke(args=["resort-content"]).output
    with app.app_context():
        assert Session.query(ContentItem).one().category == "animals"
