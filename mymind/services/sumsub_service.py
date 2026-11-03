"""Sumsub integration: age gate, request signing, applicant + SDK token, webhook verification.

DATA FLOW (read top to bottom)
  1. The caretaker fills in name, email and date of birth on /verify (templates/verify.html + static/js/verify.js).
  2. POST /verify/start  ->  routes/verification.py  ->  parse_dob() + age_on(): an exact, day-accurate AGE GATE.
     Under 18  ->  refused immediately with a gentle, firm message. Sumsub is never called and nothing is stored.
  3. 18+  ->  create_applicant() then access_token(): two HMAC-SHA256-signed server-to-server requests. The browser only ever
     receives the short-lived access token (never the app token or secret key).
  4. The browser mounts the Sumsub WebSDK with that token (static/js/verify.js). The person photographs their document.
  5. Sumsub reviews it and calls POST /verify/webhook (signature-checked). The server then FETCHES the applicant from Sumsub
     itself and decides: GREEN + document date of birth shows 18+  ->  verified. The browser's "submitted" event is never
     trusted, and the self-declared date of birth in step 1 is only a pre-filter (the document's date of birth decides).
  6. Only the outcome is stored (status, verified_at, country, document type). Name, email, DOB and document number are NOT.

Credentials live only in environment variables (config.py). Dates are compared in UTC.
"""
import hashlib
import hmac
import json
import re
import time
from datetime import date, datetime, timezone
import requests
from flask import current_app

SESSION = requests.Session()          # tests replace this with a fake
TIMEOUT = (5, 15)                     # connect, read seconds: a slow provider must never hang a web worker
ADULT_AGE = 18
MAX_AGE = 120
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}$")


class SumsubError(Exception):
    """kind: timeout | unreachable | auth | config | rejected | server. `message` is safe to show to a person."""
    def __init__(self, kind, message, status=None):
        super().__init__(message)
        self.kind, self.status = kind, status


class FormError(ValueError):
    """A problem with what the person typed. Safe to show."""


# ====================================================================== 1. age gate
def today_utc():
    return datetime.now(timezone.utc).date()


