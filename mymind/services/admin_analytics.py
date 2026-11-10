"""Numbers and chart shapes for the administrator dashboard.

Only counts and money totals are used: no names, no child data. Everything comes from the tables the admin pages already
read (users, subscriptions, payment requests), so no new data is collected.

build() is a pure function (plain lists in, plain dicts out) so it can be tested without a database.
collect() reads the rows and calls build(); it imports the database lazily for the same reason.
The curve / bar geometry is worked out here so the template only has to print it: the dashboard draws its charts as
inline SVG and CSS (no chart library, nothing to load), the same way the caretaker dashboard does.
"""
import math
from collections import Counter
from datetime import timedelta

RANGES = (7, 30, 90)
PALETTE = ["#ff7a1a", "#ffc36b", "#3fd9c8", "#f6f2ec", "#ff7482", "#a78bfa", "#7dd3fc"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _label(d):
    return f"{d.day} {MONTHS[d.month - 1]}"


def smooth_path(points):
    """'M x,y C ...' through the points with smooth cubic curves (same curve style as the caretaker charts)."""
    if not points:
        return ""
    d = "M%.2f,%.2f" % points[0]
    px, py = points[0]
    for x, y in points[1:]:
        xm = (px + x) / 2
        d += " C%.2f,%.2f %.2f,%.2f %.2f,%.2f" % (xm, py, xm, y, x, y)
        px, py = x, y
    if len(points) == 1:
        d += " L100,%.2f" % py
    return d


def _curve(values, dates):
    """Geometry for one smooth line chart: path, filled area, hover dots, x-axis labels."""
    n = len(values)
    peak = max(values) if values and max(values) > 0 else 1
    pts, dots = [], []
    peak_done = False
    for i, (v, d) in enumerate(zip(values, dates)):
        x = (i * 100 / (n - 1)) if n > 1 else 50
        y = 90 - (v / peak * 72)
        pts.append((x, y))
        is_peak = v == max(values) and v > 0 and not peak_done
        peak_done = peak_done or is_peak
        dots.append({"x": round(x, 2), "y": round(y, 2), "label": _label(d), "value": v, "peak": is_peak,
                     "right": x > 78, "left": x < 14})
    step = max(1, math.ceil(n / 6))
    labels = [{"x": round((i * 100 / (n - 1)) if n > 1 else 50, 2), "text": _label(dates[i])} for i in range(0, n, step)]
    path = smooth_path(pts)
    return {"path": path, "area": f"{path} L100,100 L0,100 Z" if path else "", "dots": dots, "labels": labels,
            "peak": max(values) if values else 0, "total": sum(values), "dense": n > 31}


def _bars(buckets):
    """buckets: [(label, value)] -> bar heights as a percentage of the tallest bar."""
    peak = max((v for _, v in buckets), default=0) or 1
    step = max(1, math.ceil(len(buckets) / 6))
    return [{"label": lab, "value": v, "pct": round(v / peak * 100, 1), "show": i % step == 0} for i, (lab, v) in enumerate(buckets)]


def _share_rows(counter, order=None):
    """[(label, count)] -> rows with a bar width relative to the largest count, in a stable colour order."""
    items = [(k, counter[k]) for k in (order or sorted(counter, key=counter.get, reverse=True)) if counter.get(k)]
    top = max((c for _, c in items), default=0) or 1
    return [{"label": k, "count": c, "pct": max(4, round(c / top * 100)), "color": PALETTE[i % len(PALETTE)]} for i, (k, c) in enumerate(items)]


def build(now, days, signups, approved, subs, counts):
    """
    now      datetime (naive UTC)
    days     one of RANGES (anything else becomes 30)
    signups  [datetime]                       caregiver accounts created
    approved [(datetime, amount, currency)]   approved payments (reviewed_at, price paid, currency)
    subs     [(status, expires_at, plan_code)] every subscription
    counts   dict with approved / rejected / pending payment-request totals (from payment_service.stats())
    """
    days = days if days in RANGES else 30
    today = now.date()
    dates = [today - timedelta(days=days - 1 - i) for i in range(days)]
    first = dates[0]

    # ---- sign-ups per day ----
    per_day = Counter(s.date() for s in signups if s and s.date() >= first)
    signup_curve = _curve([per_day.get(d, 0) for d in dates], dates)

    # ---- revenue (money from approved payments), in the most common currency ----
    window = [(r, a, c or "USD") for r, a, c in approved if r and r.date() >= first and a is not None]
    currency = (Counter(c for _, _, c in window).most_common(1) or [("USD", 0)])[0][0]
    window = [(r, a) for r, a, c in window if c == currency]
    size = 1 if days <= 30 else 7                       # 90 days are shown a week at a time so the bars stay readable
    n_buckets = math.ceil(days / size)
    money = [0.0] * n_buckets
    for r, a in window:
        money[min(n_buckets - 1, (r.date() - first).days // size)] += float(a)
    buckets = [(_label(first + timedelta(days=i * size)), round(money[i], 2)) for i in range(n_buckets)]
    revenue = {"bars": _bars(buckets), "total": round(sum(money), 2), "payments": len(window), "currency": currency,
               "per": "day" if size == 1 else "week"}

    # ---- subscriptions: what state are they in right now? ----
    state = Counter()
    plans = Counter()
    for status, expires, plan in subs:
        if status == "active" and expires and expires > now:
            state["Active"] += 1
            plans[(plan or "plan").title()] += 1
        elif status in ("expired", "active"):
            state["Expired"] += 1
        elif status in ("pending_payment", "pending_verification"):
            state["Awaiting payment"] += 1
        elif status == "rejected":
            state["Rejected"] += 1
    order = [k for k in ("Active", "Awaiting payment", "Expired", "Rejected") if state.get(k)]
    total = sum(state.values())
    parts, off = [], 0.0
    for i, k in enumerate(order):
        end = off + state[k] / total * 100
        parts.append({"label": k, "count": state[k], "color": PALETTE[i % len(PALETTE)], "from": off, "to": end})
        off = end
    donut = {"total": total, "parts": parts,
             "css": "conic-gradient(" + ", ".join("%s %.2f%% %.2f%%" % (p["color"], p["from"], p["to"]) for p in parts) + ")" if parts else ""}

    decisions = _share_rows(Counter({"Approved": counts.get("approved", 0), "Rejected": counts.get("rejected", 0),
                                     "Waiting for you": counts.get("pending", 0)}), ["Approved", "Waiting for you", "Rejected"])

    return {"days": days, "start": first, "end": today, "signups": signup_curve, "revenue": revenue, "donut": donut,
            "plans": _share_rows(plans), "decisions": decisions, "active_now": state.get("Active", 0)}


def collect(days=30):
    """Read the rows and build the dashboard numbers. (Database imports are inside so build() stays importable anywhere.)"""
    from database.db import Session
    from database.models import User, Subscription, PaymentVerificationRequest, utcnow
    from services import payment_service

    now = utcnow()
    days = days if days in RANGES else 30
    since = now - timedelta(days=days + 7)
    signups = [r[0] for r in Session.query(User.created_at).filter(User.role == "caregiver", User.created_at >= since).all()]
    approved = [(r[0], r[1], r[2]) for r in
                Session.query(PaymentVerificationRequest.reviewed_at, Subscription.amount, Subscription.currency)
                .join(Subscription, Subscription.id == PaymentVerificationRequest.subscription_id)
                .filter(PaymentVerificationRequest.status == "approved", PaymentVerificationRequest.reviewed_at >= since).all()]
    subs = [(r[0], r[1], r[2]) for r in Session.query(Subscription.status, Subscription.expires_at, Subscription.plan_code).all()]
    return build(now, days, signups, approved, subs, payment_service.stats())
