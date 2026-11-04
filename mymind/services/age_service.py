"""Age-appropriate content rules (ages 3-25).

The caregiver sets the child's age (whole years, 3-25) in Settings or the questionnaire. From that age we pick an
*age band*, and the band decides:

  * which interest categories are offered (e.g. Toys for little ones, Careers for teens and young adults),
  * which search words each category uses (e.g. "puppy" for a 4-year-old, "wildlife documentary" for a teenager),
  * the audience word added to YouTube / Spotify searches ("kids" for the young, nothing for older users),
  * an extra safety blocklist for younger children (on top of the default and caregiver blocklists).

No age set -> `band_for()` returns None and the app behaves exactly as it did before this feature existed
(original 16 categories, original keywords, "kids" searches), so existing accounts are never changed silently.

Only the age in years is stored (never a date of birth).
"""
from services.categories import CATEGORIES, LEGACY_CATEGORIES

MIN_AGE, MAX_AGE = 3, 25

_SHARED = ["animals", "nature", "food", "vehicles", "music", "sports", "people", "places", "art", "stories", "dancing"]

BANDS = {
    "little": {
        "label": "Little Explorers", "min": 3, "max": 5, "audience": "kids",
        "blurb": "Simple, colourful, gentle content: animals, songs, shapes, stories and play.",
        "categories": ["animals", "nature", "food", "vehicles", "music", "sports", "toys", "people", "places", "colors",
                       "art", "objects", "cartoons", "stories", "dancing", "water", "learning"],
        "keywords": {"learning": ["alphabet", "counting numbers", "shapes and colors", "preschool songs"]},
        "block": ["dating", "romance", "romantic", "boyfriend", "girlfriend", "vape", "vaping", "beer", "wine",
                  "true crime", "ghost", "haunted", "spooky", "monster"],
    },
    "young": {
        "label": "Young Learners", "min": 6, "max": 8, "audience": "kids",
        "blurb": "Fun and curious content: animals, science, stories, music and making friends.",
        "categories": list(LEGACY_CATEGORIES) + ["learning", "science", "social"],
        "keywords": {"learning": ["reading practice", "math for kids", "spelling", "fun facts"],
                     "science": ["simple experiments", "space planets", "dinosaurs", "how things work"],
                     "social": ["making friends", "sharing and kindness", "feelings", "good manners"]},
        "block": ["dating", "romance", "romantic", "boyfriend", "girlfriend", "vape", "vaping", "beer", "wine", "true crime"],
    },
    "tween": {
        "label": "Explorers", "min": 9, "max": 12, "audience": "kids",
        "blurb": "Hobbies, science, coding, sport, creativity and building confidence with others.",
        "categories": _SHARED + ["cartoons", "water", "learning", "science", "technology", "social", "wellbeing"],
        "keywords": {
            "animals": ["wildlife", "ocean animals", "dog training", "animal facts"],
            "nature": ["rainforest", "volcano", "weather", "hiking"],
            "food": ["baking", "cooking for kids", "healthy snacks", "pizza making"],
            "vehicles": ["electric cars", "trains", "airplanes", "rockets"],
            "music": ["learn guitar", "piano lessons", "drum cover", "choir"],
            "sports": ["soccer skills", "swimming", "basketball", "gymnastics"],
            "people": ["friendship", "teamwork", "family time", "school life"],
            "places": ["world landmarks", "travel", "museum", "city tour"],
            "art": ["drawing tutorial", "painting", "origami", "pottery"],
            "cartoons": ["animation", "cartoon", "animated short", "stop motion"],
            "stories": ["audiobook", "short story", "adventure story", "myths and legends"],
            "dancing": ["dance tutorial", "hip hop dance", "ballet", "dance routine"],
            "water": ["surfing", "snorkeling", "swimming", "waterfall"],
            "learning": ["study tips", "math tricks", "history facts", "geography"],
            "science": ["science experiments", "space", "robots", "human body"],
            "technology": ["coding for kids", "robots", "how computers work", "3d printing"],
            "social": ["making friends", "kindness", "talking to new people", "teamwork"],
            "wellbeing": ["calm breathing", "mindfulness for kids", "stretching", "healthy sleep"]},
        "block": ["dating", "romance", "romantic", "boyfriend", "girlfriend", "vape", "vaping", "beer", "wine", "true crime"],
    },
    "teen": {
        "label": "Teens", "min": 13, "max": 17, "audience": "",
        "blurb": "Skills, study, creativity, technology, wellbeing and confident communication.",
        "categories": _SHARED + ["cartoons", "learning", "science", "technology", "social", "wellbeing", "careers"],
        "keywords": {
            "animals": ["wildlife documentary", "pets", "marine life", "animal rescue"],
            "nature": ["national park", "hiking", "northern lights", "sustainability"],
            "food": ["cooking", "healthy recipes", "baking", "street food"],
            "vehicles": ["electric vehicles", "aviation", "motorcycles", "engineering"],
            "music": ["guitar lesson", "piano", "music production", "live concert"],
            "sports": ["football skills", "basketball", "athletics", "fitness"],
            "people": ["friendship", "teamwork", "communication skills", "family"],
            "places": ["travel", "world cities", "architecture", "museum"],
            "art": ["digital art", "drawing tutorial", "photography", "graphic design"],
            "cartoons": ["animation", "animated short", "stop motion", "animated film"],
            "stories": ["short stories", "book review", "audiobook", "poetry"],
            "dancing": ["dance tutorial", "hip hop dance", "contemporary dance", "choreography"],
            "learning": ["study skills", "exam revision", "math help", "history"],
            "science": ["science experiments", "space", "chemistry", "biology"],
            "technology": ["coding", "robotics", "web design", "artificial intelligence"],
            "social": ["social skills", "how to start a conversation", "confidence", "public speaking"],
            "wellbeing": ["mindfulness", "stress relief", "sleep", "exercise"],
            "careers": ["career ideas", "job interview tips", "university", "entrepreneurship"]},
        "block": [],
    },
    "adult": {
        "label": "Young Adults", "min": 18, "max": 25, "audience": "",
        "blurb": "Career, study, communication skills, wellbeing, technology and everyday interests.",
        "categories": _SHARED + ["learning", "science", "technology", "social", "wellbeing", "careers"],
        "keywords": {
            "animals": ["wildlife documentary", "pets", "marine life", "animal rescue"],
            "nature": ["national park", "hiking", "sustainability", "landscape photography"],
            "food": ["cooking", "meal prep", "healthy recipes", "baking"],
            "vehicles": ["electric vehicles", "aviation", "engineering", "trains"],
            "music": ["guitar lesson", "piano", "music production", "live concert"],
            "sports": ["fitness", "football", "running", "yoga"],
            "people": ["friendship", "teamwork", "communication skills", "relationships"],
            "places": ["travel", "world cities", "architecture", "museum"],
            "art": ["digital art", "photography", "graphic design", "illustration"],
            "stories": ["short stories", "book review", "audiobook", "poetry"],
            "dancing": ["dance tutorial", "contemporary dance", "salsa", "choreography"],
            "learning": ["study techniques", "online courses", "learn a language", "time management"],
            "science": ["science explained", "space", "psychology", "climate"],
            "technology": ["programming", "ai tools", "cybersecurity basics", "web development"],
            "social": ["small talk", "conversation skills", "networking", "public speaking"],
            "wellbeing": ["meditation", "stress management", "sleep", "fitness"],
            "careers": ["resume tips", "job interview", "internship", "entrepreneurship"]},
        "block": [],
    },
}
BAND_ORDER = ["little", "young", "tween", "teen", "adult"]


