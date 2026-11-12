"""The child's 2D My World: the stops of the design, always present, laid out without overlap, and a room for each."""
from services import world2d_service as w2d


def test_stops_match_the_design():
    assert w2d.ORDER == ("soccer", "music", "home", "basketball", "food", "animals", "nature", "colors", "pictures", "videos", "shots", "journey")
    assert w2d.MAIN_STOPS == w2d.ORDER[:-1]
    for key, d in w2d.STOPS.items():
        assert d["label"] and d["icon"] and d["color"].startswith("#") and 0 < d["land"][0] < 100 and 0 < d["land"][1] < 100


def test_every_stop_has_a_room_topic():
    assert w2d.STOPS["soccer"]["cat"] == "sports" and w2d.STOPS["soccer"]["q"] == "football"
    assert w2d.STOPS["basketball"]["q"] == "basketball"
    assert w2d.STOPS["music"]["kinds"][0] == "music"


def test_phone_layout_zigzags_and_never_overlaps():
    height, placed = w2d.tall_layout(list(w2d.ORDER))
    assert [k for k, _, _ in placed] == list(w2d.ORDER)
    ys = [y for _, _, y in placed]
    assert ys == sorted(ys) and len(set(ys)) == len(ys) and all(0 < y < height for y in ys)
    assert {x for _, x, _ in placed} == {26, 74}


def test_phone_layout_with_hidden_stops_has_no_gaps():
    assert w2d.tall_layout([])[1] == [] and len(w2d.tall_layout(["music"])[1]) == 1
    h, placed = w2d.tall_layout(["music", "journey"])
    assert placed[0][2] < placed[1][2] < h


def test_wide_map_has_an_island_per_building_and_connected_paths():
    sc = w2d.wide_scene(list(w2d.ORDER))
    assert len(sc["islands"]) == len(w2d.MAIN_STOPS)
    assert sc["paths"] and len(sc["bridges"]) == len(w2d.BRIDGES)
    assert w2d.wide_scene([])["islands"] == []


def test_path_is_a_smooth_curve():
    d = w2d._tall_path([(50, 6), (26, 24), (74, 40)])
    assert d.startswith("M50.0,6.0") and d.count("C") == 2 and w2d._tall_path([]) == ""


def test_admin_order_puts_listed_stops_first_and_journey_last(monkeypatch):
    monkeypatch.setattr(w2d.settings_service, "get", lambda k: "videos,pictures,bogus" if k == "world2d_order" else "")
    keys = w2d.ordered_keys()
    assert keys[:2] == ("videos", "pictures") and keys[-1] == "journey"
    assert set(keys) == set(w2d.STOPS) and len(keys) == len(w2d.STOPS)


def test_admin_hidden_never_includes_the_journey_sign(monkeypatch):
    monkeypatch.setattr(w2d.settings_service, "get", lambda k: "food,journey,bogus" if k == "world2d_hidden" else "")
    assert w2d.admin_hidden() == {"food"}
    assert w2d._shown("food", {"hidden_stops": []}, True) is False
    assert w2d._shown("music", {"hidden_stops": []}, True) is True
