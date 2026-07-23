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
DB_PATH: Path = BASE_DIR / "bot_state.db"
LOG_FILE_PATH: Path = LOG_DIR / "system.log"

# Auto-create essential operational directories
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(TOKENS_DIR, exist_ok=True)

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

# Target Video Specifications
TARGET_WIDTH: int = 1080
TARGET_HEIGHT: int = 1920
MIN_CLIP_DURATION: float = 25.0
MAX_CLIP_DURATION: float = 45.0

# Schedule & Ramp-Up Configuration
RAMPUP_MODE: bool = os.getenv("RAMPUP_MODE", "true").lower() in ("true", "1", "t", "yes")
RAMPUP_INTERVAL_SEC: int = int(os.getenv("RAMPUP_INTERVAL_SEC", "28800"))   # ~8 hours = 3 uploads/day
STANDARD_INTERVAL_SEC: int = int(os.getenv("STANDARD_INTERVAL_SEC", "8640")) # ~2.4 hours = 10 uploads/day
RETRY_DELAY_SEC: int = int(os.getenv("RETRY_DELAY_SEC", "60"))

# Target YouTube Sources / Feed Settings
SOURCE_FEED_URL: str = os.getenv("SOURCE_FEED_URL", "https://www.youtube.com/@HubermanLab/videos")
MAX_FEED_ITEMS: int = int(os.getenv("MAX_FEED_ITEMS", "5"))

# Token & Cookie File Paths
YOUTUBE_CLIENT_SECRETS_FILE: Path = TOKENS_DIR / "client_secrets.json"
YOUTUBE_TOKEN_FILE: Path = TOKENS_DIR / "youtube_token.json"
TIKTOK_COOKIES_FILE: Path = TOKENS_DIR / "tiktok_cookies.json"
