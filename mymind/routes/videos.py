from flask import Blueprint, render_template
from services.categories import CATEGORIES
from routes.helpers import subscribed_required

bp = Blueprint("videos", __name__)


@bp.route("/videos")
@subscribed_required
def page():
    return render_template("videos.html", categories=CATEGORIES, active="videos")
