"""Safety by construction for AI 3D prompts.

Prompts are NEVER taken from free text. They are assembled from allow-listed archetypes and attributes, so a prompt can only describe
an original, generic object or friendly character. Free-text labels (name, caption) are shown to people but are never sent to a provider;
they are still screened so a real person, team, league or brand cannot be attached to generated art.
Reference photos are not supported at all (so no photo of a real person can ever be used as an input).
The block-list is a safety net, not a complete list: the administrator's review before publishing is the real gate.
"""
import re

CATEGORIES = ("food", "nature", "music", "sports")

# key -> (category, kind, label, description used in the prompt)
ARCHETYPES = {
    # ---- items ----
    "ice_cream_cone": ("food", "item", "Ice-cream cone", "a two-scoop ice-cream cone in a waffle cone"),
    "cupcake": ("food", "item", "Cupcake", "a frosted cupcake with sprinkles"),
    "apple": ("food", "item", "Apple", "a shiny whole apple with a leaf"),
    "pizza_slice": ("food", "item", "Pizza slice", "a slice of cheese pizza"),
    "strawberry": ("food", "item", "Strawberry", "a ripe strawberry with a green top"),
    "oak_tree": ("nature", "item", "Tree", "a small round leafy tree"),
    "sunflower": ("nature", "item", "Sunflower", "a tall sunflower with a big round face"),
    "mushroom": ("nature", "item", "Mushroom", "a spotted toadstool mushroom"),
    "crystal": ("nature", "item", "Crystal", "a cluster of smooth glowing crystals"),
    "butterfly": ("nature", "item", "Butterfly", "a butterfly with patterned wings"),
    "acoustic_guitar": ("music", "item", "Guitar", "an acoustic guitar"),
    "drum": ("music", "item", "Drum", "a round toy drum with two drumsticks"),
    "xylophone": ("music", "item", "Xylophone", "a toy xylophone with coloured bars"),
    "trumpet": ("music", "item", "Trumpet", "a shiny trumpet"),
    "headphones": ("music", "item", "Headphones", "a pair of plain over-ear headphones"),
    "soccer_ball": ("sports", "item", "Football", "a classic football (soccer ball) with plain panels"),
    "basketball": ("sports", "item", "Basketball", "an orange basketball with plain black lines"),
    "trophy": ("sports", "item", "Trophy", "a plain golden trophy cup with two handles"),
    "swim_goggles": ("sports", "item", "Swim goggles", "a pair of plain swim goggles"),
    "bicycle": ("sports", "item", "Bicycle", "a simple children's bicycle"),
    # ---- characters ----
    "ice_cream_buddy": ("food", "character", "Ice-cream buddy", "a friendly ice-cream scoop character with little arms and legs"),
    "cupcake_buddy": ("food", "character", "Cupcake buddy", "a cheerful cupcake character with little arms and legs"),
    "fox": ("nature", "character", "Fox", "a friendly cartoon fox standing on two legs"),
    "rabbit": ("nature", "character", "Rabbit", "a friendly cartoon rabbit standing on two legs"),
    "owl": ("nature", "character", "Owl", "a friendly cartoon owl standing upright"),
    "frog": ("nature", "character", "Frog", "a friendly cartoon frog standing on two legs"),
    "robot_drummer": ("music", "character", "Robot drummer", "a friendly little robot holding two drumsticks"),
    "bear_singer": ("music", "character", "Bear singer", "a friendly cartoon bear holding a toy microphone"),
    "cat_guitarist": ("music", "character", "Cat guitarist", "a friendly cartoon cat holding a small guitar"),
    "dino_dancer": ("music", "character", "Dino dancer", "a friendly cartoon dinosaur in a dancing pose"),
    "bear_footballer": ("sports", "character", "Bear footballer", "a friendly cartoon bear in a plain sports shirt, no numbers or badges"),
    "bunny_swimmer": ("sports", "character", "Bunny swimmer", "a friendly cartoon rabbit wearing plain swim goggles"),
    "penguin_runner": ("sports", "character", "Penguin runner", "a friendly cartoon penguin in a running pose"),
    "elephant_basketball": ("sports", "character", "Elephant player", "a friendly cartoon elephant holding a plain basketball"),
}

