import json
from datetime import date, timedelta
from conftest import Client, subscribe_and_approve, ONB, PW
from database.db import Session
from database.models import (CaregiverQuestionnaire, InterestProfile, Interaction, ContentItem, ChildProfile, Favorite,
                             DailyActivity, utcnow)
from services import recommendation_service as rec, content_service as cs, youtube_service, spotify_service, image_service, safety
from services.errors import ServiceError


def test_onboarding_requires_consent_and_persists(app, client, admin):
    client.register(); subscribe_and_approve(app, client, admin)
    assert client.post("/onboarding", {"display_name": "Sunny"}).status_code == 400    # no consent
    assert client.post("/onboarding", ONB).status_code == 302
    with app.app_context():
        q = Session.query(CaregiverQuestionnaire).one()
        assert json.loads(q.responses_json)["interests"] == ["animals", "music"]
        seeds = {r.category: r.caregiver_seed for r in Session.query(InterestProfile)}
        assert seeds["animals"] == 4 and seeds["music"] == 4 and seeds["dancing"] == 1.5


def test_onboarding_gate_before_feed(app, client, admin):
    client.register(); subscribe_and_approve(app, client, admin)
    assert "/onboarding" in client.get("/home").location


def test_interest_score_updates_and_rules(app, ready):
    with app.app_context():
        child = Session.query(ChildProfile).one()
        item = cs.upsert({"provider": "demo", "provider_content_id": "d1", "content_type": "picture", "title": "Puppy",
                          "category": "animals", "tags": ["puppy"]})
        before = {i["category"]: i for i in rec.get_interests(child.id)}["animals"]["score"]
        rec.record_interaction(child.id, item, "like")
        after = {i["category"]: i for i in rec.get_interests(child.id)}["animals"]["score"]
        assert after > before
        rec.record_interaction(child.id, item, "skip")                   # skip is recorded, not scored
        assert {i["category"]: i for i in rec.get_interests(child.id)}["animals"]["score"] == after
        rec.record_interaction(child.id, item, "dislike")                # one dislike never wipes out a category
        assert {i["category"]: i for i in rec.get_interests(child.id)}["animals"]["score"] > 0
        assert item.id in rec.disliked_ids(child.id)
        assert Session.query(Interaction).filter_by(interaction_type="skip").count() == 1


def test_caregiver_seed_fades_with_child_evidence(app, ready):
    with app.app_context():
        child = Session.query(ChildProfile).one()
        row = Session.query(InterestProfile).filter_by(child_profile_id=child.id, category="music").one()
        assert rec.seed_factor(0) == 1.0 and rec.seed_factor(20) == 0.25
        assert rec.effective_score(row) == 4.0


def test_recency_decay():
    class R: caregiver_seed = 0; evidence_count = 3; interest_score = 8.0; last_observed_at = utcnow() - timedelta(days=45)
    assert abs(rec.effective_score(R) - 4.0) < 0.05


def test_picture_to_video_and_music_recommendations(app, ready):
    with app.app_context():
        item = cs.upsert({"provider": "demo", "provider_content_id": "dog", "content_type": "picture", "title": "Dog",
                          "category": "animals", "tags": ["puppy"]})
        iid = item.id
    r = ready.get(f"/api/related/{iid}").get_json()
    assert r["pictures"] and r["videos"] and r["songs"]
    assert all(v["category"] == "animals" for v in r["videos"] + r["songs"])
    assert r["notice"] and "demo" in r["notice"].lower()


def test_related_excludes_disliked_and_filters_unsafe(app, ready, monkeypatch):
    with app.app_context():
        item = cs.upsert({"provider": "demo", "provider_content_id": "dog2", "content_type": "picture", "title": "Dog",
                          "category": "animals", "tags": ["puppy"]})
        iid = item.id
    vids = ready.get(f"/api/related/{iid}").get_json()["videos"]
    ready.jpost("/api/react", {"content_id": vids[0]["id"], "type": "dislike"})
    again = ready.get(f"/api/related/{iid}").get_json()["videos"]
    assert vids[0]["id"] not in [v["id"] for v in again]
    assert not safety.is_allowed("Scary horror video") and safety.is_allowed("Friendly puppy")
    assert not safety.is_allowed("puppy spiders", extra_blocklist=["spiders"])


def test_react_endpoint_validation_and_dedupe(app, ready):
    pics = ready.get("/api/pictures?category=animals").get_json()["items"]
    cid = pics[0]["id"]
    assert ready.jpost("/api/react", {"content_id": cid, "type": "hack"}).status_code == 400
    assert ready.jpost("/api/react", {"content_id": "1", "type": "like"}).status_code == 400
    assert ready.jpost("/api/react", {"content_id": cid, "type": "like"}).get_json()["counted"] is True
    assert ready.jpost("/api/react", {"content_id": cid, "type": "like"}).get_json()["counted"] is False
    assert ready.jpost("/api/favorite", {"content_id": cid}).get_json()["favorite"] is True
    assert ready.get("/api/favorites").get_json()["items"][0]["id"] == cid


