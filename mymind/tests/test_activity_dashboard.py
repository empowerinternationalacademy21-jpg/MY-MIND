import uuid
from datetime import timedelta
from types import SimpleNamespace

from conftest import CPW, PW, Client
from database.db import Session
from database.models import ActivityEvent, ChildProfile, ContentItem, User, utcnow
from services import activity_analytics_service as analytics
from services import activity_service, interest_discovery_service as discovery, world_service


def eid():
    return str(uuid.uuid4())


def make_item(kind="video", category="sports", title=None):
    item = ContentItem(provider="demo", provider_content_id=eid()[:12], content_type=kind, title=title or f"{category} {kind}",
                       thumbnail_url="https://example.test/t.jpg", category=category)
    Session.add(item)
    Session.flush()
    return item


def add_event(child_id, item, kind, seconds, at, **kw):
    row = ActivityEvent(child_id=child_id, stop={"watch": "videos", "listen": "music", "look": "pictures"}.get(kind, "home"),
                        content_id=item.id if item else None, content_title=item.title if item else None, event_type=kind,
                        duration_seconds=seconds, client_event_id=eid(), created_at=at, last_active_at=at + timedelta(seconds=seconds),
                        content_type=item.content_type if item else None, category=kw.pop("category", item.category if item else None), **kw)
    Session.add(row)
    return row


def child_id_of(app, username="mum"):
    with app.app_context():
        return Session.query(ChildProfile).join(User, User.id == ChildProfile.caregiver_user_id).filter(User.username == username).first().id


def login_as_child(app, client):
    with app.app_context():
        username = Session.query(ChildProfile).first().caregiver.child_username
    client.post("/logout")
    assert client.login(username, CPW).status_code == 302
    return client


# ------------------------------------------------------------------ tracking endpoint
def test_session_detail_is_stored_and_never_shrinks(app, ready):
    login_as_child(app, ready)
    with app.app_context():
        video, song, pic = make_item("video", "music"), make_item("song", "music"), make_item("picture", "animals")
        Session.commit()
        vid, sid, pid = video.id, song.id, pic.id
    watch, listen, look = eid(), eid(), eid()
    ok = ready.jpost("/api/activity-events", {"events": [
        {"event_id": watch, "event_type": "watch", "stop": "videos", "content_id": vid, "duration_seconds": 40, "measured": True,
         "completion_pct": 80, "content_seconds": 50, "pauses": 1, "resumes": 1, "replays": 0, "completed": True},
        {"event_id": listen, "event_type": "listen", "stop": "music", "content_id": sid, "duration_seconds": 12},
        {"event_id": look, "event_type": "look", "stop": "pictures", "content_id": pid, "duration_seconds": 5},
        {"event_id": eid(), "event_type": "browse", "stop": "pictures", "category": "animals"}]})
    assert ok.status_code == 200
    # a late, smaller heartbeat for the same session must not shrink or un-complete it
    assert ready.jpost("/api/activity-events", {"events": [
        {"event_id": watch, "event_type": "watch", "stop": "videos", "content_id": vid, "duration_seconds": 10, "completion_pct": 20,
         "completed": False, "pauses": 0}]}).status_code == 200
    with app.app_context():
        rows = {r.event_type: r for r in Session.query(ActivityEvent).all()}
        w = rows["watch"]
        assert (w.duration_seconds, w.completion_pct, w.completed, w.pause_count, w.measured) == (40, 80.0, True, 1, True)
        assert w.content_type == "video" and w.category == "music"
        assert rows["listen"].content_type == "song" and rows["look"].content_type == "picture"
        assert rows["browse"].category == "animals" and rows["browse"].content_id is None
        assert Session.query(ActivityEvent).filter_by(event_type="watch").count() == 1


def test_session_types_must_match_content_and_values_are_validated(app, ready):
    login_as_child(app, ready)
    with app.app_context():
        video, song = make_item("video"), make_item("song")
        Session.commit()
        vid, sid = video.id, song.id
    bad = [
        {"event_type": "listen", "stop": "music", "content_id": vid},                      # a listen must be a song
        {"event_type": "watch", "stop": "videos", "content_id": sid},                      # a watch must be a video
        {"event_type": "look", "stop": "pictures", "content_id": vid},
        {"event_type": "watch", "stop": "videos"},                                        # a session needs content
        {"event_type": "browse", "stop": "pictures"},                                     # browse needs a category
        {"event_type": "browse", "stop": "pictures", "category": "not-a-category"},
        {"event_type": "watch", "stop": "videos", "content_id": vid, "completion_pct": 400},
        {"event_type": "watch", "stop": "videos", "content_id": vid, "completion_pct": True},
        {"event_type": "watch", "stop": "videos", "content_id": vid, "replays": -1},
    ]
    for event in bad:
        assert ready.jpost("/api/activity-events", {"events": [dict(event, event_id=eid())]}).status_code == 400, event
    with app.app_context():
        assert Session.query(ActivityEvent).count() == 0


