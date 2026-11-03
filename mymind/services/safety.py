"""Content-safety filtering applied to every external result before it is shown."""
import re

DEFAULT_BLOCKLIST = [
    "horror", "scary", "creepy", "gore", "blood", "kill", "murder", "weapon", "gun", "shooting", "war",
    "violent", "fight", "explicit", "nsfw", "18+", "adult", "sexy", "drunk", "alcohol", "cigarette",
    "drugs", "suicide", "prank gone", "jumpscare", "jump scare", "nightmare", "slasher", "zombie",
    "gambling", "casino", "fnaf", "five nights",
]

def _norm(t):
    return (t or "").lower()

def parse_keywords(text):
    return [w.strip().lower() for w in re.split(r"[,\n;]", text or "") if w.strip()][:60]

def is_allowed(title, description="", extra_blocklist=None):
    hay = f" {_norm(title)} {_norm(description)} "
    for term in list(DEFAULT_BLOCKLIST) + list(extra_blocklist or []):
        term = term.strip().lower()
        if not term:
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", hay):
            return False
    return True

def filter_items(items, extra_blocklist=None):
    return [i for i in items if is_allowed(i.get("title"), i.get("description"), extra_blocklist)]