def parse_dob(value):
    """'YYYY-MM-DD' (what <input type="date"> sends) -> date. Rejects other formats, impossible dates, the future and > 120 years."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        raise FormError("Please enter your date of birth as day, month and year.")
    try:
        dob = date.fromisoformat(value.strip())
    except ValueError:
        raise FormError("That date doesn't exist. Please check your date of birth.")
    today = today_utc()
    if dob > today:
        raise FormError("Your date of birth can't be in the future.")
    if age_on(dob, today) > MAX_AGE:
        raise FormError("Please check your date of birth.")
    return dob


def age_on(dob, today=None):
    """Exact age in whole years on `today`, correct to the day.
    The birthday counts on the day itself. A 29 February birthday is counted from 1 March in non-leap years (the cautious reading)."""
    today = today or today_utc()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def is_adult(dob, today=None):
    return age_on(dob, today) >= ADULT_AGE


def clean_person(full_name, email):
    name = re.sub(r"\s+", " ", full_name or "").strip() if isinstance(full_name, str) else ""
    if not (2 <= len(name) <= 100) or re.search(r"[\x00-\x1f<>]", name):
        raise FormError("Please enter your full name.")
    mail = (email or "").strip() if isinstance(email, str) else ""
    if len(mail) > 254 or not EMAIL_RE.match(mail):
        raise FormError("Please enter a valid email address.")
    return name, mail


# ====================================================================== 2. signed requests
def _cfg():
    c = current_app.config
    if not (c["SUMSUB_APP_TOKEN"] and c["SUMSUB_SECRET_KEY"]):
        raise SumsubError("config", "Identity verification isn't set up yet. Please contact the administrator.")
    return c


def sign(secret, ts, method, path_with_query, body=b""):
    """X-App-Access-Sig: lowercase hex HMAC-SHA256 of  ts + METHOD + /path?query + raw body bytes."""
    msg = str(ts).encode() + method.upper().encode() + path_with_query.encode() + (body or b"")
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def _call(method, path, payload=None):
    """One signed request. The EXACT bytes that are signed are the bytes that are sent."""
    c = _cfg()
    body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else b""
    ts = int(time.time())                                  # must be within ~1 minute of Sumsub's clock
    headers = {"X-App-Token": c["SUMSUB_APP_TOKEN"], "X-App-Access-Ts": str(ts),
               "X-App-Access-Sig": sign(c["SUMSUB_SECRET_KEY"], ts, method, path, body), "Accept": "application/json"}
    if body:
        headers["Content-Type"] = "application/json"
    try:
        r = SESSION.request(method, c["SUMSUB_BASE_URL"].rstrip("/") + path, data=body or None, headers=headers, timeout=TIMEOUT)
    except requests.Timeout:
        raise SumsubError("timeout", "The verification service took too long to answer. Please try again in a moment.")
    except requests.RequestException:
        raise SumsubError("unreachable", "We couldn't reach the verification service. Please try again in a moment.")
    if r.status_code in (200, 201):
        try:
            return r.json()
        except ValueError:
            raise SumsubError("server", "The verification service sent an unexpected answer.", r.status_code)
    if r.status_code == 409:
        raise SumsubError("conflict", "exists", 409)
    if r.status_code in (401, 403):                        # bad key, bad signature or a clock that is off: a setup problem
        current_app.logger.error("Sumsub rejected our credentials/signature (HTTP %s)", r.status_code)
        raise SumsubError("auth", "Identity verification is temporarily unavailable. Please try again later.", r.status_code)
    if r.status_code == 429 or r.status_code >= 500:
        raise SumsubError("server", "The verification service is busy. Please try again in a moment.", r.status_code)
    current_app.logger.warning("Sumsub request failed with HTTP %s", r.status_code)
    raise SumsubError("rejected", "We couldn't start the verification. Please check your details and try again.", r.status_code)


# ====================================================================== 3. applicant + SDK access token
def external_id(user_id):
    """Stable, opaque id we give Sumsub (it is stored there as externalUserId). No name or email in it."""
    return f"mymind-{int(user_id)}"


def user_id_from_external(ext):
    m = re.fullmatch(r"mymind-(\d+)", ext or "")
    return int(m.group(1)) if m else None


def create_applicant(user_id, full_name, email, dob):
    """POST /resources/applicants?levelName=...  ->  applicant id.
    The details are sent to Sumsub only (to pre-fill and compare with the document); we never store them."""
    level = _cfg()["SUMSUB_LEVEL_NAME"]
    first, _, last = full_name.partition(" ")
    body = {"externalUserId": external_id(user_id), "email": email,
            "fixedInfo": {"firstName": first, "lastName": last or first, "dob": dob.isoformat()}}
    try:
        return _call("POST", f"/resources/applicants?levelName={level}", body)["id"]
    except SumsubError as exc:
        if exc.kind != "conflict":
            raise
        return get_applicant_by_external(user_id)["id"]    # the person already started once: reuse that applicant


def get_applicant_by_external(user_id):
    return _call("GET", f"/resources/applicants/-;externalUserId={external_id(user_id)}/one")


def access_token(user_id, ttl=600):
    """POST /resources/accessTokens/sdk  ->  short-lived token that is valid for this one applicant only."""
    c = _cfg()
    d = _call("POST", "/resources/accessTokens/sdk", {"userId": external_id(user_id), "levelName": c["SUMSUB_LEVEL_NAME"], "ttlInSecs": ttl})
    if not d.get("token"):
        raise SumsubError("server", "The verification service sent an unexpected answer.")
    return d["token"]


# ====================================================================== 4. results (authoritative, server-side)
def get_applicant(applicant_id):
    if not re.fullmatch(r"[A-Za-z0-9]{8,40}", applicant_id or ""):
        raise SumsubError("rejected", "Invalid applicant.")
    return _call("GET", f"/resources/applicants/{applicant_id}/one")


def interpret(applicant, today=None):
    """Turn Sumsub's applicant record into our decision. Returns a dict:
       state: pending | verified | retry | rejected | underage | manual   (+ country, doc_type)
    The adult check uses the date of birth READ FROM THE DOCUMENT by Sumsub, not what the person typed."""
    review = applicant.get("review") or {}
    result = review.get("reviewResult") or {}
    answer, status = result.get("reviewAnswer"), review.get("reviewStatus")
    info = applicant.get("info") or {}
    docs = info.get("idDocs") or []
    out = {"country": (docs[0].get("country") if docs else None) or info.get("country"),
           "doc_type": (docs[0].get("idDocType") if docs else None), "state": "pending"}
    if status != "completed" or answer not in ("GREEN", "RED"):
        return out
    if answer == "RED":
        out["state"] = "retry" if result.get("reviewRejectType") == "RETRY" else "rejected"
        return out
    try:
        dob = parse_dob(info.get("dob"))
    except FormError:
        out["state"] = "manual"                            # approved but no usable date of birth: never auto-verify
        return out
    out["state"] = "verified" if is_adult(dob, today) else "underage"
    return out


# ====================================================================== 5. webhook authenticity
_ALGOS = {"HMAC_SHA256_HEX": hashlib.sha256, "HMAC_SHA512_HEX": hashlib.sha512}     # legacy SHA1 is refused on purpose


def verify_webhook(raw_body, headers):
    """True only if X-Payload-Digest equals HMAC(secret, raw body bytes) with the algorithm named in X-Payload-Digest-Alg."""
    secret = current_app.config.get("SUMSUB_WEBHOOK_SECRET", "")
    algo = _ALGOS.get((headers.get("X-Payload-Digest-Alg") or "").upper())
    digest = (headers.get("X-Payload-Digest") or "").strip().lower()
    if not (secret and algo and digest):
        return False
    expected = hmac.new(secret.encode(), raw_body, algo).hexdigest()
    return hmac.compare_digest(expected, digest)