# ------------------------------------------------------------------ analytics
def row(start, seconds, rid, last=None):
    return SimpleNamespace(id=rid, created_at=start, duration_seconds=seconds, last_active_at=last or start + timedelta(seconds=seconds))


def test_overlapping_sessions_are_counted_once():
    t = utcnow().replace(microsecond=0)
    a, b, c = row(t, 60, 1), row(t + timedelta(seconds=30), 60, 2), row(t + timedelta(minutes=10), 30, 3)
    eff = analytics.effective_seconds([a, b, c])
    assert round(eff[1]) == 60 and round(eff[2]) == 30 and round(eff[3]) == 30      # b overlaps a for 30 of its 60 seconds
    assert round(sum(eff.values())) == 120                                           # not 150: the overlap is not double counted
    assert analytics.effective_seconds([row(t, 0, 9)])[9] == 0


def test_percentage_formulas_and_trend_classification():
    assert analytics.pct_change(150, 100) == 50.0 and analytics.pct_change(50, 100) == -50.0
    assert analytics.pct_change(10, 0) is None and analytics.pct_change(10, None) is None      # no invented trend
    assert analytics.classify(300, 200) == "increasing" and analytics.classify(60, 300) == "decreasing"
    assert analytics.classify(310, 300) == "stable" and analytics.classify(300, 10) == "new"
    assert analytics.classify(5, 5) == "insufficient"


def test_summary_calculations_from_real_records(app, ready):
    cid = child_id_of(app)
    now = utcnow().replace(hour=12, minute=0, second=0, microsecond=0)
    with app.app_context():
        sport, music = make_item("video", "sports"), make_item("song", "music")
        add_event(cid, sport, "watch", 600, now - timedelta(minutes=30), completed=True, completion_pct=95, replay_count=1)   # 10 min
        add_event(cid, music, "listen", 300, now - timedelta(days=1), measured=True)                                          # 5 min
        add_event(cid, sport, "watch", 300, now - timedelta(days=8))                                                          # previous week: 5 min
        add_event(cid, None, "view", 900, now - timedelta(hours=3))                                                           # page time: NOT engagement
        Session.commit()
        today = now.date()
        data = analytics.summary(cid, today - timedelta(days=6), today, tz=0)
    s = data["stats"]
    assert s["total_minutes"] == 15.0                                  # page-view time is excluded
    assert s["avg_daily_minutes"] == round(15 / 7, 2) and s["active_days"] == 2
    assert s["most_active_day"]["minutes"] == 10.0
    assert s["top_video_category"]["category"] == "sports" and s["top_music_category"]["category"] == "music"
    assert s["completions"] == 1 and s["replays"] == 1
    assert s["most_replayed"]["content"]["title"] == "sports video"
    shares = {a["category"]: a["percent"] for a in data["allocation"]}
    assert shares == {"sports": 66.7, "music": 33.3}                   # category minutes / total categorised minutes x 100
    assert round(sum(shares.values())) == 100
    assert s["week_change_pct"] == 200.0                              # (15 - 5) / 5 x 100 with this week 15 min, previous week 5 min
    assert {t["type"]: t["minutes"] for t in data["types"]}["video"] == 10.0
    assert data["day_graph"][11]["minutes"] == 10.0 and len(data["day_graph"]) == 24
    assert data["has_data"] is True


def test_zero_data_is_handled_without_inventing_trends(app, ready):
    cid = child_id_of(app)
    with app.app_context():
        today = utcnow().date()
        data = analytics.summary(cid, today - timedelta(days=6), today, tz=0)
    s = data["stats"]
    assert s["total_minutes"] == 0 and s["avg_daily_minutes"] == 0 and s["most_active_day"] is None
    assert s["week_change_pct"] is None and "Not enough" in s["week_change_note"]
    assert data["development"]["enough"] is False and data["trends"]["available"] is False
    assert data["distribution"] == [] and data["most_engaging"] == [] and data["has_data"] is False


