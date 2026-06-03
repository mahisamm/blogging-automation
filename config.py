# =============================================================================
# WealthMarg Auto Blog Publisher - Configuration
# All secrets come from environment variables.
# Local dev: set variables in .env file (gitignored)
# GitHub Actions: set variables in repo Secrets
# =============================================================================
import os, json
from pathlib import Path

# Load .env file for local development (ignored in GitHub Actions)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# ── Google OAuth ──────────────────────────────────────────────────────────────
CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# ── Google Sheets ─────────────────────────────────────────────────────────────
SPREADSHEET_ID          = os.environ.get("SPREADSHEET_ID", "")
PENDING_SHEET_NAME      = "Pending"
ALL_ARTICLES_SHEET_NAME = "All Articles"

# ── WordPress ─────────────────────────────────────────────────────────────────
WP_URL          = os.environ.get("WP_URL", "")
WP_USERNAME     = os.environ.get("WP_USERNAME", "")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")

# ── Mistral (PRIMARY content generation) ─────────────────────────────────────
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_MODEL   = "mistral-large-latest"

# ── Gemini (FALLBACK — rotate on rate limit) ──────────────────────────────────
_gemini_env = os.environ.get("GEMINI_API_KEYS", "[]")
try:
    GEMINI_API_KEYS = json.loads(_gemini_env)
except Exception:
    GEMINI_API_KEYS = []
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Schedule ──────────────────────────────────────────────────────────────────
BURST_COUNT         = 5   # articles to publish on first local run
ARTICLES_PER_HOUR   = 1   # GitHub Actions publishes 1 per trigger
BURST_DELAY_SECONDS = 30

# ── Google API Scopes ─────────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ── File paths ────────────────────────────────────────────────────────────────
TOKEN_FILE       = "token.json"
CREDENTIALS_FILE = "credentials.json"
