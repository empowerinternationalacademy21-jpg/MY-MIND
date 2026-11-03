"""Self-service password recovery using the caregiver's own questionnaire answers.

How it works: the caregiver enters a username, then answers 5 questions about what they originally told MyMind
(everyday activities, topics, communication, routine, the child's nickname). Each answer is scored 0–1
(multi-choice = overlap between the chosen and stored sets; text = fuzzy match). If the average is >= 80 %
the caregiver may set a new password. Otherwise they can refill the form or contact the administrator.

Hardening: unknown usernames get identical questions and always fail (no account enumeration); attempts are
rate limited per username and per IP; 3 failures lock self-service recovery for 1 hour; answers/scores are never
shown or logged; the reset step needs a fresh, 10-minute, single-use verification token held in the session.
"""
import difflib
import json
import re
import time
from database.db import Session
from database.models import User, ChildProfile, CaregiverQuestionnaire
from services import cache
from services import categories as C

PASS_THRESHOLD = 0.80
MAX_FAILS, LOCK_SECONDS = 3, 3600
MIN_RICH_FIELDS = 3          # the caregiver must have given real answers to at least 3 of the 4 list questions
VERIFY_TTL = 600

QUESTIONS = [
    {"key": "activities", "type": "multi", "prompt": "Which everyday activities did you tick for your child?", "options": C.ACTIVITIES},
    {"key": "interests", "type": "multi", "prompt": "Which topics did you tick as your child's interests?", "options": C.INTERESTS},
    {"key": "communication", "type": "multi", "prompt": "How did you say your child shows preferences?", "options": C.COMMUNICATION},
    {"key": "routine", "type": "multi", "prompt": "Which parts of the daily routine did you tick?", "options": C.ROUTINE},
    {"key": "nickname", "type": "text", "prompt": "What nickname did you give your child in MyMind?"},
]


def _norm(t):
    return re.sub(r"\s+", " ", (t or "").strip().lower())


def _score_multi(stored, given, allowed):
    a, b = set(stored) & allowed, set(given) & allowed
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _score_text(stored, given):
    s, g = _norm(stored), _norm(given)
    if not s or not g:
        return 0.0
    return 1.0 if difflib.SequenceMatcher(None, s, g).ratio() >= 0.85 else 0.0


def _stored(user_id):
    child = Session.query(ChildProfile).filter_by(caregiver_user_id=user_id).first()
    if not child:
        return None
    q = Session.query(CaregiverQuestionnaire).filter_by(child_profile_id=child.id).first()
    if not q:
        return None
    data = json.loads(q.responses_json or "{}")
    data["nickname"] = child.display_name
    return data


def eligible_user(username):
    u = Session.query(User).filter_by(username=(username or "").strip().lower()).first()
    if not u or u.role != "caregiver" or u.account_status != "active":
        return None
    return u


def score(user_id, form):
    """Return average score 0..1 (0 if the account has too little stored data to verify safely)."""
    stored = _stored(user_id)
    if not stored:
        return 0.0
    if sum(1 for k in ("activities", "interests", "communication", "routine") if stored.get(k)) < MIN_RICH_FIELDS:
        return 0.0
    parts = []
    for q in QUESTIONS:
        if q["type"] == "multi":
            allowed = {k for k, _ in q["options"]}
            parts.append(_score_multi(stored.get(q["key"], []), form.getlist(q["key"]), allowed))
        else:
            parts.append(_score_text(stored.get("nickname"), form.get("nickname")))
    return sum(parts) / len(parts)


# ---- attempt limiting ----
def is_locked(username, ip):
    return cache.rate_peek(f"recfail:{username}", MAX_FAILS, LOCK_SECONDS) or cache.rate_peek(f"recip:{ip}", 12, 3600)


def register_start(ip):
    return cache.rate_limited(f"recip:{ip}", 12, 3600)      # True => too many starts from this IP


def register_failure(username):
    cache.rate_limited(f"recfail:{username}", MAX_FAILS, LOCK_SECONDS)


def clear_failures(username):
    cache.rate_reset(f"recfail:{username}")


def token_valid(ts):
    return bool(ts) and time.time() - ts <= VERIFY_TTL
