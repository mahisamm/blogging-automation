# WealthMarg Auto Blog Publisher

> **Fully automated AI blog publishing system** — reads topics from Google Sheets, generates 1500+ word SEO-optimised articles using Mistral AI (with Gemini fallback), publishes them to WordPress, updates the sheet, and sends Telegram notifications.  
> Runs autonomously on GitHub Actions every 2 hours with zero manual intervention.

---

## 🗂️ Project Structure

```
wealthmarg/
├── auto_publisher.py        # Main workflow engine (AI → WordPress pipeline)
├── config.py                # All config loaded from environment variables
├── server.py                # Local dashboard server (http://localhost:8000)
├── state_manager.py         # Workflow state tracking (JSON file)
├── index.html               # Live monitoring dashboard UI
├── requirements.txt         # Python dependencies
├── .env.example             # Template for local secrets (copy → .env)
├── .gitignore               # Keeps secrets out of Git
└── .github/
    └── workflows/
        └── publish.yml      # GitHub Actions CI — runs every 2 hours
```

---

## ⚙️ How It Works

```
Google Sheets (Pending topics)
        ↓
  [Step 1] Read next "Pending" topic
        ↓  (no topic? AI generates one and appends it)
  [Step 2] Mistral AI writes 1500+ word HTML article
           └── (Gemini fallback with key rotation if Mistral fails)
        ↓
  [Step 3] AI generates SEO title, meta description & tags
        ↓
  [Step 4] Publish to WordPress via REST API (with affiliate link injection)
        ↓
  [Step 5] Update Google Sheets → mark "Published", log to All Articles
        ↓
  Telegram notification sent ✅
```

---

## 🚀 Quick Start (Local)

### 1. Clone & install
```bash
git clone https://github.com/mahisamm/blogging-automation.git wealthmarg
cd wealthmarg
pip install -r requirements.txt
```

### 2. Create your `.env` file
```bash
copy .env.example .env   # Windows
# cp .env.example .env   # Mac/Linux
```
Then edit `.env` and fill in all your secrets (see [`.env.example`](.env.example) for documentation).

### 3. Authenticate with Google
```bash
python auto_publisher.py --auth
```
This opens a browser for OAuth. The token is saved to `token.json`.

### 4. Test WordPress connectivity
```bash
python auto_publisher.py --check-wp
```

### 5. Run one publish cycle
```bash
python auto_publisher.py --test
```

### 6. Start the live dashboard
```bash
python server.py
# Open http://localhost:8000 in your browser
```

### 7. Burst mode (publish 5 articles, then run every 2 hours)
```bash
python auto_publisher.py
```

---

## 🔑 GitHub Secrets Required

Set these in **GitHub → Your Repo → Settings → Secrets → Actions**:

| Secret | Description |
|--------|-------------|
| `GOOGLE_TOKEN_JSON` | Contents of your `token.json` after running `--auth` |
| `GOOGLE_CLIENT_ID` | Google OAuth Client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth Client Secret |
| `SPREADSHEET_ID` | Google Sheets spreadsheet ID |
| `WP_URL` | Your WordPress site URL (e.g. `https://www.wealthmarg.com`) |
| `WP_USERNAME` | WordPress username |
| `WP_APP_PASSWORD` | WordPress Application Password |
| `MISTRAL_API_KEY` | Mistral AI API key (primary AI engine) |
| `GEMINI_API_KEYS` | JSON array of Gemini API keys e.g. `["key1","key2"]` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |

---

## 📊 Google Sheets Setup

Your spreadsheet needs **2 sheets** (tabs):

### `Pending` sheet — columns:
| Topic | Status | PublishedDate | ArticleURL |
|-------|--------|---------------|------------|
| How to start SIP in India | Pending | | |

### `All Articles` sheet — columns:
| Topic | PublishedDate | ArticleURL | WordCount | Status |
|-------|---------------|------------|-----------|--------|

---

## 📅 GitHub Actions Schedule

The workflow ([`publish.yml`](.github/workflows/publish.yml)) runs automatically:
- **Every 2 hours** (cron: `0 */2 * * *`)
- **Manually** via GitHub → Actions → "Run workflow" button

---

## 💡 CLI Reference

```bash
python auto_publisher.py --auth       # Google OAuth login (run once locally)
python auto_publisher.py --check-wp   # Test WordPress connectivity
python auto_publisher.py --test       # Publish 1 article now
python auto_publisher.py --report     # Send daily Telegram report now
python auto_publisher.py              # Burst 5 articles → then 1 every 2 hours
python server.py                      # Start dashboard at http://localhost:8000
```

---

## 🔗 Affiliate Links

Configured in [`auto_publisher.py`](auto_publisher.py) under `AFFILIATE_LINKS`:
- **Groww**: `https://groww.in/invite/ARYOZB`
- **Amazon**: `https://www.amazon.in/?tag=wealthmarg-21`

Add more brands and their referral URLs to auto-inject links into every article.

---

## 📝 Notes

- `token.json`, `.env`, `credentials.json`, `*.log`, `workflow_state.json` are all gitignored — **never commit secrets**
- Mistral AI is the primary engine; Gemini rotates across all configured keys as fallback
- The dashboard polls `/api/status` every 800ms for live step updates
