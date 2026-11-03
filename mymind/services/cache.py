"""Small in-memory TTL cache + sliding-window rate limiter.
NOTE: per-process only. For multi-worker production use Redis (documented in README)."""
import time
from collections import defaultdict, deque

_cache = {}

def cache_get(key):
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    _cache.pop(key, None)
    return None

def cache_set(key, value, ttl=1800):
    if len(_cache) > 2000:
        _cache.clear()
    _cache[key] = (time.time() + ttl, value)

def cache_clear():
    _cache.clear()

_hits = defaultdict(deque)

def rate_limited(key, limit, window):
    """Return True if `key` exceeded `limit` hits in `window` seconds (and record this hit)."""
    now = time.time()
    q = _hits[key]
    while q and q[0] <= now - window:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False

def rate_peek(key, limit, window):
    now = time.time()
    q = _hits[key]
    while q and q[0] <= now - window:
        q.popleft()
    return len(q) >= limit

def rate_reset(key=None):
    _hits.clear() if key is None else _hits.pop(key, None)
