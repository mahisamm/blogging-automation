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


def send_telegram_message(text):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.info("Telegram not configured; skipping notification.")
        return
    try:
        telegram_url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": text,
        }
        response = requests.post(telegram_url, json=payload, timeout=15)
        response.raise_for_status()
        log.info("Telegram notification sent.")
    except Exception as e:
        log.warning(f"Failed to send Telegram notification: {e}")


def generate_new_topic(sheets_service):
    existing_articles = read_all_articles(sheets_service)
    existing_topics = [a.get("Topic", "") for a in existing_articles if a.get("Topic")]
    example_list = "\n".join(f"- {topic}" for topic in existing_topics[:20])
    if not example_list:
        example_list = "- None"

    prompt = f"""You are an expert Indian personal finance SEO content strategist.
Suggest one new, unique, and clickworthy blog topic for Indian millennials and young adults (20-40 years old) about personal finance, investing, or money management.
Avoid duplication of these existing topics:
{example_list}
Return only a single topic title on one line with no extra explanation."""
    raw_topic = call_ai(prompt).strip()
    topic_line = "\n".join([line.strip() for line in raw_topic.splitlines() if line.strip()])
    topic = topic_line.splitlines()[0] if topic_line else ""
    if not topic:
        raise Exception("AI did not generate a valid new topic.")
    return topic


def append_pending_topic(sheets_service, topic):
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=config.SPREADSHEET_ID,
        range=f"{config.PENDING_SHEET_NAME}!A:Z",
    ).execute()
    rows = result.get("values", [])
    headers = rows[0] if rows else []
    if headers:
        new_row = ["" for _ in headers]
        if "Topic" in headers:
            new_row[headers.index("Topic")] = topic
        if "Status" in headers:
            new_row[headers.index("Status")] = "Pending"
        if "PublishedDate" in headers:
            new_row[headers.index("PublishedDate")] = ""
        if "ArticleURL" in headers:
            new_row[headers.index("ArticleURL")] = ""
    else:
        new_row = [topic, "Pending", "", ""]

    sheets_service.spreadsheets().values().append(
        spreadsheetId=config.SPREADSHEET_ID,
        range=f"{config.PENDING_SHEET_NAME}!A:Z",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [new_row]},
    ).execute()

    row_number = len(rows) + 1 if rows else 2
    log.info(f"Appended AI-generated topic to Pending sheet at row {row_number}.")
    return row_number


