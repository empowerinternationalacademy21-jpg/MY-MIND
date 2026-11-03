from flask import Blueprint, render_template
from services.categories import CATEGORIES, PICTURE_CATEGORIES
from routes.helpers import subscribed_required

bp = Blueprint("pictures", __name__)


@bp.route("/pictures")
@subscribed_required
def page():
    return render_template("pictures.html", categories={c: CATEGORIES[c] for c in PICTURE_CATEGORIES}, active="pictures")
