from flask import Blueprint, render_template, g, abort
from database.db import Session
from database.models import ContentItem
from services import recommendation_service as rec, age_service
from routes.helpers import subscribed_required

bp = Blueprint("feed", __name__)


@bp.route("/home")
@subscribed_required
def home():
    age = g.child.age_years
    allowed = set(age_service.allowed_categories(age))
    interests = [item for item in rec.get_interests(g.child.id) if item["score"] > 0 and item["category"] in allowed][:4]
    return render_template("feed.html", categories=age_service.categories_for(age), interests=interests, active="home",
                           age=age, age_band=age_service.band_for(age))


@bp.route("/topic/<key>")
@subscribed_required
def topic(key):
    """A friendly page for one topic (Sports, Food, Animals ...): a grid of big pictures for the child to tap.
    Only topics allowed for the child's age exist; anything else is a plain 404."""
    cats = age_service.categories_for(g.child.age_years)
    if key not in cats:
        abort(404)
    return render_template("topic.html", key=key, cat=cats[key], active="home")


@bp.route("/favourites")
@subscribed_required
def favourites():
    """Everything the child has saved with the heart button (data comes from /api/favorites)."""
    return render_template("favourites.html", active="favourites")


@bp.route("/explore/<int:content_id>")
@subscribed_required
def explore(content_id):
    item = Session.get(ContentItem, content_id) or abort(404)
    return render_template("explore.html", item=item, active="home")
