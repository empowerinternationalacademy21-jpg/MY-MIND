from flask import Blueprint, render_template
from services.categories import CATEGORIES
from routes.helpers import subscribed_required

bp = Blueprint("shots", __name__)


@bp.route("/shots")
@subscribed_required
def page():
    return render_template("shots.html", categories=CATEGORIES, active="shots")
