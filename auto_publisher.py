"""
=============================================================================
WealthMarg Auto Blog Publisher - Pure Python (Clean Rewrite)
=============================================================================
"""

import os
import sys
import json
import time
import logging
import requests
from datetime import datetime, timezone, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Make sure we can import from same folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import state_manager

# =============================================================================
# Logging
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "publisher.log"),
            encoding="utf-8"
        ),
    ],
)
log = logging.getLogger("WealthMarg")

IST = timezone(timedelta(hours=5, minutes=30))


# =============================================================================
# Google Auth
# =============================================================================
def get_google_credentials():
    base = os.path.dirname(os.path.abspath(__file__))
    token_path = os.path.join(base, config.TOKEN_FILE)
    creds_path = os.path.join(base, config.CREDENTIALS_FILE)
    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, config.SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Refreshing Google token...")
            creds.refresh(Request())
        else:
            log.info("Starting Google OAuth login...")
            if os.path.exists(creds_path):
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, config.SCOPES)
            else:
                client_config = {
                    "installed": {
                        "client_id": config.CLIENT_ID,
                        "client_secret": config.CLIENT_SECRET,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }
                }
                flow = InstalledAppFlow.from_client_config(client_config, config.SCOPES)
            creds = flow.run_local_server(port=0)
            log.info("Google auth successful!")

        with open(token_path, "w") as f:
            f.write(creds.to_json())
        log.info("Token saved.")

    return creds


# =============================================================================
# Google Sheets
# =============================================================================
def read_pending_topic(sheets_service):
    try:
        result = (
            sheets_service.spreadsheets()
            .values()
            .get(spreadsheetId=config.SPREADSHEET_ID, range=f"{config.PENDING_SHEET_NAME}!A:Z")
            .execute()
        )
        rows = result.get("values", [])
        if len(rows) < 2:
            log.info("No data rows in Pending sheet.")
            return None

        headers = rows[0]
        for i, row in enumerate(rows[1:], start=2):
            padded = row + [""] * (len(headers) - len(row))
            row_dict = dict(zip(headers, padded))
            row_dict["row_number"] = i
            status = row_dict.get("Status", "").strip().lower()
            topic = row_dict.get("Topic", "").strip()
            if status == "pending" and topic:
                log.info(f"Found pending topic (row {i}): {topic}")
                return row_dict

        log.info("No pending topics found.")
        return None
    except Exception as e:
        log.error(f"Error reading Google Sheets: {e}")
        raise


def update_sheet_published(sheets_service, row_number, article_url, published_date):
    try:
        result = (
            sheets_service.spreadsheets()
            .values()
            .get(spreadsheetId=config.SPREADSHEET_ID, range=f"{config.PENDING_SHEET_NAME}!1:1")
            .execute()
        )
        headers = result.get("values", [[]])[0]
        updates = []
        for col_idx, header in enumerate(headers):
            col_letter = chr(65 + col_idx)
            if header == "Status":
                updates.append({"range": f"{config.PENDING_SHEET_NAME}!{col_letter}{row_number}", "values": [["Published"]]})
            elif header == "PublishedDate":
                updates.append({"range": f"{config.PENDING_SHEET_NAME}!{col_letter}{row_number}", "values": [[published_date]]})
            elif header == "ArticleURL":
                updates.append({"range": f"{config.PENDING_SHEET_NAME}!{col_letter}{row_number}", "values": [[article_url]]})

        if updates:
            sheets_service.spreadsheets().values().batchUpdate(
                spreadsheetId=config.SPREADSHEET_ID,
                body={"valueInputOption": "RAW", "data": updates},
            ).execute()
            log.info(f"Sheet row {row_number} updated as Published.")
    except Exception as e:
        log.error(f"Error updating sheet: {e}")
        raise


def log_to_all_articles(sheets_service, topic, published_date, article_url, word_count):
    try:
        sheets_service.spreadsheets().values().append(
            spreadsheetId=config.SPREADSHEET_ID,
            range=f"{config.ALL_ARTICLES_SHEET_NAME}!A:E",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [[topic, published_date, article_url, str(word_count), "Published"]]},
        ).execute()
        log.info("Logged to All Articles sheet.")
    except Exception as e:
        log.error(f"Error logging to All Articles: {e}")
        raise


def read_all_articles(sheets_service):
    try:
        result = (
            sheets_service.spreadsheets()
            .values()
            .get(spreadsheetId=config.SPREADSHEET_ID, range=f"{config.ALL_ARTICLES_SHEET_NAME}!A:E")
            .execute()
        )
        rows = result.get("values", [])
        if not rows:
            return []
        headers = rows[0]
        return [dict(zip(headers, row + [""] * (len(headers) - len(row)))) for row in rows[1:]]
    except Exception as e:
        log.error(f"Error reading All Articles: {e}")
        return []


