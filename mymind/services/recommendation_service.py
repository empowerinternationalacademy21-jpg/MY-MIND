"""Explainable, adjustable recommendation logic.

Scoring (all numbers live in the constants below so they are easy to change):
  * Child reactions add weighted points to a category (see WEIGHTS).
  * Caregiver answers are stored separately as a 'seed'. The seed fades as real child evidence
    accumulates, so caregiver assumptions never permanently override the child's own choices.
  * Child-derived score decays with time (HALF_LIFE_DAYS) so new interests can emerge.
  * Disliking ONE item hides that item and nudges its category only slightly.
  * A skip is recorded but never scored as a dislike. Impressions are never scored.
"""
import json
import random
from datetime import timedelta
from database.db import Session
from database.models import (InterestProfile, Interaction, Favorite, ContentItem, RecommendationLog, utcnow)
from services.categories import (CATEGORIES, INTEREST_TO_CATEGORY, ACTIVITY_TO_CATEGORY, CONTENT_PREF_TO_CATEGORY, label_for)

WEIGHTS = {"selected": 0.5, "watched": 1.5, "like": 3.0, "favorite": 4.0, "explore": 1.5,
           "skip": 0.0, "dislike": -0.75, "unfavorite": -1.0, "caregiver_adjust": 0.0}
EVIDENCE_TYPES = {"watched", "like", "favorite", "explore", "dislike"}
SEED_INTEREST, SEED_ACTIVITY, SEED_CAP = 4.0, 1.5, 6.0
SCORE_MIN, SCORE_MAX = -10.0, 30.0
HALF_LIFE_DAYS = 45
EXPLORE_SLOTS = 1


def _row(profile_id, category):
    row = Session.query(InterestProfile).filter_by(child_profile_id=profile_id, category=category).first()
    if not row:
        row = InterestProfile(child_profile_id=profile_id, category=category, interest_score=0.0,
                              evidence_count=0, caregiver_seed=0.0, first_observed_at=None)
        Session.add(row)
        Session.flush()
    return row


def seed_from_questionnaire(profile_id, responses):
    """Caregiver answers -> initial (moderate) weights. Re-running replaces seeds only."""
    seeds = {}
    for v in responses.get("interests", []):
        c = INTEREST_TO_CATEGORY.get(v)
        if c:
            seeds[c] = seeds.get(c, 0) + SEED_INTEREST
    for v in responses.get("activities", []):
        c = ACTIVITY_TO_CATEGORY.get(v)
        if c:
            seeds[c] = seeds.get(c, 0) + SEED_ACTIVITY
    for v in responses.get("content_prefs", []):
        c = CONTENT_PREF_TO_CATEGORY.get(v)
        if c:
            seeds[c] = seeds.get(c, 0) + SEED_ACTIVITY
    for row in Session.query(InterestProfile).filter_by(child_profile_id=profile_id).all():
        row.caregiver_seed = 0.0
    for cat, val in seeds.items():
        _row(profile_id, cat).caregiver_seed = min(val, SEED_CAP)
    Session.commit()
    return seeds


def seed_factor(evidence):
    return max(0.25, 1.0 - 0.1 * evidence)


def effective_score(row, now=None):
    now = now or utcnow()
    recency = 1.0
    if row.last_observed_at:
        days = max(0.0, (now - row.last_observed_at).total_seconds() / 86400)
        recency = 0.5 ** (days / HALF_LIFE_DAYS)
    return row.caregiver_seed * seed_factor(row.evidence_count) + row.interest_score * recency


def confidence(row):
    return round(min(1.0, row.evidence_count / 8), 2)


def get_interests(profile_id):
    now = utcnow()
    out = []
    for r in Session.query(InterestProfile).filter_by(child_profile_id=profile_id).all():
        out.append({"category": r.category, "label": label_for(r.category), "icon": CATEGORIES.get(r.category, {}).get("icon", "star"),
                    "score": round(effective_score(r, now), 2), "evidence": r.evidence_count, "confidence": confidence(r),
                    "first_observed_at": r.first_observed_at, "last_observed_at": r.last_observed_at,
                    "seed": r.caregiver_seed})
    return sorted(out, key=lambda d: -d["score"])


