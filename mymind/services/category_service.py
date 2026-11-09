"""Sorting content into the right category: animals with animals, people with people, shapes with shapes.

Search engines return what is *related* to a search word, so a "family" search can bring back a dog and an "animals" search a
person. Every item is therefore checked against what its own title / description says it shows, and filed in the category it
really belongs to. This is deliberately conservative:

* Words are scored: a STRONG word (dog, family, circle ...) counts 2, a WEAK word (pet, smile, bright ...) counts 1.
* An item is moved only on clear evidence: the best other category must score at least 2 more than the requested one
  (or at least 2 when the requested category has no evidence at all). Ties, weak hints and empty descriptions keep the
  category that was searched for, so a good result is never moved on a guess.
* In a topic view (no free-text search) an item that really belongs elsewhere is left out, and shows up under its own topic.
  In a free-text search nothing is hidden; the item is simply filed under its true category.
* Only the original topic categories are sorted. Newer ones (learning, science ...) keep what was searched.

`classify()` is pure (no database), so it is cheap, testable and also used by the one-off back-fill of existing items.
"""
import json
import re

SORTED_KINDS = ("picture", "video", "short")           # songs keep their music / dancing category

# category -> (strong words, weak words). Plurals are matched automatically. Phrases are allowed.
_V = {
    "animals": (
        "dog puppy cat kitten horse pony cow bull sheep lamb goat pig piglet chicken hen rooster duck duckling goose rabbit bunny hamster "
        "mouse rat bird parrot owl eagle penguin fish shark whale dolphin turtle tortoise frog snake lizard crocodile alligator lion tiger "
        "leopard cheetah bear panda wolf fox deer elephant giraffe zebra monkey gorilla chimpanzee kangaroo koala camel hippo rhino squirrel "
        "butterfly bee ladybug spider goldfish seal otter donkey llama alpaca peacock flamingo swan pigeon crab octopus jellyfish",
        "animal pet wildlife zoo farm fur paw feather insect bug"),
    "people": (
        "family mother father mom dad mum brother sister grandmother grandfather grandma grandpa baby toddler boy girl child children kid kids "
        "man woman men women person people friends friend teacher student students couple hug hugging parent parents son daughter teenager "
        "portrait boys girls adult",
        "smile smiling together group team crowd laughing"),
    "colors": (
        "shape circle square triangle rectangle oval diamond hexagon pentagon octagon geometric rainbow colorful colourful balloon pattern pastel "
        "polygon cube sphere cone cylinder",
        "color colour bright stripes polka confetti gradient"),
    "nature": (
        "forest flower mountain river lake waterfall meadow sunset sunrise valley canyon jungle rainforest "
        "snow desert volcano rose tulip sunflower petal bamboo moss cliff",
        "nature landscape outdoor green plant tree leaf leaves grass sky cloud field hill garden"),
    "food": (
        "fruit apple banana strawberry grape watermelon pizza burger sandwich bread cake cookie ice cream icecream pasta rice soup salad vegetable "
        "carrot tomato potato egg cheese milk breakfast lunch dinner meal snack chocolate candy cupcake pancake donut doughnut juice pineapple "
        "mango cereal noodles popcorn sausage",
        "food delicious dish cooking baking"),
    "vehicles": (
        "car truck bus train airplane aeroplane plane jet helicopter boat ship motorcycle tractor taxi ambulance fire truck ferry yacht sailboat "
        "subway tram van locomotive scooter bulldozer excavator",
        "vehicle road traffic wheel engine bicycle bike"),
    "music": (
        "guitar piano drum drums violin trumpet saxophone flute harp keyboard microphone singing singer song choir orchestra concert band "
        "musician instrument headphones vinyl melody ukulele xylophone",
        "music sound stage"),
    "sports": (
        "soccer football basketball tennis volleyball baseball gymnastics athlete athletics cycling skateboard golf cricket rugby "
        "stadium referee sport sports playground trampoline karate boxing marathon",
        "ball game exercise fitness training bicycle bike running runner race"),
    "toys": (
        "toy teddy lego building blocks puzzle doll kite rubber duck rocking horse play dough playdough board game stuffed toy",
        "plush playing play"),
    "places": (
        "beach city castle skyline museum church mosque temple airport lighthouse palace harbor harbour",
        "landmark architecture travel house home park building bridge street village town school library tower hospital market island"),
    "art": (
        "painting painter crayon drawing sketch pencil canvas clay sculpture artwork mural graffiti origami watercolor watercolour easel palette "
        "paintbrush craft",
        "art creative brush"),
    "objects": (
        "kitchen clock umbrella shoe scissors spoon fork backpack toothbrush",
        "object item bag chair table lamp cup mug bottle key plate hat glasses door window bed sofa mirror towel bucket basket"),
    "water": (
        "splash pool swimming pool rain wave ocean sea underwater swimming swim raindrop puddle fountain",
        "water wet drops"),
    "dancing": ("dance dancing dancer ballet choreography hip hop", "party"),
    "cartoons": ("cartoon animation animated anime nursery rhyme", "character"),
    "stories": ("storybook story book fairy tale picture book bedtime story book reading", "story fairy"),
}
STRONG_W, WEAK_W = 2, 1
MOVE_MARGIN = 2