def test_feed_is_built_from_questionnaire(app, ready):
    d = ready.get("/api/feed").get_json()
    cats = [s["category"] for s in d["sections"]]
    assert "animals" in cats or "music" in cats
    assert all(s["items"] for s in d["sections"])
    assert len(d["sections"]) == 4 and all(s["reason"] for s in d["sections"])
    seeded = [s for s in d["sections"] if s["category"] in ("animals", "music")]
    assert seeded and "caregiver mentioned" in seeded[0]["reason"]


def test_calendar_shows_real_events_only(app, ready):
    today = date.today().isoformat()
    assert ready.get(f"/api/journey/day/{today}").get_json()["app_events"] == []
    cid = ready.get("/api/pictures?category=nature").get_json()["items"][0]["id"]
    ready.jpost("/api/react", {"content_id": cid, "type": "like"})
    ready.post("/journey/activity", {"title": "Danced in the kitchen", "activity_date": today})
    d = ready.get(f"/api/journey/day/{today}").get_json()
    assert any("Liked 1 nature picture" in l for l in d["app_events"])
    assert d["recorded"][0]["title"] == "Danced in the kitchen"
    assert ready.get("/journey").status_code == 200 and ready.get("/journey?view=week").status_code == 200
    assert ready.get("/api/journey/day/not-a-date").status_code == 404


def test_clear_history(app, ready):
    cid = ready.get("/api/pictures?category=nature").get_json()["items"][0]["id"]
    ready.jpost("/api/react", {"content_id": cid, "type": "like"})
    ready.post("/journey/clear", {"scope": "all"})
    with app.app_context():
        assert Session.query(Interaction).count() == 0


def test_user_data_isolation(app, ready, admin):
    b = Client(app); b.register("dad"); subscribe_and_approve(app, b, admin, ref="DADREF99"); b.post("/onboarding", ONB)
    ready.post("/journey/activity", {"title": "Private moment", "activity_date": date.today().isoformat()})
    with app.app_context():
        act_id = Session.query(DailyActivity).one().id
    assert b.post(f"/journey/activity/{act_id}/delete").status_code == 404        # cannot delete another's record
    assert "Private moment" not in b.get(f"/api/journey/day/{date.today().isoformat()}").get_data(as_text=True)
    with app.app_context():
        assert Session.query(DailyActivity).count() == 1
    with app.app_context():
        mum_sub = __import__("database.models", fromlist=["Subscription"]).Subscription
        sid = Session.query(mum_sub).filter_by(user_id=1).first()
    assert b.get("/subscription/payment/1").status_code in (302, 404)
    assert b.get("/subscription/verify/1").status_code == 404


def test_world_controls(app, ready):
    ready.post("/world/interest/sports", {"mode": "more"})
    page = ready.get("/world")
    assert page.status_code == 200
    assert b"Animal Garden" in page.data and b"Music Garden" in page.data
    assert b"Sports Arena" in page.data and b'id="world3d"' in page.data and b'id="world-data"' in page.data
    ready.post("/world/interest/animals", {"mode": "less"})
    with app.app_context():
        child = Session.query(ChildProfile).one()
        assert {i["category"]: i for i in rec.get_interests(child.id)}["animals"]["score"] < 0
    ready.post("/world/interest/animals", {"mode": "remove"})
    ready.post("/world/reset")
    with app.app_context():
        assert Session.query(InterestProfile).count() == 0
    assert ready.post("/world/interest/bogus", {"mode": "more"}).status_code == 302


def test_updates_and_settings_pages(app, ready):
    assert ready.post("/updates", {"new_interests": ["vehicles"], "avoid_keywords": "clowns", "private": "note"}).status_code == 302
    assert b"clowns" in ready.get("/settings").data
    assert ready.post("/settings/preferences", {"screen_time_minutes": "20", "display_name": "Sam", "large_text": "on"}).status_code == 302
    exp = ready.get("/settings/export")
    assert exp.status_code == 200 and json.loads(exp.data)["username"] == "mum"
    for url in ("/pictures", "/videos", "/shots", "/music", "/journey", "/world", "/updates", "/settings", "/privacy"):
        assert ready.get(url).status_code == 200, url


def test_deletion_request_and_admin_delete(app, ready, admin):
    ready.post("/settings/delete-request", {"confirm": "DELETE"})
    with app.app_context():
        from database.models import User
        uid = Session.query(User).filter_by(username="mum").one().id
    admin.post(f"/admin/users/{uid}/delete")
    with app.app_context():
        assert Session.query(User).filter_by(username="mum").count() == 0
        assert Session.query(ChildProfile).count() == 0


