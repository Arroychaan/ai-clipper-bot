"""
Central configuration module for ai-clipper-bot.
Loads environment variables, manages path definitions, API keys, and video rendering specs.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base Directories
BASE_DIR: Path = Path(__file__).resolve().parent
TEMP_DIR: Path = BASE_DIR / "temp"
LOG_DIR: Path = BASE_DIR / "logs"
TOKENS_DIR: Path = BASE_DIR / "config" / "tokens"
CLIPS_DIR: Path = BASE_DIR / "output_clips"
DB_PATH: Path = BASE_DIR / "bot_state.db"
LOG_FILE_PATH: Path = LOG_DIR / "system.log"

# Auto-create essential operational directories
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(TOKENS_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)

# Parse up to 10 Groq API Keys from environment
def _load_groq_keys() -> tuple[str, ...]:
    keys: list[str] = []
    for i in range(1, 11):
        key = os.getenv(f"GROQ_KEY_{i}")
        if key and key.strip() and not key.startswith("your_"):
            keys.append(key.strip())
    # Fallback to single GROQ_API_KEY if defined
    if not keys and os.getenv("GROQ_API_KEY"):
        fallback = os.getenv("GROQ_API_KEY", "").strip()
        if fallback and not fallback.startswith("your_"):
            keys.append(fallback)
    return tuple(keys)

GROQ_KEYS: tuple[str, ...] = _load_groq_keys()

# Target Video & Language Specifications
TARGET_WIDTH: int = 1080
TARGET_HEIGHT: int = 1920
MIN_CLIP_DURATION: float = 60.0
MAX_CLIP_DURATION: float = 90.0
MIN_VIRAL_SCORE: int = int(os.getenv("MIN_VIRAL_SCORE", "95"))

TARGET_LANGUAGE: str = os.getenv("TARGET_LANGUAGE", "id").lower()  # 'id' for Indonesia, 'en' for Global market

# Gaming Split-Screen Mode Configuration
GAMING_MODE: str = os.getenv("GAMING_MODE", "auto").lower()  # 'true', 'false', 'auto'
GAMING_DIVIDER_COLOR: str = os.getenv("GAMING_DIVIDER_COLOR", "cyan").lower()  # 'cyan', 'yellow', 'purple'


# Dashboard & Web PWA Configuration
DASHBOARD_HOST: str = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "8000"))
DASHBOARD_PASSWORD: str = os.getenv("DASHBOARD_PASSWORD", "admin123")

# Schedule & Ramp-Up Configuration
RAMPUP_MODE: bool = os.getenv("RAMPUP_MODE", "true").lower() in ("true", "1", "t", "yes")
RAMPUP_INTERVAL_SEC: int = int(os.getenv("RAMPUP_INTERVAL_SEC", "28800"))   # ~8 hours = 3 uploads/day
STANDARD_INTERVAL_SEC: int = int(os.getenv("STANDARD_INTERVAL_SEC", "8640")) # ~2.4 hours = 10 uploads/day
RETRY_DELAY_SEC: int = int(os.getenv("RETRY_DELAY_SEC", "60"))

# Target YouTube Sources / Feed Settings
PODCAST_FEEDS: list[str] = [
    "https://www.youtube.com/@radityadika/videos",
    "https://www.youtube.com/@tuah_kreasi/videos",
    "https://www.youtube.com/@Rockaroma_ID/videos",
    "https://www.youtube.com/@HASCreative/videos",
    "https://www.youtube.com/@agaklaenofficial/videos",
    "https://www.youtube.com/@gjlsentertainment6055/videos",
    "https://www.youtube.com/@TirtaPengPengPeng/videos",
    "https://www.youtube.com/@juanneve/videos",
    "https://www.youtube.com/channel/UCp7hJfiiocdY085XnWVrp2Q/videos",
]

SOURCE_FEED_URL: str = os.getenv("SOURCE_FEED_URL", ",".join(PODCAST_FEEDS))
MAX_FEED_ITEMS: int = int(os.getenv("MAX_FEED_ITEMS", "25"))


import base64

# Token & Cookie File Paths
YOUTUBE_CLIENT_SECRETS_FILE: Path = TOKENS_DIR / "client_secrets.json"
YOUTUBE_TOKEN_FILE: Path = TOKENS_DIR / "youtube_token.json"
YOUTUBE_COOKIES_FILE: Path = TOKENS_DIR / "youtube_cookies.txt"
_default_yt_cookie = TOKENS_DIR / ("cookies-youtube-lokal.txt" if TARGET_LANGUAGE == "id" else "cookies-youtube-global.txt")
if not YOUTUBE_COOKIES_FILE.exists() and _default_yt_cookie.exists():
    YOUTUBE_COOKIES_FILE = _default_yt_cookie

# Affiliate Monetization Link Settings
AFFILIATE_COMMENT_TEXT: str = os.getenv("AFFILIATE_COMMENT_TEXT", "").strip()

# Auto-decode token secrets if passed via environment (supports 4 separate accounts)
def _get_env_secret(primary_key: str, fallback_key: str) -> str:
    val = os.getenv(primary_key, "").strip()
    if val:
        return val
    return os.getenv(fallback_key, "").strip()

raw_yt_b64 = (
    _get_env_secret("YOUTUBE_TOKEN_INDO_BASE64", "YOUTUBE_TOKEN_BASE64") if TARGET_LANGUAGE == "id" 
    else _get_env_secret("YOUTUBE_TOKEN_GLOBAL_BASE64", "YOUTUBE_TOKEN_BASE64")
)
if raw_yt_b64:
    try:
        clean_b64 = raw_yt_b64.replace("\r", "").replace("\n", "").replace(" ", "")
        decoded = base64.b64decode(clean_b64)
        with open(YOUTUBE_TOKEN_FILE, "wb") as f:
            f.write(decoded)
        print(f"[config] Successfully decoded YouTube token to {YOUTUBE_TOKEN_FILE}")
    except Exception as e:
        print(f"[config] Failed to decode YouTube token Base64: {e}")

raw_tt_b64 = (
    _get_env_secret("TIKTOK_COOKIES_INDO_BASE64", "TIKTOK_COOKIES_BASE64") if TARGET_LANGUAGE == "id" 
    else _get_env_secret("TIKTOK_COOKIES_GLOBAL_BASE64", "TIKTOK_COOKIES_BASE64")
)
if raw_tt_b64:
    try:
        clean_b64 = raw_tt_b64.replace("\r", "").replace("\n", "").replace(" ", "")
        decoded = base64.b64decode(clean_b64)
        with open(TIKTOK_COOKIES_FILE, "wb") as f:
            f.write(decoded)
        print(f"[config] Successfully decoded TikTok cookies to {TIKTOK_COOKIES_FILE}")
    except Exception as e:
        print(f"[config] Failed to decode TikTok cookies Base64: {e}")

raw_ytcookies_b64 = (
    _get_env_secret("YOUTUBE_COOKIES_INDO_BASE64", "YOUTUBE_COOKIES_BASE64") if TARGET_LANGUAGE == "id" 
    else _get_env_secret("YOUTUBE_COOKIES_GLOBAL_BASE64", "YOUTUBE_COOKIES_BASE64")
)
if raw_ytcookies_b64:
    try:
        clean_b64 = raw_ytcookies_b64.replace("\r", "").replace("\n", "").replace(" ", "")
        decoded = base64.b64decode(clean_b64)
        with open(YOUTUBE_COOKIES_FILE, "wb") as f:
            f.write(decoded)
        print(f"[config] Successfully decoded YouTube cookies to {YOUTUBE_COOKIES_FILE}")
    except Exception as e:
        print(f"[config] Failed to decode YouTube cookies Base64: {e}")