def _forms(word):
    """A vocabulary word plus its plural forms."""
    forms = {word, word + "s", word + "es"}
    if word.endswith("y"):
        forms.add(word[:-1] + "ies")
    if word.endswith("f"):
        forms.add(word[:-1] + "ves")
    return forms


def _compile():
    """category -> list of (weight, word forms or phrase). Multi-word entries are written with spaces in the vocabulary strings above,
    so entries are split on single words except for the known phrases below."""
    phrases = ("ice cream", "fire truck", "swimming pool", "building blocks", "rubber duck", "rocking horse", "play dough", "board game",
               "stuffed toy", "fairy tale", "picture book", "bedtime story", "story book", "hip hop", "nursery rhyme")
    out = {}
    for cat, (strong, weak) in _V.items():
        entries = []
        for text, weight in ((strong, STRONG_W), (weak, WEAK_W)):
            rest = f" {text} "
            for ph in phrases:
                if f" {ph} " in rest:
                    entries.append((weight, {ph}))
                    rest = rest.replace(f" {ph} ", " ")
            for w in rest.split():
                entries.append((weight, _forms(w)))
        out[cat] = entries
    return out


_ENTRIES = _compile()
_TOKEN = re.compile(r"[a-z]+")


def _tokens(text):
    return _TOKEN.findall((text or "").lower())


def _detail(title="", description="", tags=None):
    """{category: (score, first position of a matching word)} for the item's own text (each vocabulary entry counts once)."""
    parts = [title or "", description or ""]
    if tags:
        parts.append(" ".join(str(t) for t in tags))
    tokens = _tokens(" ".join(parts))
    joined = " " + " ".join(tokens) + " "
    index = {}
    for pos, tok in enumerate(tokens):
        index.setdefault(tok, pos)
    out = {}
    for cat, entries in _ENTRIES.items():
        total, first = 0, None
        for weight, forms in entries:
            hits = [index[f] for f in forms if " " not in f and f in index]
            hits += [joined[:joined.find(f" {f} ")].count(" ") for f in forms if " " in f and f" {f} " in joined]
            if hits:
                total += weight
                first = min(hits) if first is None else min(first, min(hits))
        if total:
            out[cat] = (total, first)
    return out


def scores(title="", description="", tags=None):
    """{category: score} for the words found in the item's own text."""
    return {c: s for c, (s, _) in _detail(title, description, tags).items()}


def classify(title="", description="", tags=None, requested=None, free=False):
    """-> (category, moved). Keeps `requested` unless the item's own words clearly place it in another category.

    free=True is for free-text searches, where `requested` is only a default filter and not a claim about the item: the item
    is filed under the best-scoring category (score of at least 2; the word that comes first wins a tie)."""
    if requested not in _V:                                  # not a sorted category (learning, science ...): leave it alone
        return requested, False
    found = _detail(title, description, tags)
    if free:
        if not found:
            return requested, False
        top = max(v[0] for v in found.values())
        if top < 2:
            return requested, False
        leaders = sorted((v[1], c) for c, v in found.items() if v[0] == top)
        best = leaders[0][1]
        return best, best != requested
    mine = found.get(requested, (0, None))[0]
    others = {c: v for c, v in found.items() if c != requested}
    if not others:
        return requested, False
    best_score = max(v[0] for v in others.values())
    leaders = [c for c, v in others.items() if v[0] == best_score]
    if len(leaders) > 1:                                     # equal scores: the word that comes first in the description is the subject
        earliest = min(others[c][1] for c in leaders)
        leaders = [c for c in leaders if others[c][1] == earliest]
        if len(leaders) != 1:                                # still a tie: not clear evidence
            return requested, False
    clear = best_score >= mine + MOVE_MARGIN and best_score >= 2
    return (leaders[0], True) if clear else (requested, False)


def _tags(d):
    tags = d.get("tags") if isinstance(d, dict) else None
    if isinstance(tags, str):
        try:
            tags = json.loads(tags or "[]")
        except ValueError:
            tags = []
    return tags if isinstance(tags, list) else []


def sort_items(items, requested, explicit=False):
    """Sort provider items (dicts). Topic view (explicit=False): items that belong elsewhere are left out. Free-text search
    (explicit=True): nothing is hidden, items are filed under their true category. Each kept item gets `_resorted=True` when moved."""
    kept = []
    for d in items:
        if d.get("content_type") not in SORTED_KINDS:
            kept.append(d)
            continue
        category, moved = classify(d.get("title"), d.get("description"), _tags(d), requested, free=explicit)
        if moved and not explicit:
            continue
        if moved:
            d = dict(d, category=category, _resorted=True)
        kept.append(d)
    return kept


def resort_rows(rows):
    """For the back-fill: rows are (id, title, description, tags_json, category, content_type). Returns [(id, old, new)] for items to move."""
    moves = []
    for rid, title, description, tags_json, category, ctype in rows:
        if ctype not in SORTED_KINDS:
            continue
        try:
            tags = json.loads(tags_json or "[]")
        except ValueError:
            tags = []
        new, moved = classify(title, description, tags if isinstance(tags, list) else [], category)
        if moved:
            moves.append((rid, category, new))
    return moves
