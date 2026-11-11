"""The child's 2D My World: ten stops in a fixed order, always present, and a room page for each."""
from services import world2d_service as w2d


def test_ten_stops_in_order_with_rooms():
    assert len(w2d.ORDER) == 10 and "journey" in w2d.ORDER
    assert set(w2d.ORDER) == set(w2d.ROOMS)


def test_layout_zigzags_and_never_overlaps():
    placed = w2d.layout(list(w2d.ORDER))
    assert [k for k, _, _ in placed] == list(w2d.ORDER)
    ys = [y for _, _, y in placed]
    assert ys == sorted(ys) and len(set(ys)) == len(ys)
    assert {x for _, x, _ in placed} == {26, 74}
    assert all(0 < y < w2d.SCENE_H for y in ys)


def test_layout_with_hidden_stops_has_no_gaps():
    placed = w2d.layout(["music", "journey"])
    assert placed[0][2] < placed[1][2] and len(placed) == 2
    assert w2d.layout([]) == [] and len(w2d.layout(["music"])) == 1


def test_path_is_a_smooth_curve():
    d = w2d._path([(50, 6), (26, 24), (74, 40)])
    assert d.startswith("M50.0,6.0") and d.count("C") == 2 and w2d._path([]) == ""
