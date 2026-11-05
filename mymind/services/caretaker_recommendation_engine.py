"""Rule-based, explainable recommendations; the inputs can later be supplied by another engine."""
from datetime import timedelta

from database.db import Session
from database.models import CaregiverRecommendationState, utcnow
from services import activity_service, settings_service
from services import recommendation_rules as rules
from services.world_service import STOP_DEFS


def _duration(minutes):
    minutes = int(round(minutes))
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours}h {remainder}m"
    if hours:
        return f"{hours}h"
    return f"{remainder}m"


def _state(child_id, key):
    return Session.query(CaregiverRecommendationState).filter_by(
        child_profile_id=child_id, recommendation_key=key).first()


def _card(key, title, reason, action, priority, icon):
    return {"key": key, "title": title, "reason": reason, "action": action,
            "priority": priority, "icon": icon}


def _dominant(child_id, days):
    today = utcnow().date()
    start = today - timedelta(days=days - 1)
    totals = activity_service.minutes_per_stop(child_id, start, today)
    total = sum(totals.values())
    if total <= 0:
        return None
    other_values = [value for value in totals.values() if value > 0]
    average_other = (total - max(totals.values())) / max(1, len(other_values) - 1) if len(other_values) > 1 else 0
    candidate = max(totals, key=totals.get)
    minutes = totals[candidate]
    share = minutes / total
    ratio = minutes / average_other if average_other else 0
    if share < rules.DOMINANCE_SHARE and ratio <= rules.DOMINANCE_OTHER_STOPS_RATIO:
        return None
    label = STOP_DEFS.get(candidate, {}).get("label", candidate.title())
    action, icon = rules.STOP_ACTIONS.get(candidate, ("Explore an offline activity connected to this interest together.", "sparkles"))
    period = "this week" if days == 7 else "this month"
    priority = "high" if share >= .6 else "medium"
    return _card(f"dominant:{days}:{candidate}", f"Make room for {label}",
                 f"{_duration(minutes)} on {label} {period} ({round(share * 100)}% of {_duration(total)} total time).",
                 action, priority, icon)


def _raw_recommendations(child_id, daily_limit):
    cards = []
    today = utcnow().date()
    for days in (7, 30):
        card = _dominant(child_id, days)
        if card:
            cards.append(card)

    all_time = activity_service.minutes_per_stop(child_id)
    unseen = next((key for key in rules.VARIETY_STOPS if all_time.get(key, 0) <= 0), None)
    if unseen:
        label = STOP_DEFS.get(unseen, {}).get("label", unseen.title())
        cards.append(_card(f"variety:{unseen}", f"Explore {label} together",
                           f"{label} hasn't appeared in {child_name(child_id)}'s activity yet.",
                           "Open the world map and explore this stop together.", "low",
                           rules.STOP_ACTIONS.get(unseen, ("", "sparkles"))[1]))

    streak = activity_service.daily_streak(child_id, today)
    if streak >= rules.STREAK_ENCOURAGEMENT_DAYS:
        cards.append(_card("streak", "Celebrate the routine",
                           f"{child_name(child_id)} has explored MyMind for {streak} days in a row.",
                           "Notice the interests they've explored and enjoy a screen-free activity together.",
                           "low", "flame"))

    last_week = activity_service.minutes_per_stop(child_id, today - timedelta(days=6), today)
    video_minutes = last_week.get("videos", 0) + last_week.get("shorts", 0)
    if video_minutes >= rules.VIDEO_WEEKLY_THRESHOLD_MINUTES:
        interests = sorted(((value, key) for key, value in last_week.items() if key not in ("videos", "shorts")), reverse=True)
        topic = STOP_DEFS.get(interests[0][1], {}).get("label", "a favorite topic") if interests else "a favorite topic"
        cards.append(_card("screen:video-balance", "Balance videos with offline play",
                           f"Video and short-viewing time reached {_duration(video_minutes)} this week.",
                           f"Try an offline activity connected to {topic}, and agree a daily screen-time target together.",
                           "medium", "clapperboard"))

    today_minutes = sum(activity_service.minutes_per_stop(child_id, today, today).values())
    if daily_limit > 0 and today_minutes > daily_limit:
        cards.append(_card("screen:daily", "A gentle screen-time reminder",
                           f"Today's recorded activity is {_duration(today_minutes)}, above the {daily_limit}-minute reminder you set.",
                           "Consider a short break and a favorite offline activity together.", "high", "clock-3"))
    return cards


def child_name(child_id):
    from database.models import ChildProfile
    child = Session.get(ChildProfile, child_id)
    return child.display_name if child else "Your child"


def get_recommendations(child_id, user_id, daily_limit=None):
    if daily_limit is None:
        daily_limit = settings_service.caregiver_settings(user_id).get(
            "recommendation_limit_minutes", rules.DAILY_SCREEN_WARNING_MINUTES)
    try:
        daily_limit = max(0, min(600, int(daily_limit)))
    except (TypeError, ValueError):
        daily_limit = rules.DAILY_SCREEN_WARNING_MINUTES
    now = utcnow()
    cards = []
    for card in _raw_recommendations(child_id, daily_limit):
        state = _state(child_id, card["key"])
        if state and state.dismissed_at and now - state.dismissed_at < timedelta(days=rules.DISMISS_DAYS):
            continue
        if state and state.remind_until and state.remind_until > now:
            continue
        cards.append(card)
    return cards


def update_state(child_id, recommendation_key, action):
    if action not in ("dismiss", "remind") or not recommendation_key or len(recommendation_key) > 100:
        return False
    state = _state(child_id, recommendation_key)
    if not state:
        state = CaregiverRecommendationState(child_profile_id=child_id, recommendation_key=recommendation_key)
        Session.add(state)
    now = utcnow()
    if action == "dismiss":
        state.dismissed_at = now
        state.remind_until = None
    else:
        state.remind_until = now + timedelta(hours=rules.REMIND_HOURS)
    Session.commit()
    return True