# The island kit: one landmark per map place, plus the island base itself. category = the map stop the model belongs to ("island" = the shared base).
LANDMARKS = {
    "lm_island":   ("island", "landmark", "Island base", "a small round floating island with a flat grassy top, a thin sandy shore and a rocky underside, nothing standing on top"),
    "lm_home":     ("home", "landmark", "Home", "a cosy little cottage with a red roof, a round door, two windows and a small chimney"),
    "lm_pictures": ("pictures", "landmark", "Pictures", "three colourful framed pictures on wooden easels"),
    "lm_videos":   ("videos", "landmark", "Videos", "a cheerful retro television with a bright screen showing a play button, on a small stand"),
    "lm_shots":    ("shots", "landmark", "Shorts", "a big friendly smartphone standing upright with a bright screen showing a play button"),
    "lm_music":    ("music", "landmark", "Music", "a colourful drum with two drumsticks and a couple of floating music notes"),
    "lm_sports":   ("sports", "landmark", "Sports", "a small football goal with a net and a plain football beside it"),
    "lm_food":     ("food", "landmark", "Food", "a giant two-scoop ice-cream cone with a cherry on top"),
    "lm_colors":   ("colors", "landmark", "Colors", "a playful pile of colourful toy shapes: a cube, a ball, a cone and a ring, with a small rainbow arch"),
    "lm_nature":   ("nature", "landmark", "Nature", "a small cluster of three leafy trees with a few flowers and a mossy rock"),
    "lm_animals":  ("animals", "landmark", "Animals", "a friendly cartoon puppy sitting beside a little food bowl"),
    "lm_vehicles": ("vehicles", "landmark", "Vehicles", "a cute little toy car with big round wheels"),
    "lm_art":      ("art", "landmark", "Art", "a wooden painter's easel with a colourful painting and a paint palette on the ground"),
}
KIT_ORDER = tuple(LANDMARKS)
KIT_SUFFIX = {"lm_island": "game-ready diorama base, flat top surface, no buildings, no trees, no characters, no water plane"}

COLORS = {"red": "red", "orange": "orange", "yellow": "yellow", "green": "green", "blue": "blue", "purple": "purple",
          "pink": "pink", "brown": "brown", "white": "white", "rainbow": "rainbow-coloured"}
STYLES = {"cartoon": "soft cartoon style with rounded shapes", "plush": "cute soft plush toy style",
          "clay": "smooth clay model style", "lowpoly": "clean stylised low-poly style"}
MOODS = {"happy": "a happy smiling face", "calm": "a calm gentle face", "curious": "a curious bright-eyed face", "sleepy": "a sleepy peaceful face"}
ACCESSORIES = {"none": "", "scarf": "wearing a plain scarf", "hat": "wearing a plain round hat", "bow": "wearing a plain bow",
               "backpack": "wearing a small plain backpack"}
CHARACTER_POSE = "standing in a neutral T-pose-like stance with arms slightly away from the body, facing forward"
SAFETY_SUFFIX = ("original design, child-friendly, no text, no letters, no numbers, no logos, no brand marks, no badges, "
                 "no real person, not based on any existing character")

DEFAULT_OPTIONS = {"color": "blue", "style": "cartoon", "mood": "happy", "accessory": "none"}

_BLOCKED_TERMS = [
    # brands, studios, franchises
    "nike", "adidas", "puma", "reebok", "under armour", "disney", "pixar", "marvel", "dc comics", "pokemon", "pokémon", "pikachu", "mario",
    "sonic the hedgehog", "nintendo", "sega", "lego", "barbie", "hello kitty", "peppa", "paw patrol", "minecraft", "roblox", "fortnite", "spotify",
    "apple music", "coca-cola", "coca cola", "pepsi", "mcdonald", "kfc", "starbucks", "red bull", "gucci", "louis vuitton", "yamaha",
    "fender", "gibson", "steinway", "harley", "ferrari", "lamborghini", "toyota", "tesla", "youtube", "tiktok", "netflix",
    # leagues, clubs, competitions
    "fifa", "uefa", "nba", "nfl", "mlb", "nhl", "premier league", "la liga", "serie a", "bundesliga", "champions league", "world cup",
    "olympic", "olympics", "barcelona", "real madrid", "manchester", "chelsea", "arsenal", "liverpool", "juventus", "bayern", "psg",
    "lakers", "celtics", "knicks", "yankees", "cowboys", "patriots", "golden state warriors", "miami heat", "chicago bulls", "uganda cranes",
    # well-known people
    "messi", "ronaldo", "neymar", "mbappe", "mbappé", "haaland", "salah", "lebron", "stephen curry", "steph curry", "michael jordan", "kobe", "durant",
    "usain bolt", "serena williams", "federer", "nadal", "djokovic", "mike tyson", "muhammad ali", "beyonce", "beyoncé", "taylor swift", "rihanna", "drake", "eminem",
    "michael jackson", "elvis", "beatles", "bob marley", "burna boy", "wizkid", "davido", "diamond platnumz", "bebe cool",
    "trump", "obama", "putin", "biden", "museveni", "elon musk", "bezos", "zuckerberg",
]
_BLOCKED_RE = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(t) for t in sorted(_BLOCKED_TERMS, key=len, reverse=True)) + r")(?![a-z0-9])", re.I)
_LOOKALIKE_RE = re.compile(r"\b(looks?\s+like|look\s+alike|lookalike|inspired\s+by|in\s+the\s+style\s+of|parody|parodies|resembl\w*|"
                           r"version\s+of|based\s+on|knock-?off|copy\s+of|imitation\s+of|similar\s+to|reminds?\s+(?:me\s+)?of|homage)\b", re.I)