def test_history_filters_search_and_pagination(app, ready):
    cid = child_id_of(app)
    now = utcnow()
    with app.app_context():
        cat = make_item("video", "animals", "Funny Cat Video")
        song = make_item("song", "music", "Happy Song")
        for n in range(25):
            add_event(cid, cat, "watch", 30, now - timedelta(minutes=n))
        add_event(cid, song, "listen", 60, now - timedelta(days=2))
        add_event(cid, None, "search", 0, now)
        Session.commit()
        everything = analytics.history(cid, per_page=10)
        assert everything["total"] == 26 and everything["pages"] == 3 and len(everything["items"]) == 10   # searches are never listed
        assert analytics.history(cid, per_page=10, page=3)["has_more"] is False
        assert analytics.history(cid, content_type="song")["total"] == 1
        assert analytics.history(cid, q="funny")["total"] == 25 and analytics.history(cid, q="happy")["items"][0]["content"]["title"] == "Happy Song"
        assert analytics.history(cid, category="music")["total"] == 1
        assert analytics.history(cid, start=now.date(), end=now.date())["total"] <= 25
        assert analytics.history(cid, q="100%_")["total"] == 0                                              # LIKE wildcards are escaped
        detail = analytics.detail(cid, analytics.history(cid, content_type="song")["items"][0]["id"])
        assert detail["content_history"]["sessions"] == 1 and detail["viewer"]["title"] == "Happy Song"


# ------------------------------------------------------------------ interest discovery
def test_interest_needs_repeated_activity_and_explains_its_evidence(app, ready):
    cid = child_id_of(app)
    now = utcnow().replace(microsecond=0)
    with app.app_context():
        vid = make_item("video", "sports")
        add_event(cid, vid, "watch", 900, now - timedelta(hours=1))               # one long video: still not an interest
        Session.commit()
        found = discovery.discover(cid, now=now)
        assert found["possible"] == [] and "Not enough repeated activity" in found["message"]
        add_event(cid, vid, "watch", 240, now - timedelta(days=1), completed=True)
        add_event(cid, vid, "watch", 240, now - timedelta(days=2), replay_count=1)
        Session.commit()
        found = discovery.discover(cid, now=now)
        top = found["possible"][0]
        assert top["category"] == "sports" and top["qualified"] and top["active_days"] == 3 and top["sessions"] == 3
        assert "3 sessions" in top["evidence"] and "replay" in top["evidence"]
        assert "possible interests" in found["disclaimer"] and "not an assessment" in found["disclaimer"]
        assert discovery.discover(cid, now=now + timedelta(days=200))["possible"] == []   # interests fade as time passes


def test_no_activity_gives_no_invented_interests(app, ready):
    cid = child_id_of(app)
    with app.app_context():
        found = discovery.discover(cid)
    assert found["interests"] == [] and found["possible"] == [] and "No activity" in found["message"]


# ------------------------------------------------------------------ world: one shared base, personal emphasis
def test_world_personalises_per_child_on_the_same_base(app, ready):
    assert ready.post("/caretaker/children/add", {"display_name": "Alex", "avatar": "star", "age": "8", "consent": "yes",
                                                   "child_password": "Alex!Secret8901"}).status_code == 302
    now = utcnow().replace(microsecond=0)
    with app.app_context():
        user = Session.query(User).filter_by(username="mum").one()
        first, second = Session.query(ChildProfile).order_by(ChildProfile.id).all()
        before = world_service.payload(user, first)
        assert before["discovery"]["top"] == [] and all(s["interest"] is None for s in before["stops"])
        music = make_item("song", "music")
        for days in (0, 1, 2, 3):
            add_event(first.id, music, "listen", 300, now - timedelta(days=days), completed=True)
        Session.commit()
        mine, other = world_service.payload(user, first), world_service.payload(user, second)
        assert mine["discovery"]["top"][0]["category"] == "music"
        assert next(s for s in mine["stops"] if s["key"] == "music")["interest"]["level"] >= 1
        assert mine["theme"]["key"] == "music"                                                # real activity changed this child's world...
        assert other["discovery"]["top"] == [] and other["theme"]["key"] != "music"          # ...and not the sibling's
        assert all(s["interest"] is None for s in other["stops"])
        assert mine["island_base"] == other["island_base"]                                    # the administrator's island is shared
        assert {s["key"] for s in other["stops"]} <= {s["key"] for s in mine["stops"]} | {s["key"] for s in other["stops"]}


