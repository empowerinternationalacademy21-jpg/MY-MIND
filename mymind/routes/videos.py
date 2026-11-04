from flask import Blueprint, render_template, g
from services import age_service
from routes.helpers import subscribed_required

bp = Blueprint("videos", __name__)


@bp.route("/videos")
@subscribed_required
def page():
    return render_template("videos.html", categories=age_service.categories_for(g.child.age_years), active="videos")