def test_external_api_failure_falls_back_to_demo(app, ready, monkeypatch):
    app.config.update(YOUTUBE_API_KEY="k", SPOTIFY_CLIENT_ID="a", SPOTIFY_CLIENT_SECRET="b", PEXELS_API_KEY="p")
    def boom(*a, **k): raise ServiceError("Videos are unavailable right now.")
    monkeypatch.setattr(youtube_service, "search_videos", boom)
    monkeypatch.setattr(spotify_service, "search_tracks", boom)
    monkeypatch.setattr(image_service, "search_images", boom)
    for url in ("/api/videos?category=animals", "/api/music?category=animals", "/api/pictures?category=animals", "/api/shots"):
        r = ready.get(url)
        d = r.get_json()
        assert r.status_code == 200 and d["items"] and d["notice"] and all(i["demo"] for i in d["items"])
        if url.startswith("/api/videos"):
            sample = d["items"][0]
            assert sample["video_id"] == "aqz-KE-bpKQ"
            assert sample["embed"].startswith("https://www.youtube-nocookie.com/embed/aqz-KE-bpKQ")


def test_video_demo_is_playable_without_youtube_api_key(app, ready):
    app.config["YOUTUBE_API_KEY"] = ""
    data = ready.get("/api/videos?category=animals").get_json()
    sample = data["items"][0]
    assert data["notice"] == "Live video search isn't set up yet. You can still watch this sample video."
    assert sample["demo"] is True
    assert sample["video_id"] == "aqz-KE-bpKQ"
    assert sample["url"] == "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
    assert sample["embed"] == "https://www.youtube-nocookie.com/embed/aqz-KE-bpKQ?rel=0&modestbranding=1"


def test_real_provider_results_are_mapped_and_filtered(app, ready, monkeypatch):
    app.config.update(YOUTUBE_API_KEY="k")
    good = dict(provider="youtube", provider_content_id="abc123", content_type="video", title="Cute puppies play", description="",
                thumbnail_url="https://i.ytimg.com/x.jpg", canonical_url="https://www.youtube.com/watch?v=abc123", category="animals",
                tags=[], attribution={"channel": "Kids"})
    bad = dict(good, provider_content_id="zzz999", title="Scary horror puppies")
    monkeypatch.setattr(youtube_service, "search_videos", lambda *a, **k: [good, bad])
    d = ready.get("/api/videos?category=animals").get_json()
    titles = [i["title"] for i in d["items"]]
    assert "Cute puppies play" in titles and "Scary horror puppies" not in titles
    assert d["items"][0]["embed"].startswith("https://www.youtube-nocookie.com/embed/")
    assert d["items"][0]["provider_content_id"] == good["provider_content_id"]
    assert d["items"][0]["thumb"] == good["thumbnail_url"]
    assert d["items"][0]["url"] == good["canonical_url"]

    no_thumbnail = dict(good, provider_content_id="no-thumbnail", thumbnail_url="")
    monkeypatch.setattr(youtube_service, "search_videos", lambda *a, **k: [no_thumbnail])
    fallback = ready.get("/api/videos?category=animals&page=2").get_json()["items"][0]
    assert fallback["thumb"] == "https://i.ytimg.com/vi/no-thumbnail/hqdefault.jpg"


def test_youtube_duration_and_quota(app, monkeypatch):
    assert youtube_service.parse_duration("PT45S") == 45 and youtube_service.parse_duration("PT1M5S") == 65
    app.config["YOUTUBE_API_KEY"] = "k"
    class Resp: status_code = 403; text = '{"error":{"errors":[{"reason":"quotaExceeded"}]}}'
    monkeypatch.setattr("services.youtube_service.requests.get", lambda *a, **k: Resp())
    import pytest
    with app.app_context(), pytest.raises(ServiceError):
        youtube_service.search_videos("dogs")


def test_spotify_and_pexels_mapping(app):
    t = {"id": "t1", "name": "Song", "artists": [{"name": "A"}], "album": {"name": "Al", "images": [{"url": "u1"}, {"url": "u2"}]},
         "external_urls": {"spotify": "https://open.spotify.com/track/t1"}}
    assert spotify_service.map_track(t, "music")["attribution"]["artist"] == "A"
    p = {"id": 5, "alt": "dog", "src": {"large": "L"}, "url": "u", "photographer": "Ann", "photographer_url": "pu"}
    assert image_service.map_photo(p, "animals")["attribution"]["source"] == "Pexels"


def test_security_headers(client):
    r = client.get("/")
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"] and b"Built and Powered by Emtrixz" in r.data
