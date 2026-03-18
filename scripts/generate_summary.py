#!/usr/bin/env python3
"""
Daily Gmail Newsletter Summary Generator
Fetches newsletters from yesterday 07:00 IST → today 07:00 IST
and writes gmail-daily-summary.html in the repo root.
"""

import os
import sys
import json
import base64
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── Auth ────────────────────────────────────────────────────
def get_gmail_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)

# ── Date window ─────────────────────────────────────────────
IST = ZoneInfo("Asia/Kolkata")

def get_window():
    now_ist = datetime.now(IST)
    cutoff_today = now_ist.replace(hour=7, minute=0, second=0, microsecond=0)
    cutoff_yesterday = cutoff_today - timedelta(days=1)
    # Gmail after/before use YYYY/MM/DD
    after  = cutoff_yesterday.strftime("%Y/%m/%d")
    before = cutoff_today.strftime("%Y/%m/%d")
    display_date = cutoff_today.strftime("%a, %d %b %Y")
    return after, before, display_date

# ── Newsletter detection ────────────────────────────────────
NEWSLETTER_SENDERS = {
    "noreply@digest.groww.in",
    "hello@digest.producthunt.com",
    "digest@producthunt.com",
    "newsletter@",
    "digest@",
    "noreply@substack.com",
    "weekly@",
    "daily@",
    "morning@",
    "updates@",
}

NOISE_SENDERS = {
    "noreply@accounts.google.com",
    "alerts@hdfcbank",
    "no-reply@razorpay.com",
    "tickets@bookmyshow",
    "no-reply@info.bookmyshow.com",
    "no-reply@entertainment.bookmyshow.com",
    "invitations@linkedin.com",
    "updates-noreply@linkedin.com",
    "information@mailers.hdfcbank",
    "noreply@github.com",
    "cm.order.email.ikea.com",
}

NEWSLETTER_LABELS = {"CATEGORY_UPDATES", "CATEGORY_PROMOTIONS"}

def is_newsletter(msg):
    headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
    from_addr = headers.get("from", "").lower()
    subject   = headers.get("subject", "").lower()
    labels    = set(msg.get("labelIds", []))

    # Hard exclude noise
    for noise in NOISE_SENDERS:
        if noise in from_addr:
            return False

    # Known newsletter senders
    for sender in NEWSLETTER_SENDERS:
        if sender in from_addr:
            return True

    # List-Unsubscribe header → strong newsletter signal
    if "list-unsubscribe" in headers:
        return True

    # Keyword signals in subject
    newsletter_keywords = ["digest", "weekly", "daily", "newsletter", "roundup",
                           "recap", "edition", "issue #", "briefing", "summary"]
    if any(kw in subject for kw in newsletter_keywords):
        return True

    return False

# ── Extract readable body ───────────────────────────────────
def decode_body(part):
    data = part.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    return ""

