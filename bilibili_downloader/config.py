# bilibili_downloader/config.py

# Download concurrency
MAX_CONCURRENT_DOWNLOADS = 5
MAX_CONCURRENT_API_REQUESTS = 10

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

# Web
DEFAULT_WEB_PORT = 8080

# Bilibili API base
BILIBILI_API_BASE = "https://api.bilibili.com"
BILIBILI_SPACE_URL_PATTERN = r"https?://space\.bilibili\.com/(\d+)"
