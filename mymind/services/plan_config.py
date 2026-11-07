"""Central plan limits and feature access rules."""

FREE_CHILD_PROFILE_LIMIT = 1
PAID_CHILD_PROFILE_LIMIT = 10
TRIAL_CHILD_PROFILE_LIMIT = 1     # the free trial behaves like Free for profiles: one child only
FREE_HISTORY_DAYS = 7
PAID_HISTORY_DAYS = 365
FREE_ACTIVE_SHARE_LINK_LIMIT = 1
FREE_FEATURES = frozenset({"dashboard_basic", "child_world", "share_world"})
PAID_FEATURES = frozenset({"dashboard_basic", "dashboard_full", "history_30_days", "export_report",
                           "share_world", "unlimited_share_links", "child_profiles_10"})

PLAN_CATALOG = {
    "free": {"name": "Free", "days": 0, "price": 0},
    "weekly": {"name": "Weekly", "days": 7},
    "monthly": {"name": "Monthly", "days": 30},
    "yearly": {"name": "Yearly", "days": 365},
}
