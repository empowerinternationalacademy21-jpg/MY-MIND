"""Editable thresholds and positive activity-to-offline suggestion mappings."""

DOMINANCE_SHARE = 0.40
DOMINANCE_OTHER_STOPS_RATIO = 2.0
DAILY_SCREEN_WARNING_MINUTES = 120
VIDEO_WEEKLY_THRESHOLD_MINUTES = 180
DISMISS_DAYS = 14
REMIND_HOURS = 24
STREAK_ENCOURAGEMENT_DAYS = 3

STOP_ACTIONS = {
    "soccer": ("Try a local soccer club or have a weekend kickabout together.", "sports"),
    "sports": ("Try a local youth sports club or plan a weekend game together.", "sports"),
    "basketball": ("Look for a youth basketball team or visit a local court together.", "sports"),
    "music": ("Explore music lessons, a children's choir, or a kids' band.", "music"),
    "colors": ("Try a drawing kit, an art class, or a family visit to a gallery.", "art"),
    "pictures": ("Try a drawing or photography kit, or visit a local gallery together.", "art"),
    "art": ("Try an art class or make a small creative project together.", "art"),
    "food": ("Cook a simple meal together or look for a children's cooking class.", "food"),
    "nature": ("Plan a family hike, gardening session, or nature walk.", "nature"),
    "animals": ("Visit a nature centre or find an animal-themed activity together.", "nature"),
    "videos": ("Balance screen time with an offline activity connected to a favorite topic; agree on a daily screen-time target together.", "offline"),
    "shorts": ("Balance short clips with an offline activity connected to a favorite topic; agree on a daily screen-time target together.", "offline"),
}

VARIETY_STOPS = ("music", "nature", "pictures", "food", "sports", "colors", "videos", "shorts")