class PromptRefused(ValueError):
    """The request would name or imitate a real person, team, league, brand or existing character, or used a value outside the allow-list."""


def check_label(text, field="text"):
    """Screen free text (name / caption) that people will see. Raises PromptRefused; never rewrites."""
    text = (text or "").strip()
    if not text:
        return text
    m = _BLOCKED_RE.search(text)
    if m:
        raise PromptRefused(f"The {field} mentions \"{m.group(1)}\". Real people, teams, leagues and brands can't be used for generated art. "
                            "Use an original description instead (licensed real-star art goes through the World Library).")
    if _LOOKALIKE_RE.search(text):
        raise PromptRefused(f"The {field} asks for something that looks like or is inspired by another person or character. Please describe an original design.")
    if re.search(r"https?://|www\.", text, re.I):
        raise PromptRefused(f"The {field} can't contain links.")
    return text


def archetype_info(key):
    entry = ARCHETYPES.get(key) or LANDMARKS.get(key)
    if entry is None:
        raise PromptRefused("Please choose an item, character or island piece from the list.")
    category, kind, label, desc = entry
    return {"key": key, "category": category, "kind": kind, "label": label, "desc": desc}


def match_archetype(filename):
    """Work out which item, character or island piece a file is for, from its file name. -> archetype key, or None.

    'lm_home.glb', 'home.glb', 'Island base.glb' and 'cupcake.glb' all match. Island-kit places win over items with the same word
    (music.glb is the Music landmark). A label shared by several items or characters is ambiguous, so it matches nothing.
    """
    base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    norm = re.sub(r"[^a-z0-9]+", "_", base.rsplit(".", 1)[0].lower()).strip("_")
    if not norm:
        return None
    if norm in LANDMARKS or norm in ARCHETYPES:
        return norm
    if "lm_" + norm in LANDMARKS:
        return "lm_" + norm
    for table in (LANDMARKS, ARCHETYPES):
        hits = [k for k, v in table.items() if re.sub(r"[^a-z0-9]+", "_", v[2].lower()).strip("_") == norm]
        if len(hits) == 1:
            return hits[0]
    return None


def clean_options(options):
    """Validate against the allow-lists. Unknown keys or values are refused, never ignored (so nothing free-form slips through)."""
    options = dict(options or {})
    out = dict(DEFAULT_OPTIONS)
    for field, allowed in (("color", COLORS), ("style", STYLES), ("mood", MOODS), ("accessory", ACCESSORIES)):
        if field in options:
            v = options.pop(field)
            if v not in allowed:
                raise PromptRefused(f"\"{field}\" has an option that isn't allowed.")
            out[field] = v
    if options:
        raise PromptRefused("Unknown options were supplied.")
    return out


def build_prompt(archetype, options=None):
    """-> (prompt, cleaned_options). Pure function of allow-listed values."""
    info = archetype_info(archetype)
    o = clean_options(options)
    explicit_color = "color" in (options or {})
    if info["kind"] == "landmark" and not explicit_color:             # island-kit pieces keep the colours already described (a red roof stays red)
        parts = [info["desc"], STYLES[o["style"]]]
    else:
        parts = [f"{info['desc']}, mainly {COLORS[o['color']]}", STYLES[o["style"]]]
    if info["kind"] == "landmark":
        parts.append("stylised game-ready diorama piece with a flat base")
        if KIT_SUFFIX.get(archetype):
            parts.append(KIT_SUFFIX[archetype])
    if info["kind"] == "character":
        parts.append(MOODS[o["mood"]])
        if ACCESSORIES[o["accessory"]]:
            parts.append(ACCESSORIES[o["accessory"]])
        parts.append(CHARACTER_POSE)
    parts.append("single character centred on a plain background" if info["kind"] == "character" else "single object centred on a plain background")
    parts.append(SAFETY_SUFFIX)
    return ", ".join(parts), o


def kit_catalog():
    return [{"key": k, "label": v[2], "category": v[0]} for k, v in LANDMARKS.items()]


def catalog():
    """Everything the admin form needs, grouped by category."""
    out = {c: {"item": [], "character": []} for c in CATEGORIES}
    for key, (cat, kind, label, _) in ARCHETYPES.items():
        out[cat][kind].append({"key": key, "label": label})
    return out