# ------------------------------------------------------------------ dashboard page + API security
def test_dashboard_page_and_api_for_the_owner(app, ready):
    cid = child_id_of(app)
    with app.app_context():
        item = make_item("video", "animals", "Zoo Trip")
        add_event(cid, item, "watch", 120, utcnow() - timedelta(minutes=5), measured=True)
        Session.commit()
        event_id = Session.query(ActivityEvent).first().id
    page = ready.get("/caretaker/activity")
    assert page.status_code == 200 and b"ad-root" in page.data and b"Activity" in page.data
    data = ready.get("/api/caretaker/activity/summary?range=7&tz=0").get_json()
    assert data["stats"]["total_minutes"] == 2.0 and data["child"]["name"] == "Sunny"
    hist = ready.get("/api/caretaker/activity/history?q=zoo").get_json()
    assert hist["total"] == 1 and hist["items"][0]["content"]["thumbnail_url"]
    assert ready.get(f"/api/caretaker/activity/{event_id}").get_json()["viewer"]["title"] == "Zoo Trip"
    assert ready.get("/api/caretaker/activity/timeline?day=" + utcnow().date().isoformat()).get_json()["events"]
    assert ready.get("/api/caretaker/activity/series?group=day").status_code == 200
    assert ready.get("/api/caretaker/activity/series?group=year").status_code == 400
    assert "disclaimer" in ready.get("/api/caretaker/interests").get_json()
    assert ready.get("/caretaker").status_code == 200                                         # existing dashboard still works


def test_other_families_and_children_cannot_read_the_activity(app, ready):
    cid = child_id_of(app)
    with app.app_context():
        item = make_item("video", "animals")
        add_event(cid, item, "watch", 120, utcnow() - timedelta(minutes=5))
        Session.commit()
        event_id = Session.query(ActivityEvent).first().id
        uid = Session.query(ChildProfile).first().public_uid
    anonymous = Client(app)
    assert anonymous.get("/api/caretaker/activity/summary").status_code == 401
    assert anonymous.get("/caretaker/activity").status_code == 302
    # a second, unrelated caregiver
    other = Client(app)
    other.register("dad")
    assert other.get(f"/api/caretaker/activity/{event_id}").status_code in (302, 403, 404)
    assert other.get(f"/api/caretaker/activity/summary?child={uid}").status_code in (302, 403, 404)
    assert other.get(f"/caretaker/activity?child={uid}").status_code in (302, 403, 404)
    # the child's own session is not allowed on caretaker analytics
    login_as_child(app, ready)
    assert ready.get("/api/caretaker/activity/summary").status_code == 403
    assert ready.get(f"/api/caretaker/activity/{event_id}").status_code == 403


def test_access_follows_the_explicit_grant_not_the_account(app, ready):
    """Authorisation is the grant: a caregiver with an active grant resolves the child, one without (or revoked) does not."""
    from database.models import CaregiverChildAccess
    from services import child_scope
    cid = child_id_of(app)
    Client(app).register("dad")
    with app.app_context():
        dad = Session.query(User).filter_by(username="dad").one()
        mum = Session.query(User).filter_by(username="mum").one()
        uid = Session.get(ChildProfile, cid).public_uid
        assert child_scope.resolve_child_uid(mum.id, uid) is not None
        assert child_scope.resolve_child_uid(dad.id, uid) is None and not child_scope.can_access(dad.id, cid)
        grant = CaregiverChildAccess(caregiver_id=dad.id, child_id=cid, status="active", access_role="guardian")
        Session.add(grant)
        Session.commit()
        assert child_scope.resolve_child_uid(dad.id, uid) is not None          # a second authorised caretaker sees the same child
        grant.status = "revoked"
        Session.commit()
        assert child_scope.resolve_child_uid(dad.id, uid) is None


# ------------------------------------------------------------------ retention
def test_retention_purge_removes_only_old_activity(app, ready):
    cid = child_id_of(app)
    with app.app_context():
        item = make_item("video")
        add_event(cid, item, "watch", 10, utcnow() - timedelta(days=400))
        add_event(cid, item, "watch", 10, utcnow() - timedelta(days=5))
        Session.commit()
        assert activity_service.purge_expired(365) == 1
        assert Session.query(ActivityEvent).count() == 1
        assert activity_service.purge_expired(5) == 0                  # never purges more aggressively than 30 days
        assert activity_service.purge_expired(0) == 0
