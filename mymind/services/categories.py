"""Interest categories, topic keywords (anonymous search terms) and questionnaire option sets."""

CATEGORIES = {
    "animals":  {"label": "Animals",   "icon": "paw-print", "color": "#f5a623", "keywords": ["puppy", "kitten", "farm animals", "zoo animals"]},
    "nature":   {"label": "Nature",    "icon": "trees", "color": "#4caf3f", "keywords": ["forest", "flowers", "mountains", "garden"]},
    "food":     {"label": "Food",      "icon": "apple", "color": "#f9566a", "keywords": ["fruit", "pizza", "ice cream", "breakfast"]},
    "vehicles": {"label": "Vehicles",  "icon": "car", "color": "#2f80ed", "keywords": ["cars", "trains", "airplanes", "boats"]},
    "music":    {"label": "Music",     "icon": "music", "color": "#9a5bd9", "keywords": ["guitar", "drums", "piano", "singing"]},
    "sports":   {"label": "Sports",    "icon": "bike", "color": "#2bb3a6", "keywords": ["soccer", "swimming", "bicycle", "playground"]},
    "toys":     {"label": "Toys",      "icon": "blocks", "color": "#fbb116", "keywords": ["toys", "building blocks", "teddy bear", "puzzle"]},
    "people":   {"label": "Friends & Family", "icon": "users", "color": "#ef6f9a", "keywords": ["family", "friends playing", "children playing", "hugging"]},
    "places":   {"label": "Places",    "icon": "building-2", "color": "#5b8def", "keywords": ["beach", "park", "city", "castle"]},
    "colors":   {"label": "Colors & Shapes", "icon": "shapes", "color": "#7c4dff", "keywords": ["colorful", "rainbow", "shapes", "balloons"]},
    "art":      {"label": "Art",       "icon": "brush", "color": "#e8590c", "keywords": ["painting", "crayons", "drawing", "clay"]},
    "objects":  {"label": "Everyday Things", "icon": "box", "color": "#7a8794", "keywords": ["kitchen", "clock", "umbrella", "shoes"]},
    "cartoons": {"label": "Cartoons",  "icon": "tv", "color": "#14a3c7", "keywords": ["cartoon", "animation", "nursery rhymes", "kids show"]},
    "stories":  {"label": "Stories",   "icon": "book-open", "color": "#a0522d", "keywords": ["storybook", "bedtime story", "picture book", "fairy tale"]},
    "dancing":  {"label": "Dancing",   "icon": "party-popper", "color": "#d6336c", "keywords": ["dance", "kids dance", "ballet", "dance party"]},
    "water":    {"label": "Water Play", "icon": "droplets", "color": "#339af0", "keywords": ["splash", "swimming pool", "rain", "waves"]},
}
# Picture-page filter shows these (spec list); others still exist as interests.
PICTURE_CATEGORIES = ["animals", "nature", "food", "vehicles", "music", "sports", "toys", "people", "places", "colors", "art", "objects"]

# ---- Questionnaire definitions (value, label) ----
ACTIVITIES = [("videos", "Watches videos"), ("music", "Listens to music"), ("toys", "Plays with toys"),
              ("outdoors", "Plays outdoors"), ("art", "Draws or paints"), ("dance", "Dances"),
              ("family", "Interacts with family"), ("children", "Plays with other children"),
              ("books", "Looks at books or pictures"), ("nature", "Explores nature"), ("household", "Joins in household activities")]
INTERESTS = [("animals", "Animals"), ("music", "Music"), ("cartoons", "Cartoons"), ("vehicles", "Vehicles"), ("nature", "Nature"),
             ("food", "Food"), ("sports", "Sports"), ("dancing", "Dancing"), ("toys", "Toys"), ("people", "Family and friendships"),
             ("colors", "Colors and shapes"), ("water", "Water and outdoor play"), ("stories", "Stories"), ("unknown", "Unknown / still exploring")]
COMMUNICATION = [("words", "Spoken words"), ("phrases", "Short phrases"), ("gestures", "Gestures"), ("pointing", "Pointing"),
                 ("cards", "Picture cards"), ("devices", "Communication devices"), ("expressions", "Facial expressions or sounds"),
                 ("combination", "A combination of methods"), ("other", "Other")]
CONTENT_PREFS = [("music_styles", "Music styles"), ("songs", "Favorite songs"), ("animals", "Animals"), ("colors", "Colors"),
                 ("video_subjects", "Video subjects"), ("characters", "Familiar characters"), ("calm", "Quiet / calm content"),
                 ("energetic", "Energetic content"), ("repeat", "Activities chosen again and again"), ("not_sure", "Not sure / still discovering")]
SENSORY = [("loud", "Loud sounds"), ("sudden", "Sudden noises"), ("flashing", "Flashing or fast visual effects"),
           ("dark", "Dark or scary scenes"), ("crowded", "Very busy / crowded scenes")]
ROUTINE = [("morning", "Morning activities"), ("school", "Learning or school"), ("play", "Playtime"), ("meals", "Meals"),
           ("outdoor", "Outdoor activities"), ("musictime", "Music time"), ("rest", "Rest time"), ("evening", "Evening activities")]

INTEREST_TO_CATEGORY = {k: k for k, _ in INTERESTS if k != "unknown"}
ACTIVITY_TO_CATEGORY = {"music": "music", "toys": "toys", "outdoors": "nature", "art": "art", "dance": "dancing",
                        "family": "people", "children": "people", "books": "stories", "nature": "nature"}
CONTENT_PREF_TO_CATEGORY = {"animals": "animals", "colors": "colors", "songs": "music", "music_styles": "music"}


def label_for(cat):
    return CATEGORIES.get(cat, {}).get("label", cat.title())