# =============================================================================
# Mistral AI — PRIMARY for all content generation
# =============================================================================
def call_mistral(prompt, max_retries=3):
    """Call Mistral API for content generation. Primary AI engine."""
    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.MISTRAL_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 4096,
    }
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
            log.info(f"Mistral response received (attempt {attempt+1})")
            return text
        except Exception as e:
            log.warning(f"Mistral attempt {attempt+1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
    raise Exception("Mistral API failed after all retries")


# =============================================================================
# Gemini AI — FALLBACK only (used if Mistral fails)
# =============================================================================
_current_key_index = 0

def call_gemini_fallback(prompt):
    """Call Gemini API with key rotation. Fallback only — preserves quota."""
    global _current_key_index
    keys = config.GEMINI_API_KEYS
    total_keys = len(keys)

    if total_keys == 0:
        raise Exception("No Gemini fallback keys configured.")

    attempts = 0
    max_total_attempts = total_keys * 2

    while attempts < max_total_attempts:
        key = keys[_current_key_index]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            response = requests.post(url, json=payload, timeout=120)
            if response.status_code == 429:
                log.warning(f"[Gemini Fallback] Key [{_current_key_index+1}/{total_keys}] rate limited. Rotating...")
                _current_key_index = (_current_key_index + 1) % total_keys
                attempts += 1
                time.sleep(5)
                continue
            response.raise_for_status()
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            log.info(f"[Gemini Fallback] Response via key [{_current_key_index+1}/{total_keys}]")
            return text
        except Exception as e:
            log.warning(f"[Gemini Fallback] Key [{_current_key_index+1}/{total_keys}] failed: {e}")
            _current_key_index = (_current_key_index + 1) % total_keys
            attempts += 1
            time.sleep(5)

    raise Exception(f"All Gemini fallback keys exhausted after {attempts} attempts.")


def call_ai(prompt):
    """
    Smart AI router:
    1. Try Mistral first (primary — saves Gemini quota)
    2. Fall back to Gemini with key rotation if Mistral fails
    """
    try:
        return call_mistral(prompt)
    except Exception as mistral_err:
        log.warning(f"Mistral failed: {mistral_err}. Falling back to Gemini...")
        return call_gemini_fallback(prompt)


# =============================================================================
# Content Generation — uses call_ai() (Mistral → Gemini fallback)
# =============================================================================
def generate_article(topic):
    prompt = f"""You are an expert SEO content writer for Indian personal finance.

TOPIC: {topic}

Write a 1500+ word blog article with STRICT rules:
1. FORMAT: Only HTML tags (h2, p, ul, li, ol, strong, em). NO markdown, NO doctype, NO body tags. Start directly with <h2> or <p>.
2. STRUCTURE: Intro → 6 H2 sections → bullet list → numbered list → FAQ (5 Q&A) → Conclusion with CTA
3. TONE: Conversational, for Indians 20-40, use 'you', mention Groww/Zerodha/Amazon where natural
4. SEO: Use main keyword in first 100 words, 5-7 times total

WRITE THE ARTICLE NOW:"""
    log.info(f"Generating article for: {topic}")
    return call_ai(prompt)


def generate_seo_metadata(topic):
    prompt = f"""Topic: {topic}

Return ONLY a valid JSON object (no markdown, no backticks):
{{
  "seo_title": "max 60 chars with main keyword",
  "meta_description": "max 155 chars with keyword and CTA",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}"""
    log.info("Generating SEO metadata...")
    raw = call_ai(prompt)
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1:
            return json.loads(raw[start:end+1])
        return json.loads(raw)
    except Exception:
        log.warning("Failed to parse SEO JSON, using defaults.")
        return {"seo_title": topic, "meta_description": "", "tags": []}


# =============================================================================
# Affiliate Link Injection — Auto-embeds referral links into every article
# =============================================================================
# Add your affiliate links here. They will be automatically embedded
# into every article the robot publishes.
AFFILIATE_LINKS = {
    "Groww":   "https://groww.in/invite/ARYOZB",
    "groww":   "https://groww.in/invite/ARYOZB",
    "Amazon":  "https://www.amazon.in/?tag=wealthmarg-21",
    "amazon":  "https://www.amazon.in/?tag=wealthmarg-21",
    # Add more below when you get them:
    # "Zerodha": "https://zerodha.com/open-account?c=YOURCODE",
    # "Upstox":  "https://upstox.com/open-account/?f=YOURCODE",
}


def inject_affiliate_links(html_content):
    """Replace brand mentions with affiliate links in HTML content."""
    import re
    for brand, url in AFFILIATE_LINKS.items():
        # Only link the FIRST occurrence of each brand to avoid over-linking
        pattern = rf'(?<!["\'>])({re.escape(brand)})(?![^<]*>)(?![^<]*</a>)'
        replacement = rf'<a href="{url}" target="_blank" rel="nofollow sponsored">\1</a>'
        html_content = re.sub(pattern, replacement, html_content, count=1)
    return html_content




# =============================================================================
# WordPress — Simple REST API publisher (no OAuth needed!)
# =============================================================================
def get_or_create_wp_tag(tag_name, headers):
    """Get existing tag ID or create new one. Returns tag ID."""
    base = f"{config.WP_URL}/wp-json/wp/v2/tags"
    # Try to find existing tag
    r = requests.get(base, headers=headers, params={"search": tag_name}, timeout=30)
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    # Create new tag
    r = requests.post(base, headers=headers, json={"name": tag_name}, timeout=30)
    if r.status_code == 201:
        return r.json()["id"]
    return None


def publish_to_wordpress(title, content, tags=None):
    """Publish a post to WordPress using Application Password. No OAuth needed!"""
    import base64

    # Build auth header from Application Password
    credentials = f"{config.WP_USERNAME}:{config.WP_APP_PASSWORD}"
    token = base64.b64encode(credentials.encode()).decode("utf-8")
    headers = {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }

    # Resolve tag names to WordPress tag IDs
    tag_ids = []
    for tag in (tags or []):
        tag_id = get_or_create_wp_tag(tag, headers)
        if tag_id:
            tag_ids.append(tag_id)

    # Create the post
    payload = {
        "title": title,
        "content": content,
        "status": "publish",   # publish immediately
        "tags": tag_ids,
        "format": "standard",
    }

    log.info(f"Publishing to WordPress: {config.WP_URL}")
    response = requests.post(
        f"{config.WP_URL}/wp-json/wp/v2/posts",
        headers=headers,
        json=payload,
        timeout=60,
    )

    if response.status_code == 201:
        post_data = response.json()
        post_url = post_data.get("link", config.WP_URL)
        post_id = post_data.get("id", "")
        log.info(f"[WordPress] Published successfully! URL: {post_url}")
        return {"url": post_url, "id": post_id, "title": title}
    else:
        raise Exception(
            f"WordPress API returned {response.status_code}: {response.text[:400]}"
        )


# =============================================================================
# Telegram
# =============================================================================
def send_telegram_message(message):
    if not config.TELEGRAM_BOT_TOKEN:
        log.warning("No Telegram token configured.")
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": config.TELEGRAM_CHAT_ID, "text": message}, timeout=30)
        resp.raise_for_status()
        log.info("Telegram message sent.")
    except Exception as e:
        log.error(f"Telegram error: {e}")


# =============================================================================
# Main Workflow
# =============================================================================
def run_publish_workflow():
    log.info("=" * 55)
    log.info("Starting WealthMarg Publish Workflow")
    log.info("=" * 55)

    state_manager.start_run()

    try:
        # --- Auth (Google Sheets only now) ---
        creds = get_google_credentials()
        sheets_service = build("sheets", "v4", credentials=creds)

        # --- Step 1: Read Topic ---
        state_manager.update_step(1, "running", "Querying Google Sheets for pending topics...")
        topic_data = read_pending_topic(sheets_service)
        if not topic_data:
            state_manager.update_step(1, "success", "No pending topics found. Workflow skipped.")
            state_manager.end_run()
            return

        topic = topic_data["Topic"]
        row_number = topic_data["row_number"]
        state_manager.update_step(1, "success", f"Found topic: \"{topic}\" (row {row_number})")

        # --- Step 2: Generate Article ---
        state_manager.update_step(2, "running", f"Writing 1500+ word article for: {topic}")
        html_content = generate_article(topic)
        word_count = len(html_content.split())
        state_manager.update_step(2, "success", f"Article generated — {word_count} words")

        # --- Step 3: SEO Metadata ---
        state_manager.update_step(3, "running", "Generating SEO title, description and tags...")
        seo_data = generate_seo_metadata(topic)
        title = seo_data.get("seo_title", topic)
        labels = seo_data.get("tags", [])
        state_manager.update_step(3, "success", f"Title: \"{title}\" | Tags: {', '.join(labels[:3])}")

        # --- Step 4: Publish to WordPress ---
        state_manager.update_step(4, "running", "Publishing post to WordPress...")
        full_content = html_content + '\n\n<hr><p style="font-size:12px;color:#999;">This article may contain affiliate links.</p>'
        full_content = inject_affiliate_links(full_content)   # 💰 embed affiliate links
        post = publish_to_wordpress(title, full_content, labels)

        article_url = post.get("url", "")
        published_date = datetime.now(IST).strftime("%Y-%m-%d")
        state_manager.update_step(4, "success", f"Published to WordPress! → {article_url}")

        # --- Step 5: Update Sheets ---
        state_manager.update_step(5, "running", "Updating Google Sheets and logging article...")
        update_sheet_published(sheets_service, row_number, article_url, published_date)
        log_to_all_articles(sheets_service, topic, published_date, article_url, word_count)
        state_manager.update_step(5, "success", f"Sheet updated. Article logged to 'All Articles'.")

        state_manager.end_run()
        log.info(f"✅ Workflow complete! Published: {title}")
        log.info(f"   URL: {article_url}")

        # Send Telegram success
        send_telegram_message(
            f"✅ WealthMarg Published!\n\n📝 {title}\n🔗 {article_url}\n📊 {word_count} words"
        )

    except Exception as e:
        import traceback
        err = traceback.format_exc()
        log.error(f"Workflow failed: {err}")
        state_manager.end_run(error=str(e))


# =============================================================================
# Daily Report
# =============================================================================
def run_daily_report():
    log.info("Running daily Telegram report...")
    creds = get_google_credentials()
    sheets_service = build("sheets", "v4", credentials=creds)
    articles = read_all_articles(sheets_service)
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    today_articles = [a for a in articles if (a.get("PublishedDate", "") or "").startswith(today_str)]
    count = len(today_articles)

    msg = f"📊 WealthMarg Daily Report\n📅 {today_str}\n📝 Articles published today: {count}\n\n"
    for art in today_articles:
        msg += f"✅ {art.get('Topic','')}\n🔗 {art.get('ArticleURL','')}\n\n"
    msg += "Keep publishing! 🚀"
    send_telegram_message(msg)


def run_burst_then_schedule():
    """
    Burst mode: publish BURST_COUNT articles immediately on startup,
    then switch to 1 article per hour on a fixed schedule.
    """
    import schedule
    burst = config.BURST_COUNT
    delay = config.BURST_DELAY_SECONDS

    log.info("=" * 55)
    log.info(f"BURST MODE: Publishing {burst} articles now, then 1/hour")
    log.info("=" * 55)

    for i in range(burst):
        log.info(f"--- Burst article {i+1}/{burst} ---")
        state_manager.init_state()
        run_publish_workflow()
        if i < burst - 1:
            log.info(f"Waiting {delay}s before next burst article...")
            time.sleep(delay)

    log.info("Burst complete! Switching to 1 article/hour schedule.")
    send_telegram_message(f"✅ Burst complete! Published {burst} articles.\nNow running 1 article/hour automatically.")

    # Schedule 1 per hour at :00
    schedule.every().hour.at(":00").do(_scheduled_publish)

    # Daily report at 9 PM
    schedule.every().day.at(f"{config.REPORT_HOUR:02d}:00").do(run_daily_report)

    log.info("Hourly scheduler started. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(30)


def _scheduled_publish():
    """Reset state then run workflow for scheduled runs."""
    state_manager.init_state()
    run_publish_workflow()


# =============================================================================
# CLI
# =============================================================================
if __name__ == "__main__":
    import argparse
    import schedule

    parser = argparse.ArgumentParser(description="WealthMarg Auto Blog Publisher")
    parser.add_argument("--auth", action="store_true", help="Run Google OAuth login only")
    parser.add_argument("--test", action="store_true", help="Run one publish cycle now")
    parser.add_argument("--burst", action="store_true", help="Burst 5 articles then run 1/hour")
    parser.add_argument("--report", action="store_true", help="Send daily Telegram report now")
    args = parser.parse_args()

    if not config.GEMINI_API_KEYS:
        print("ERROR: No GEMINI_API_KEYS configured in config.py")
        sys.exit(1)

    if args.auth:
        get_google_credentials()
        print("✅ Authentication done! Token saved.")
    elif args.test:
        run_publish_workflow()
    elif args.report:
        run_daily_report()
    else:
        # Default + --burst: burst 5 then 1/hour
        get_google_credentials()
        run_burst_then_schedule()

