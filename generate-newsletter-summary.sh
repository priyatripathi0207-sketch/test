#!/usr/bin/env bash
# Daily Gmail Newsletter Summary Generator
# Runs at 07:00 IST (01:30 UTC) every day.
# Summarises newsletters received since 07:00 IST the previous day.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$REPO_DIR/newsletter-summary.log"
BRANCH="claude/gmail-daily-summary-NDRCC"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*" | tee -a "$LOG_FILE"; }

log "=== Starting daily newsletter summary generation ==="

cd "$REPO_DIR"

# Ensure we are on the right branch and up to date
git fetch origin "$BRANCH" >> "$LOG_FILE" 2>&1 || true
git checkout "$BRANCH"     >> "$LOG_FILE" 2>&1

# Calculate the date window:
#   window_start = yesterday 07:00 IST  →  previous day in Gmail query
#   window_end   = today     07:00 IST  →  "now" when this script runs
TODAY=$(TZ="Asia/Kolkata" date '+%Y/%m/%d')
YESTERDAY=$(TZ="Asia/Kolkata" date -d 'yesterday' '+%Y/%m/%d')

PROMPT="You are an automated assistant. Do the following steps exactly, in order, without asking questions.

CONTEXT
- Today's date (IST): $TODAY
- Newsletter window: emails received from $YESTERDAY 07:00 IST to $TODAY 07:00 IST
- Output file: $REPO_DIR/gmail-daily-summary.html
- Git branch: $BRANCH

STEPS
1. Use the Gmail MCP tool \`gmail_search_messages\` with query:
   \"after:${YESTERDAY/\//} before:${TODAY/\//} category:primary OR (label:newsletters)\"
   maxResults: 30
   Also try query: \"newer_than:1d\" to catch anything missed.

2. From the results, identify ONLY newsletter / digest emails — recurring editorial content like:
   daily digests, product roundups, industry newsletters, curated reads.
   Exclude: transaction alerts, booking confirmations, security alerts, promotions, social notifications.

3. For each identified newsletter email, use \`gmail_get_message\` (or equivalent read tool)
   to fetch the full body text. If that tool is unavailable, use the snippet.

4. Rewrite $REPO_DIR/gmail-daily-summary.html with:
   - Header showing today's date ($TODAY) and count of newsletters found.
   - One expandable card per newsletter (click to expand, chevron indicator).
   - Each expanded card shows full readable content (no raw HTML tags) and
     an 'Open in Gmail' button linking to https://mail.google.com/mail/u/0/#inbox/<messageId>
   - Keep the existing CSS design (gradient header, card styles, colour scheme).
   - If zero newsletters found, show a friendly 'No newsletters today' empty state.

5. Stage the file: git add gmail-daily-summary.html
6. Commit with message: 'chore: daily newsletter summary $TODAY'
   followed by a blank line and the session URL placeholder.
7. Push to origin $BRANCH.

Start now."

log "Invoking claude CLI..."
claude --dangerously-skip-permissions -p "$PROMPT" >> "$LOG_FILE" 2>&1

log "=== Done ==="