def record_interaction(profile_id, content, itype, category=None):
    """Store the event and (for explicit reactions) update that category's score."""
    if itype not in WEIGHTS:
        raise ValueError("unknown interaction type")
    cat = category or (content.category if content else None)
    Session.add(Interaction(child_profile_id=profile_id, content_item_id=content.id if content else None,
                            interaction_type=itype, category=cat))
    if cat in CATEGORIES and WEIGHTS[itype] != 0:
        row = _row(profile_id, cat)
        now = utcnow()
        # fold decay into the stored score before adding new evidence
        if row.last_observed_at:
            days = max(0.0, (now - row.last_observed_at).total_seconds() / 86400)
            row.interest_score *= 0.5 ** (days / HALF_LIFE_DAYS)
        row.interest_score = max(SCORE_MIN, min(SCORE_MAX, row.interest_score + WEIGHTS[itype]))
        if itype in EVIDENCE_TYPES:
            row.evidence_count += 1
        row.first_observed_at = row.first_observed_at or now
        row.last_observed_at = now
    Session.commit()


def caregiver_adjust(profile_id, category, mode):
    """mode: boost | avoid | remove. Logged as an interaction so My Journey stays truthful."""
    if category not in CATEGORIES:
        raise ValueError("unknown category")
    row = _row(profile_id, category)
    if mode == "boost":
        row.caregiver_seed = min(SEED_CAP, row.caregiver_seed + SEED_INTEREST)
    elif mode == "avoid":
        row.interest_score, row.caregiver_seed, row.evidence_count = -4.0, 0.0, max(row.evidence_count, 1)
        row.last_observed_at = utcnow()
    elif mode == "remove":
        row.interest_score, row.caregiver_seed, row.evidence_count = 0.0, 0.0, 0
        row.last_observed_at = None
    else:
        raise ValueError("bad mode")
    Session.add(Interaction(child_profile_id=profile_id, content_item_id=None, interaction_type="caregiver_adjust", category=category))
    Session.commit()


def reset_profile(profile_id):
    Session.query(InterestProfile).filter_by(child_profile_id=profile_id).delete()
    Session.commit()


def disliked_ids(profile_id):
    return {i for (i,) in Session.query(Interaction.content_item_id)
            .filter(Interaction.child_profile_id == profile_id, Interaction.interaction_type == "dislike",
                    Interaction.content_item_id.isnot(None)).all()}


def pick_feed_categories(profile_id, n=4, rng=None):
    """Weighted pick of liked categories + EXPLORE_SLOTS new ones (never one-interaction lock-in)."""
    rng = rng or random.Random()
    ranked = get_interests(profile_id)
    positives = [r for r in ranked if r["score"] > 0.5]
    chosen = []
    pool = positives[:]
    want = max(1, n - EXPLORE_SLOTS)
    while pool and len(chosen) < want:
        weights = [max(r["score"], 0.1) for r in pool]
        pick = rng.choices(pool, weights=weights, k=1)[0]
        pool.remove(pick)
        chosen.append((pick["category"], reason_for(pick)))
    known = {c for c, _ in chosen}
    disliked_cats = {r["category"] for r in ranked if r["score"] < -1}
    candidates = [c for c in CATEGORIES if c not in known and c not in disliked_cats]
    rng.shuffle(candidates)
    for c in candidates:
        if len(chosen) >= n:
            break
        label = "something new to explore" if positives else "a gentle starting point while we learn what you enjoy"
        chosen.append((c, f"Suggested as {label}."))
    return chosen


def reason_for(r):
    lab = r["label"].lower()
    if r["evidence"] >= 3:
        return f"We suggested {lab} because they were chosen or liked several times in the app."
    if r["evidence"] >= 1:
        return f"We suggested {lab} because of a recent choice in the app."
    return f"We suggested {lab} because the caregiver mentioned this interest. It will change as choices are made."


def related_terms(content, limit=2):
    """Anonymous topic keywords only (never names or notes) used for related searches."""
    tags = []
    try:
        tags = [t for t in json.loads(content.tags_json or "[]") if isinstance(t, str)]
    except ValueError:
        pass
    words = tags[:1] or CATEGORIES.get(content.category, {}).get("keywords", [content.category])[:1]
    cat_kws = CATEGORIES.get(content.category, {}).get("keywords", [])
    return (words + [k for k in cat_kws if k not in words])[:limit]


def log_recommendations(profile_id, items, reason):
    for it in items:
        Session.add(RecommendationLog(child_profile_id=profile_id, content_item_id=it.id, reason=reason[:200]))
    Session.commit()


def recently_shown_ids(profile_id, hours=48, limit=200):
    since = utcnow() - timedelta(hours=hours)
    return {i for (i,) in Session.query(RecommendationLog.content_item_id)
            .filter(RecommendationLog.child_profile_id == profile_id, RecommendationLog.shown_at >= since)
            .order_by(RecommendationLog.id.desc()).limit(limit).all()}