# =============================================================================
# Content Generation — uses call_ai() (Mistral → Gemini fallback)
# =============================================================================
def generate_article(topic):
    prompt = f"""You are a top personal finance content writer for WealthMarg — India's trusted money guide for millennials (ages 20-40).

TOPIC: {topic}

Write a 1500+ word blog article. Follow ALL rules exactly.

CONTENT RULES:
- Open with a powerful hook in the VERY FIRST sentence: a surprising stat, a relatable problem, or a bold question (e.g. "Did you know most Indians lose ₹1–2 lakh every year just by parking money in a savings account?")
- Use REAL Indian context: SIP, PPF, FD, Nifty 50, SEBI, RBI, ₹ (always use ₹ not "Rs" or "INR"), Zerodha, Groww, UPI, tax-saving under 80C, etc.
- Explain everything like a smart, honest friend — short sentences, zero jargon without a plain-English explanation immediately after
- Use relatable analogies (compare SIP to a daily tea habit that builds wealth; compare insurance to a car airbag — you hope you never need it but you're glad it's there)
- Give 3–5 specific, actionable steps the reader can take TODAY or THIS WEEK
- Be encouraging and confidence-building — many Indian readers are first-generation investors who feel intimidated; make them feel capable

FORMAT RULES (STRICT):
- Use ONLY these HTML tags: <h2>, <p>, <ul>, <li>, <ol>, <strong>, <em>
- NO markdown, NO ``` code fences, NO doctype, NO <html>/<head>/<body> tags
- Start directly with a <p> (the hook) — do NOT start with <h2>
- Structure: Hook intro (1–2 paragraphs) → 6 H2 sections with 2–3 paragraphs each → Key takeaways bullet list → Step-by-step numbered action plan → FAQ (5 Q&As with real questions Indians ask) → Conclusion with motivating CTA
- Bold (<strong>) every important number, stat, deadline, or critical tip

SEO RULES:
- Use the main keyword naturally in the first 100 words
- Repeat the keyword 5–7 times total throughout the article
- Write H2 headings that are descriptive and benefit-driven (not generic like "Introduction" or "Conclusion")

WRITE THE FULL ARTICLE NOW:"""
    log.info(f"Generating article for: {topic}")
    raw_html = call_ai(prompt)
    # Clean up markdown code block wrappers if the AI included them
    if raw_html.startswith("```html"):
        raw_html = raw_html[7:]
    if raw_html.endswith("```"):
        raw_html = raw_html[:-3]
    return raw_html.strip()


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
# WordPress — REST API publisher with retry on connection errors
# =============================================================================
def get_or_create_wp_tag(tag_name, headers, max_retries=3):
    """Get existing tag ID or create new one. Returns tag ID."""
    base = f"{config.WP_URL}/wp-json/wp/v2/tags"
    for attempt in range(max_retries):
        try:
            r = requests.get(base, headers=headers, params={"search": tag_name}, timeout=30)
            if r.status_code == 200 and r.json():
                return r.json()[0]["id"]
            r2 = requests.post(base, headers=headers, json={"name": tag_name}, timeout=30)
            if r2.status_code == 201:
                return r2.json()["id"]
            return None
        except requests.exceptions.ConnectionError as e:
            log.warning(f"Tag lookup connection error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(10)
    return None


def publish_to_wordpress(title, content, tags=None, max_retries=3):
    """Publish a post to WordPress using Application Password with retry logic."""
    import base64

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

    payload = {
        "title": title,
        "content": content,
        "status": "publish",
        "tags": tag_ids,
        "format": "standard",
    }

    log.info(f"Publishing to WordPress: {config.WP_URL}")
    for attempt in range(max_retries):
        try:
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
        except requests.exceptions.ConnectionError as e:
            log.warning(f"WordPress connection error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                log.info(f"Retrying in 15 seconds...")
                time.sleep(15)
            else:
                raise Exception(f"WordPress publish failed after {max_retries} attempts: {e}")


# =============================================================================
# Main Workflow
# =============================================================================
def run_publish_workflow():
    log.info("=" * 55)
    log.info("Starting WealthMarg Publish Workflow")
    log.info("=" * 55)

    state_manager.start_run()

    try:
        # --- Auth (Google Sheets only) ---
        creds = get_google_credentials()
        sheets_service = build("sheets", "v4", credentials=creds)

        # --- Step 1: Read Topic ---
        state_manager.update_step(1, "running", "Querying Google Sheets for pending topics...")
        topic_data = read_pending_topic(sheets_service)
        if not topic_data:
            state_manager.update_step(1, "running", "No pending topics found. AI is generating a new topic...")
            topic = generate_new_topic(sheets_service)
            row_number = append_pending_topic(sheets_service, topic)
            state_manager.update_step(1, "success", f"AI created new topic: \"{topic}\" (row {row_number})")
            send_telegram_message(f"🤖 AI generated a new topic and started publishing:\n{topic}")
        else:
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
        full_content = inject_affiliate_links(full_content)
        post = publish_to_wordpress(title, full_content, labels)

        article_url = post.get("url", "")
        published_date = datetime.now(IST).strftime("%Y-%m-%d")
        state_manager.update_step(4, "success", f"Published to WordPress! → {article_url}")

        # --- Step 5: Update Sheets ---
        state_manager.update_step(5, "running", "Updating Google Sheets and logging article...")
        if row_number:
            update_sheet_published(sheets_service, row_number, article_url, published_date)
        else:
            log.info("No pending row available; skipping Pending sheet update.")
        log_to_all_articles(sheets_service, topic, published_date, article_url, word_count)
        state_manager.update_step(5, "success", f"Sheet updated. Article logged to 'All Articles'.")

        state_manager.end_run()
        log.info(f"✅ Workflow complete! Published: {title}")
        log.info(f"   URL: {article_url}")

        send_telegram_message(
            f"✅ Article Published!\n\n"
            f"📝 {title}\n"
            f"🔗 {article_url}\n"
            f"📊 {word_count} words\n"
            f"🕐 {datetime.now(IST).strftime('%d %b %Y, %I:%M %p IST')}"
        )

    except Exception as e:
        import traceback
        err = traceback.format_exc()
        log.error(f"Workflow failed: {err}")
        send_telegram_message(f"❌ Publish workflow failed:\n{str(e)}")
        state_manager.end_run(error=str(e))


# =============================================================================
# Daily Report
# =============================================================================
def run_daily_report():
    log.info("Running daily report...")
    try:
        creds = get_google_credentials()
        sheets_service = build("sheets", "v4", credentials=creds)
        articles = read_all_articles(sheets_service)
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        today_articles = [a for a in articles if (a.get("PublishedDate", "") or "").startswith(today_str)]
        count = len(today_articles)
        log.info(f"Daily Report — {today_str}: {count} articles published today")
        for art in today_articles:
            log.info(f"  ✅ {art.get('Topic','')} → {art.get('ArticleURL','')}")

        send_telegram_message(
            f"📊 Daily report for {today_str}: {count} articles published today.\n" +
            "\n".join([f"- {art.get('Topic','')}\n{art.get('ArticleURL','')}" for art in today_articles[:5]])
        )
    except Exception as e:
        log.error(f"Daily report failed: {e}")


def run_burst_then_schedule():
    """
    Burst mode: publish BURST_COUNT articles immediately on startup,
    then switch to 1 article per hour on a fixed schedule.
    """
    import schedule
    burst = config.BURST_COUNT
    delay = config.BURST_DELAY_SECONDS

    log.info("=" * 55)
    log.info(f"BURST MODE: Publishing {burst} articles now, then every {config.PUBLISH_INTERVAL_HOURS} hours")
    log.info("=" * 55)

    for i in range(burst):
        log.info(f"--- Burst article {i+1}/{burst} ---")
        state_manager.init_state()
        run_publish_workflow()
        if i < burst - 1:
            log.info(f"Waiting {delay}s before next burst article...")
            time.sleep(delay)

    log.info(f"Burst complete! Switching to one article every {config.PUBLISH_INTERVAL_HOURS} hours.")

    # Schedule every N hours
    schedule.every(config.PUBLISH_INTERVAL_HOURS).hours.do(_scheduled_publish)

    # Daily report at configured hour
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
    parser.add_argument("--auth",   action="store_true", help="Run Google OAuth login only")
    parser.add_argument("--test",   action="store_true", help="Run one publish cycle now")
    parser.add_argument("--burst",  action="store_true", help="Burst 5 articles then run 1/hour")
    parser.add_argument("--report", action="store_true", help="Send daily report now")
    args = parser.parse_args()

    if args.auth:
        get_google_credentials()
        print("✅ Authentication done! Token saved.")
    elif args.test:
        run_publish_workflow()
    elif args.report:
        run_daily_report()
    else:
        # Default: burst 5 then 1/hour
        get_google_credentials()
        run_burst_then_schedule()
