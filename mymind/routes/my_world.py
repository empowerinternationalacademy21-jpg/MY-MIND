"""The 2D My World rooms: one themed page per stop (the map itself is profile.world, shown to children)."""
from flask import Blueprint, abort, g, render_template
from routes.helpers import subscribed_required
from services import world2d_service as w2d

bp = Blueprint("my_world", __name__)


@bp.route("/my-world/<key>")
@subscribed_required
def room(key):
    data = w2d.room(g.user, g.child, key)         # always the signed-in child's own data
    if data is None:
        abort(404)
    return render_template("world_room.html", room=data, key=key, active="world")
