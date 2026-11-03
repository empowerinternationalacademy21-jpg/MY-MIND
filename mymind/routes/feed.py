from flask import Blueprint, render_template, g, abort
from database.db import Session
from database.models import ContentItem
from services.categories import CATEGORIES
from services import recommendation_service as rec
from routes.helpers import subscribed_required

bp = Blueprint("feed", __name__)


@bp.route("/home")
@subscribed_required
def home():
    interests = [item for item in rec.get_interests(g.child.id) if item["score"] > 0][:4]
    return render_template("feed.html", categories=CATEGORIES, interests=interests, active="home")


@bp.route("/explore/<int:content_id>")
@subscribed_required
def explore(content_id):
    item = Session.get(ContentItem, content_id) or abort(404)
    return render_template("explore.html", item=item, active="home")