def get_text_body(payload):
    """Return plain text from email payload, preferring text/plain."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        return decode_body(payload)
    if mime == "text/html":
        html = decode_body(payload)
        # Strip tags, collapse whitespace
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&#39;", "'", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        return text
    # multipart
    for part in payload.get("parts", []):
        result = get_text_body(part)
        if result:
            return result
    return ""

def truncate(text, max_chars=1200):
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "\n\n[… read more in Gmail]"

# ── Fetch emails ─────────────────────────────────────────────
def fetch_newsletters(service, after, before):
    query = f"after:{after.replace('/','/')} before:{before.replace('/','/')}"
    results = service.users().messages().list(
        userId="me", q=query, maxResults=50
    ).execute()

    messages = results.get("messages", [])
    newsletters = []

    for m in messages:
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="full"
        ).execute()
        if not is_newsletter(msg):
            continue

        headers  = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
        from_raw = headers.get("from", "Unknown")
        sender   = re.sub(r"<.*?>", "", from_raw).strip().strip('"')
        subject  = headers.get("subject", "(no subject)")
        date_raw = headers.get("date", "")

        # Parse time for display
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_raw).astimezone(IST)
            time_str = dt.strftime("%-I:%M %p")
        except Exception:
            time_str = ""

        body = get_text_body(msg["payload"])
        body = truncate(body)

        newsletters.append({
            "id":      msg["id"],
            "sender":  sender,
            "subject": subject,
            "time":    time_str,
            "body":    body,
            "initials": "".join(w[0].upper() for w in sender.split()[:2]),
        })

    return newsletters

# ── HTML generation ──────────────────────────────────────────
COLORS = ["c-blue", "c-green", "c-orange", "c-purple", "c-red", "c-teal"]

def escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))

def build_html(newsletters, display_date):
    count = len(newsletters)
    badge_text = f"{count} newsletter{'s' if count != 1 else ''} today"

    cards_html = ""
    if not newsletters:
        cards_html = """
    <div style="text-align:center;padding:60px 20px;color:#5f6368;">
      <div style="font-size:2.5rem;margin-bottom:12px;">📭</div>
      <div style="font-size:1rem;font-weight:600;">No newsletters today</div>
      <div style="font-size:0.85rem;margin-top:6px;">Check back tomorrow!</div>
    </div>"""
    else:
        for i, nl in enumerate(newsletters):
            color   = COLORS[i % len(COLORS)]
            card_id = f"card-{i}"
            cards_html += f"""
    <div class="card" id="{card_id}">
      <div class="card-header" onclick="toggleCard('{card_id}')">
        <div class="avatar {color}">{escape(nl['initials'])}</div>
        <div class="card-body">
          <div class="card-row1">
            <span class="sender">{escape(nl['sender'])}</span>
            <span class="time">{escape(nl['time'])}</span>
          </div>
          <div class="subject">{escape(nl['subject'])}</div>
        </div>
        <div class="chevron">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M3 6l5 5 5-5" stroke="currentColor" stroke-width="1.8"
                  stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
      </div>
      <div class="card-expand">
        <div class="expand-inner">
          <h3>Full content</h3>
          <div class="full-content">{escape(nl['body'])}</div>
          <a class="open-gmail"
             href="https://mail.google.com/mail/u/0/#inbox/{nl['id']}"
             target="_blank">
            <svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor">
              <path d="M2.003 5.884L10 9.882l7.997-3.998A2 2 0 0016 4H4a2 2 0 00-1.997 1.884z"/>
              <path d="M18 8.118l-8 4-8-4V14a2 2 0 002 2h12a2 2 0 002-2V8.118z"/>
            </svg>
            Open in Gmail
          </a>
        </div>
      </div>
    </div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Gmail Newsletter Summary – {escape(display_date)}</title>
  <style>
    :root {{
      --bg:#f4f6fb; --card:#ffffff; --primary:#4285F4; --red:#EA4335;
      --green:#34A853; --purple:#7c4dff; --teal:#00bcd4; --orange:#ff6d00;
      --text:#202124; --sub:#5f6368; --border:#e0e0e0;
      --shadow:0 1px 4px rgba(0,0,0,.10);
    }}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'Segoe UI',Roboto,Arial,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
    header{{background:linear-gradient(135deg,#4285F4 0%,#34A853 100%);color:#fff;padding:28px 32px 24px;display:flex;align-items:center;gap:18px}}
    .gmail-logo{{width:44px;height:44px;background:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:800;color:#EA4335;flex-shrink:0}}
    header h1{{font-size:1.55rem;font-weight:700}}
    header p{{font-size:.88rem;opacity:.88;margin-top:3px}}
    .badge{{margin-left:auto;background:rgba(255,255,255,.22);border:1px solid rgba(255,255,255,.4);border-radius:20px;padding:6px 16px;font-size:.85rem;white-space:nowrap}}
    main{{max-width:960px;margin:28px auto;padding:0 20px 60px}}
    .section{{margin-bottom:30px}}
    .section-title{{font-size:.78rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--sub);margin-bottom:10px;padding-left:4px}}
    .card{{background:var(--card);border:1px solid var(--border);border-radius:10px;margin-bottom:10px;box-shadow:var(--shadow);overflow:hidden;transition:box-shadow .15s}}
    .card:hover{{box-shadow:0 3px 12px rgba(0,0,0,.13)}}
    .card-header{{display:grid;grid-template-columns:40px 1fr 28px;gap:12px;align-items:start;padding:14px 18px;cursor:pointer;user-select:none}}
    .avatar{{width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:.9rem;color:#fff;flex-shrink:0;margin-top:1px}}
    .card-row1{{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}}
    .sender{{font-weight:600;font-size:.9rem}}
    .time{{font-size:.76rem;color:var(--sub);margin-left:auto;white-space:nowrap}}
    .subject{{font-size:.88rem;font-weight:600;margin-top:2px;color:var(--text)}}
    .chevron{{width:22px;height:22px;display:flex;align-items:center;justify-content:center;color:var(--sub);transition:transform .25s ease;margin-top:8px;flex-shrink:0}}
    .card.open .chevron{{transform:rotate(180deg)}}
    .card-expand{{max-height:0;overflow:hidden;transition:max-height .35s ease;border-top:0px solid var(--border)}}
    .card.open .card-expand{{max-height:4000px;border-top-width:1px}}
    .expand-inner{{padding:18px 20px 18px 72px;background:#fafbff}}
    .expand-inner h3{{font-size:.78rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--sub);margin-bottom:10px}}
    .full-content{{font-size:.86rem;color:var(--text);line-height:1.7;white-space:pre-wrap}}
    .open-gmail{{display:inline-flex;align-items:center;gap:6px;margin-top:16px;padding:8px 16px;background:var(--primary);color:#fff;border-radius:6px;font-size:.82rem;font-weight:600;text-decoration:none;transition:background .15s}}
    .open-gmail:hover{{background:#1a73e8}}
    .c-red{{background:var(--red)}}.c-green{{background:var(--green)}}.c-blue{{background:var(--primary)}}
    .c-purple{{background:var(--purple)}}.c-teal{{background:var(--teal)}}.c-orange{{background:var(--orange)}}
    footer{{text-align:center;font-size:.76rem;color:var(--sub);padding-bottom:20px}}
    footer a{{color:var(--primary);text-decoration:none}}
  </style>
</head>
<body>
<header>
  <div class="gmail-logo">M</div>
  <div>
    <h1>Gmail Newsletter Summary</h1>
    <p>priya.tripathi0207@gmail.com &nbsp;·&nbsp; {escape(display_date)}</p>
  </div>
  <div class="badge">{escape(badge_text)}</div>
</header>
<main>
  <div class="section">
    <div class="section-title">📰 Newsletters &amp; Digests</div>
    {cards_html}
  </div>
</main>
<footer>
  Generated by Claude &nbsp;·&nbsp; Data from
  <a href="https://mail.google.com" target="_blank">Gmail</a>
  &nbsp;·&nbsp; {escape(display_date)}
</footer>
<script>
  function toggleCard(id) {{
    document.getElementById(id).classList.toggle('open');
  }}
</script>
</body>
</html>
"""

# ── Main ─────────────────────────────────────────────────────
def main():
    after, before, display_date = get_window()
    print(f"Window: {after} 07:00 IST → {before} 07:00 IST")

    service = get_gmail_service()
    print("Authenticated with Gmail.")

    newsletters = fetch_newsletters(service, after, before)
    print(f"Found {len(newsletters)} newsletter(s).")

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path  = os.path.join(repo_root, "gmail-daily-summary.html")

    html = build_html(newsletters, display_date)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Written → {out_path}")

if __name__ == "__main__":
    main()
