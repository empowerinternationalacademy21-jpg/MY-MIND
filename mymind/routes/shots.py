from flask import Blueprint, render_template, g
from services import age_service
from routes.helpers import subscribed_required

bp = Blueprint("shots", __name__)


@bp.route("/shots")
@subscribed_required
def page():
    return render_template("shots.html", categories=age_service.categories_for(g.child.age_years), active="shots")