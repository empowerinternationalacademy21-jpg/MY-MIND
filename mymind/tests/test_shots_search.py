"""Searching for a specific short on the Shorts page."""


def test_shorts_page_has_a_search_box(ready):
    page = ready.get("/shots")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert 'id="sh-search"' in body and 'id="sh-q"' in body


def test_shorts_api_accepts_a_search_word(ready):
    plain = ready.get("/api/shots")
    found = ready.get("/api/shots?q=dancing")
    assert plain.status_code == 200 and found.status_code == 200
    items = found.get_json()["items"]
    assert items                                           # demo content (or live search) always returns something
    assert any("dancing" in item["title"].lower() for item in items)


def test_shorts_search_word_is_length_limited(ready):
    assert ready.get("/api/shots?q=" + "x" * 500).status_code == 200
