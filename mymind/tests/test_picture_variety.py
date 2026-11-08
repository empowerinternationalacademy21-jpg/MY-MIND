from services import content_service as cs, image_service


def fake_search(calls):
    def search(query, category="objects", page=1, per_page=8):
        calls.append((query, page))
        return [dict(provider="pexels", provider_content_id=f"{query}-{page}-{i}", content_type="picture", title=f"{query} {i}",
                     description="", thumbnail_url="https://example.test/p.jpg", canonical_url="", category=category, tags=[],
                     attribution={}) for i in range(6)] if page < 20 else []
    return search


def first_page(app, monkeypatch, seed, page=1):
    calls = []
    monkeypatch.setattr(image_service, "search_images", fake_search(calls))
    monkeypatch.setattr(image_service, "configured", lambda: True)
    with app.app_context():
        items, _ = cs.fetch("picture", "animals", "", page, 6, [], None, seed)
    return [i["provider_content_id"] for i in items], calls


def test_without_a_seed_nothing_changes(app, monkeypatch):
    a, _ = first_page(app, monkeypatch, None)
    b, _ = first_page(app, monkeypatch, None)
    assert a == b


def test_same_seed_is_stable_and_different_seeds_differ(app, monkeypatch):
    a, _ = first_page(app, monkeypatch, 12345)
    again, _ = first_page(app, monkeypatch, 12345)
    assert a == again                                                   # scrolling inside one visit stays consistent
    variants = {tuple(first_page(app, monkeypatch, seed)[0]) for seed in range(40)}
    assert len(variants) > 10                                           # many different first screens across visits


def test_seeds_change_the_search_words_and_provider_page(app, monkeypatch):
    searches = {first_page(app, monkeypatch, seed)[1][0] for seed in range(40)}
    assert len({q for q, _ in searches}) > 3 and len({p for _, p in searches}) > 1


def test_pages_of_one_visit_do_not_repeat_searches(app, monkeypatch):
    seen = []
    for page in range(1, 6):
        seen.append(first_page(app, monkeypatch, 777, page)[1][0])
    assert len(set(seen)) == len(seen)


def test_too_deep_start_falls_back_instead_of_going_empty(app, monkeypatch):
    calls = []
    monkeypatch.setattr(image_service, "configured", lambda: True)

    def search(query, category="objects", page=1, per_page=8):
        calls.append(page)
        return [] if page > 1 else fake_search([])(query, category, 1, per_page)
    monkeypatch.setattr(image_service, "search_images", search)
    with app.app_context():
        items = [cs.fetch("picture", "animals", "", 1, 6, [], None, s)[0] for s in range(30)]
    assert all(items)                                                   # never an empty screen
    assert 1 in calls


def test_videos_ignore_the_seed(app, monkeypatch):
    with app.app_context():
        a, _ = cs.fetch("video", "animals", "", 1, 3, [], None, 1)
        b, _ = cs.fetch("video", "animals", "", 1, 3, [], None, 999)
    assert [i["provider_content_id"] for i in a] == [i["provider_content_id"] for i in b]


def test_demo_pictures_also_vary_per_seed(app):
    with app.app_context():
        a = {tuple(i["provider_content_id"] for i in cs.fetch("picture", "animals", "", 1, 6, [], None, s)[0]) for s in range(10)}
        none = [i["provider_content_id"] for i in cs.fetch("picture", "animals", "", 1, 6, [], None, None)[0]]
        again = [i["provider_content_id"] for i in cs.fetch("picture", "animals", "", 1, 6, [], None, None)[0]]
    assert len(a) > 1 and none == again


def test_api_accepts_seed_and_ignores_garbage(app, ready):
    from conftest import CPW
    from database.db import Session
    from database.models import ChildProfile
    with app.app_context():
        username = Session.query(ChildProfile).first().caregiver.child_username
    ready.post("/logout")
    assert ready.login(username, CPW).status_code == 302
    for seed in ("123", "-5", "abc", "99999999999999999999"):
        response = ready.get(f"/api/pictures?seed={seed}&page=1")
        assert response.status_code == 200 and response.get_json()["items"], seed
    first = [i["provider_content_id"] for i in ready.get("/api/pictures?seed=1&page=1&cat=animals").get_json()["items"]]
    assert first == [i["provider_content_id"] for i in ready.get("/api/pictures?seed=1&page=1&cat=animals").get_json()["items"]]
    assert ready.get("/api/feed?seed=7&page=1").status_code == 200
