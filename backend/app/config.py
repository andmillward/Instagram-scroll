import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "app.db"

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))

# How many reels ahead of the current playback position the worker should
# keep pre-fetched at all times.
PREFETCH_WINDOW = int(os.environ.get("PREFETCH_WINDOW", "6"))

# Politeness delay between consecutive downloads, so we don't hammer
# Instagram from a single home IP.
FETCH_DELAY_SECONDS = float(os.environ.get("FETCH_DELAY_SECONDS", "3"))

# How long to sleep when there is nothing to fetch.
IDLE_POLL_SECONDS = float(os.environ.get("IDLE_POLL_SECONDS", "10"))

# Reels more than this many positions behind the current one get their
# cached video file deleted to reclaim disk space (they'll be re-fetched
# on demand if you ever scroll back).
CACHE_KEEP_BEHIND = int(os.environ.get("CACHE_KEEP_BEHIND", "30"))

MAX_FETCH_ATTEMPTS = int(os.environ.get("MAX_FETCH_ATTEMPTS", "3"))

# Optional path to a Netscape-format cookies.txt (exported from your own
# logged-in browser) for reels from private accounts. Entirely optional -
# public reels work with no cookies at all.
COOKIES_FILE = os.environ.get("COOKIES_FILE") or None

FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", "/app/frontend"))

CACHE_DIR.mkdir(parents=True, exist_ok=True)
