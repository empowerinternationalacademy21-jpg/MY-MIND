from flask import Blueprint, render_template, g
from services.categories import PICTURE_CATEGORIES
from services import age_service
from routes.helpers import subscribed_required

bp = Blueprint("pictures", __name__)


@bp.route("/pictures")
@subscribed_required
def page():
    return render_template("pictures.html", categories=age_service.categories_for(g.child.age_years, PICTURE_CATEGORIES), active="pictures")