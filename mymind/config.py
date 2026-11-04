"""Application configuration. All secrets come from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv(override=True)      # values in .env win over empty/stale variables already in the shell
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _clean(name: str) -> str:
    """Env value without stray spaces or quotes (a key pasted as "AIza..." with quotes would count as set but fail)."""
    return os.getenv(name, "").strip().strip('"').strip("'").strip()


def database_url() -> str:
    """Turso (libSQL) when configured, otherwise local SQLite for development."""
    turso = os.getenv("TURSO_DATABASE_URL", "").strip()
    token = os.getenv("TURSO_AUTH_TOKEN", "").strip()
    if turso:
        from urllib.parse import quote_plus
        host = turso.replace("libsql://", "").replace("https://", "").rstrip("/")
        return f"sqlite+hrana://{host}?authToken={quote_plus(token)}"      # pure-Python HTTPS driver (database/hrana.py)
    os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)
    return "sqlite:///" + os.path.join(BASE_DIR, "instance", "mymind.db")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or "dev-only-insecure-key-change-me"
    DATABASE_URL = database_url()
    PRODUCTION = os.getenv("FLASK_ENV", "development").lower() == "production"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = PRODUCTION
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12
    MAX_CONTENT_LENGTH = 256 * 1024
    YOUTUBE_API_KEY = _clean("YOUTUBE_API_KEY")
    SPOTIFY_CLIENT_ID = _clean("SPOTIFY_CLIENT_ID")
    SPOTIFY_CLIENT_SECRET = _clean("SPOTIFY_CLIENT_SECRET")
    PEXELS_API_KEY = _clean("PEXELS_API_KEY")
    # ---- AI 3D pipeline (all optional, server-side only; admin-triggered) ----
    MESHY_API_KEY = _clean("MESHY_API_KEY")
    TRIPO_API_KEY = _clean("TRIPO_API_KEY")
    OPENAI_API_KEY = _clean("OPENAI_API_KEY")
    STABILITY_API_KEY = _clean("STABILITY_API_KEY")
    MESHY_BASE = os.getenv("MESHY_BASE", "https://api.meshy.ai/openapi")
    TRIPO_BASE = os.getenv("TRIPO_BASE", "https://api.tripo3d.ai/v2/openapi")
    MESHY_MODEL = os.getenv("MESHY_MODEL", "latest")                      # resolves to meshy-7.1 server-side
    TRIPO_MODEL = os.getenv("TRIPO_MODEL", "v3.1-20260211")               # confirm in your Tripo dashboard
    CONCEPT_PROVIDER = os.getenv("CONCEPT_PROVIDER", "openai")            # openai | stability
    OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")   # dall-e-3 was shut down 2026-05-12
    AI3D_TARGET_POLYS = int(os.getenv("AI3D_TARGET_POLYS", "12000"))      # 5k-15k budget for web
    AI3D_TEXTURE_SIZE = int(os.getenv("AI3D_TEXTURE_SIZE", "2048"))       # 1024 or 2048
    AI3D_MAX_JOBS_PER_DAY = int(os.getenv("AI3D_MAX_JOBS_PER_DAY", "20"))  # credit guard-rail
    AI3D_MAX_DOWNLOAD_BYTES = 40 * 1024 * 1024
    AI3D_MANUAL_MAX_BYTES = 25 * 1024 * 1024                                         # admin uploads of your own .glb (Blender etc.)
    AI3D_DOWNLOAD_HOSTS = tuple(h.strip() for h in os.getenv("AI3D_DOWNLOAD_HOSTS", "assets.meshy.ai,tripo-data.rg1.data.tripo3d.com,.tripo3d.com,.tripo3d.ai").split(",") if h.strip())
    AI3D_PRIVATE_DIR = os.getenv("AI3D_PRIVATE_DIR", "") or os.path.join(BASE_DIR, "instance", "ai3d_private")
    # ---- Caretaker 18+ verification (Sumsub). Server-side only. ----
    # ID_VERIFICATION: "" = auto (sumsub when keys are set, otherwise off) | off | demo (development only) | sumsub
    ID_VERIFICATION = os.getenv("ID_VERIFICATION", "").strip().lower()
    SUMSUB_APP_TOKEN = _clean("SUMSUB_APP_TOKEN")
    SUMSUB_SECRET_KEY = _clean("SUMSUB_SECRET_KEY")
    SUMSUB_WEBHOOK_SECRET = _clean("SUMSUB_WEBHOOK_SECRET")          # the "Secret key" you set on the webhook in the dashboard
    SUMSUB_LEVEL_NAME = os.getenv("SUMSUB_LEVEL_NAME", "basic-kyc-level")   # case-sensitive; must exist in the same environment
    SUMSUB_BASE_URL = os.getenv("SUMSUB_BASE_URL", "https://api.sumsub.com")
    SUMSUB_SDK_URL = os.getenv("SUMSUB_SDK_URL", "https://static.sumsub.com/idensic/static/sns-websdk-builder.js")
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_WINDOW_SECONDS = 300
    API_MAX_PER_MINUTE = 120
    TESTING = False
    WORLD_ROTATION_SECONDS = int(os.getenv("WORLD_ROTATION_SECONDS", "300") or 300)    # character/scene rotation (5 min)
    WORLD_UPLOAD_MAX_BYTES = 10 * 1024 * 1024                                         # admin art uploads only
    WORLD_ASSET_DIR = os.getenv("WORLD_ASSET_DIR", "") or os.path.join(BASE_DIR, "instance", "world_assets")