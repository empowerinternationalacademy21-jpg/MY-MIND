from flask import Blueprint, render_template, g
from services import age_service
from routes.helpers import subscribed_required

bp = Blueprint("music", __name__)


@bp.route("/music")
@subscribed_required
def page():
    return render_template("music.html", categories=age_service.categories_for(g.child.age_years), active="music")