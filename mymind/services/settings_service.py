"""Admin-configurable settings (payment details, plans, moderation) and caregiver settings."""
import json
import re
from database.db import Session
from database.models import AdminSetting, CaregiverSettings

PLACEHOLDER = "[NOT SET — administrator must configure in Admin → Settings]"
DEFAULT_PLANS = {"weekly": {"name": "Weekly", "price": 25, "days": 7},
                 "monthly": {"name": "Monthly", "price": 50, "days": 30},
                 "yearly": {"name": "Yearly", "price": 250, "days": 365}}
DEFAULTS = {
    "whatsapp_number": "", "contact_phone": "", "bank_name": "", "bank_account_name": "", "bank_account_number": "",
    "payment_instructions": "Make your payment using the bank details shown, include your payment reference, "
                            "then contact the administrator on WhatsApp to confirm.",
    "plans_json": json.dumps(DEFAULT_PLANS), "brand_tagline": "Your thoughts. Your world.",
    "trial_days": "30", "blocked_keywords": "", "moderation_level": "strict", "shots_enabled": "1",
}


def ensure_defaults():
    existing = {r.setting_key for r in Session.query(AdminSetting).all()}
    for k, v in DEFAULTS.items():
        if k not in existing:
            Session.add(AdminSetting(setting_key=k, setting_value=v))
    Session.commit()


def get_all():
    vals = dict(DEFAULTS)
    for r in Session.query(AdminSetting).all():
        vals[r.setting_key] = r.setting_value
    return vals


def get(key):
    return get_all().get(key, "")


def set_value(key, value):
    row = Session.query(AdminSetting).filter_by(setting_key=key).first()
    if row:
        row.setting_value = value
    else:
        Session.add(AdminSetting(setting_key=key, setting_value=value))


def plans():
    try:
        p = json.loads(get("plans_json"))
        return {k: v for k, v in p.items() if {"name", "price", "days"} <= set(v)} or DEFAULT_PLANS
    except (ValueError, TypeError, AttributeError):
        return DEFAULT_PLANS


def whatsapp_url(number, text="Hello, I would like to confirm my MyMind payment."):
    from urllib.parse import quote
    digits = re.sub(r"\D", "", number or "")
    if not 7 <= len(digits) <= 15:
        return None
    return f"https://wa.me/{digits}?text={quote(text)}"


def payment_display():
    s = get_all()
    shown = {k: (s[k] or PLACEHOLDER) for k in ("whatsapp_number", "contact_phone", "bank_name", "bank_account_name", "bank_account_number")}
    shown["payment_instructions"] = s["payment_instructions"]
    shown["whatsapp_url"] = whatsapp_url(s["whatsapp_number"])
    return shown


# ---- caregiver settings ----
CG_DEFAULTS = {"reduced_motion": False, "large_text": False, "sound_labels": False, "sound_on": True,
               "screen_time_minutes": 30, "recommendation_limit_minutes": 120,
               "shots_enabled": True, "avoid_keywords": "", "restriction": "strict",
               "high_contrast": False, "show_real_people": False, "world": {}}


def caregiver_settings(user_id):
    row = Session.query(CaregiverSettings).filter_by(user_id=user_id).first()
    out = dict(CG_DEFAULTS)
    if row:
        try:
            out.update(json.loads(row.settings_json))
        except ValueError:
            pass
    return out


def save_caregiver_settings(user_id, updates):
    cur = caregiver_settings(user_id)
    cur.update({k: v for k, v in updates.items() if k in CG_DEFAULTS})
    row = Session.query(CaregiverSettings).filter_by(user_id=user_id).first()
    if row:
        row.settings_json = json.dumps(cur)
    else:
        Session.add(CaregiverSettings(user_id=user_id, settings_json=json.dumps(cur)))
    Session.commit()
    return cur
