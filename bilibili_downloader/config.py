import json
from pathlib import Path

# bilibili_downloader/config.py

# Download concurrency
MAX_CONCURRENT_DOWNLOADS = 5
MAX_CONCURRENT_API_REQUESTS = 10

# Speed limit
MIN_SPEED_LIMIT_KB = 100  # Minimum speed limit in KB/s
DEFAULT_SPEED_LIMIT_MB = 0.0  # 0 = no limit, in MB/s

# Retry
DOWNLOAD_RETRY_COUNT = 3
RETRY_BACKOFF_BASE = 2  # seconds

# Network
REQUEST_TIMEOUT = 30  # seconds
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Resolution priority (first available wins)
DEFAULT_RESOLUTION_PRIORITY = ["720p", "480p", "1080p", "240p"]

# File naming
DEFAULT_NAME_TEMPLATE = "{title}\u3010{creator}-{section}\u3011"

# Database
DEFAULT_DB_PATH = "bilibili_downloader.db"

# Cookie cache
DEFAULT_COOKIE_CACHE_PATH = "bilibili_cookies.json"

# Web
DEFAULT_WEB_PORT = 8080

# Bilibili API base
BILIBILI_API_BASE = "https://api.bilibili.com"
BILIBILI_SPACE_URL_PATTERN = r"https?://space\.bilibili\.com/(\d+)"

# Settings persistence
SETTINGS_PATH = "bilibili_settings.json"

_DEFAULTS = {
    "max_concurrent_downloads": MAX_CONCURRENT_DOWNLOADS,
    "max_concurrent_api": MAX_CONCURRENT_API_REQUESTS,
    "resolution_priority": DEFAULT_RESOLUTION_PRIORITY,
    "name_template": DEFAULT_NAME_TEMPLATE,
    "output_dir": "./downloads",
    "web_port": DEFAULT_WEB_PORT,
    "download_speed_limit": DEFAULT_SPEED_LIMIT_MB,
}


def load_settings() -> dict:
    """Load user settings from JSON file, falling back to defaults for missing keys."""
    path = Path(SETTINGS_PATH)
    settings = dict(_DEFAULTS)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            settings.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def save_settings(settings: dict) -> None:
    """Save user settings to JSON file."""
    path = Path(SETTINGS_PATH)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