class AgeError(ValueError):
    """The age typed in is not a whole number between 3 and 25."""


def parse_age(value):
    """'' / None -> None (not set). Otherwise an int in 3..25, else AgeError."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    if not text.isdigit():
        raise AgeError(f"Please enter the age as a whole number from {MIN_AGE} to {MAX_AGE}.")
    age = int(text)
    if not MIN_AGE <= age <= MAX_AGE:
        raise AgeError(f"Age must be between {MIN_AGE} and {MAX_AGE}.")
    return age


def band_key(age):
    if not isinstance(age, int) or isinstance(age, bool):
        return None
    for key in BAND_ORDER:
        b = BANDS[key]
        if b["min"] <= age <= b["max"]:
            return key
    return None


def band_for(age):
    """The band dict (with its 'key') for an age, or None when no valid age is set."""
    key = band_key(age)
    return dict(BANDS[key], key=key) if key else None


def band_label(age):
    b = band_for(age)
    return f"{b['label']} (ages {b['min']}-{b['max']})" if b else ""


def allowed_categories(age):
    """Ordered category keys offered for this age. No age -> the original 16 (unchanged behaviour)."""
    b = band_for(age)
    return list(b["categories"]) if b else list(LEGACY_CATEGORIES)


def categories_for(age, subset=None):
    """CATEGORIES restricted to this age (optionally also to `subset`, e.g. the Pictures page list)."""
    keys = [k for k in allowed_categories(age) if k in CATEGORIES and (subset is None or k in subset)]
    return {k: CATEGORIES[k] for k in keys}


def keywords_for(category, age):
    """Anonymous search words for a category at this age (never names or notes)."""
    b = band_for(age)
    base = CATEGORIES.get(category, CATEGORIES["objects"]).get("keywords") or ["kids"]
    if b:
        return list(b["keywords"].get(category) or base)
    return list(base)


def audience_for(age):
    """Word appended to YouTube/Spotify searches. 'kids' when no age is set (the original behaviour)."""
    b = band_for(age)
    return b["audience"] if b else "kids"


def extra_blocklist(age):
    b = band_for(age)
    return list(b["block"]) if b else []


def demo_noun(age):
    """Short audience phrase for demo titles."""
    b = band_for(age)
    if not b or b["audience"]:
        return "for kids"
    return "for teens" if b["key"] == "teen" else "for young adults"