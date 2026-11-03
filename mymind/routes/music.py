from flask import Blueprint, render_template
from services.categories import CATEGORIES
from routes.helpers import subscribed_required

bp = Blueprint("music", __name__)


@bp.route("/music")
@subscribed_required
def page():
    return render_template("music.html", categories=CATEGORIES, active="music")
