#!/usr/bin/env python3
"""
email_monitor.py — Real-time inbound email classifier for CLIP.

Runs every 30 minutes. Fetches unread emails from the last 35 minutes,
classifies each as actionable or noise, generates a reply draft for
actionable ones, saves to pending-actions.json, and pushes a Telegram
alert with the draft so Alex can /ok to send or /skip.

Usage:
  python3 tools/email_monitor.py
  python3 tools/email_monitor.py --dry-run   # classify + print, no push

Requires: ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
          Google OAuth token at ~/.google-mcp/tokens/acmestudio.json
"""

import argparse
import base64
import json
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
DATA = BASE / "data"
sys.path.insert(0, str(BASE))

TOKEN_FILE = Path.home() / ".google-mcp" / "tokens" / "acmestudio.json"
CREDENTIALS_FILE = Path.home() / ".google-mcp" / "credentials.json"
SEEN_FILE = DATA / "email_monitor_seen.json"
PENDING_FILE = DATA / "pending-actions.json"
IST = timezone(timedelta(hours=5, minutes=30))
USER_EMAIL = "user@example.com"


def load_env():
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def get_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if not refresh_token:
        if not TOKEN_FILE.exists():
            raise FileNotFoundError(f"Token not found: {TOKEN_FILE}")
        token_data = json.loads(TOKEN_FILE.read_text())
        refresh_token = token_data["refresh_token"]
        client_id = token_data.get("client_id")
        client_secret = token_data.get("client_secret")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
    )
    creds.refresh(Request())
    return creds


def gmail_client():
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=get_credentials())


def load_seen() -> set:
    if not SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except Exception:
        return set()


def save_seen(seen: set):
    DATA.mkdir(parents=True, exist_ok=True)
    # Keep last 500 IDs to avoid unbounded growth
    ids = list(seen)[-500:]
    SEEN_FILE.write_text(json.dumps(ids))


def load_pending() -> list:
    if not PENDING_FILE.exists():
        return []
    try:
        return json.loads(PENDING_FILE.read_text())
    except Exception:
        return []


def save_pending(pending: list):
    DATA.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(pending, indent=2))


def extract_body(payload: dict) -> str:
    """Recursively extract plain text body from Gmail message payload."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    for part in payload.get("parts", []):
        text = extract_body(part)
        if text:
            return text
    return ""


def fetch_recent_unread(gmail, minutes: int = 35) -> list:
    """Return unread messages received in the last N minutes."""
    since = int((datetime.now(timezone.utc) - timedelta(minutes=minutes)).timestamp())
    result = gmail.users().messages().list(
        userId="me",
        q=f"is:unread in:inbox after:{since}",
        maxResults=20,
    ).execute()
    return result.get("messages", [])


def read_message(gmail, msg_id: str) -> dict:
    raw = gmail.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = {h["name"].lower(): h["value"] for h in raw["payload"].get("headers", [])}
    body = extract_body(raw["payload"])[:2000]
    return {
        "id": msg_id,
        "thread_id": raw.get("threadId", ""),
        "from": headers.get("from", ""),
        "subject": headers.get("subject", ""),
        "body": body,
        "snippet": raw.get("snippet", "")[:200],
    }


def classify_and_draft(msg: dict, context: str) -> dict:
    """
    Call Claude Haiku to:
    1. Classify: is this actionable (needs a reply from Alex)?
    2. If yes, draft a reply.
    Returns {actionable: bool, priority: high/medium/low, reason: str,
             reply_subject: str, reply_body: str}
    """
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("[email_monitor] ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""You are CLIP, Alex Doe's AI assistant. Alex runs a small AI automation agency (CLIP Automations / Acme Studio) based in India.

## Alex's context
{context}

## Incoming email
From: {msg['from']}
Subject: {msg['subject']}
Body:
{msg['body']}

## Task
1. Is this email actionable — does it need a reply from Alex? (not spam, not newsletter, not notification)
2. If yes: what priority? (high = client/lead/urgent, medium = partner/opportunity, low = FYI)
3. If yes: draft a short, direct reply in Alex's voice (casual, professional, no fluff). Sign as Alex Doe.

Return ONLY valid JSON:
{{
  "actionable": true/false,
  "priority": "high"/"medium"/"low"/"none",
  "reason": "one line — why this matters or why it's noise",
  "reply_subject": "Re: ...",
  "reply_body": "full reply text or empty string if not actionable"
}}"""

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    from tools.credits import track_usage
    track_usage("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens)

    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def push_telegram(msg: dict, classification: dict, dry_run: bool = False):
    """Send Telegram alert with email summary and reply draft."""
    from tools.notify import send_telegram

    priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(classification["priority"], "⚪")
    sender_name = msg["from"].split("<")[0].strip().strip('"') or msg["from"]

    text = (
        f"{priority_emoji} *New email — action needed*\n\n"
        f"*From:* {sender_name}\n"
        f"*Subject:* {msg['subject']}\n\n"
        f"_{classification['reason']}_\n\n"
        f"*Draft reply:*\n```\n{classification['reply_body'][:800]}\n```\n\n"
        f"Type `/ok` to queue send · `/skip` to dismiss"
    )

    if dry_run:
        print(text)
        return

    send_telegram(text)


def queue_send_action(msg: dict, classification: dict):
    """Add a send_email pending action so /ok in bot triggers the send."""
    pending = load_pending()

    # Extract reply-to address
    from_header = msg["from"]
    if "<" in from_header:
        to_email = from_header.split("<")[1].rstrip(">").strip()
    else:
        to_email = from_header.strip()

    action = {
        "id": str(uuid.uuid4())[:8],
        "action": "send_email",
        "params": {
            "to": to_email,
            "subject": classification["reply_subject"],
            "body": classification["reply_body"],
            "thread_id": msg["thread_id"],
        },
        "reason": f"Reply to: {msg['subject']} from {to_email}",
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "source": "email_monitor",
        "priority": classification["priority"],
    }

    pending.append(action)
    save_pending(pending)
    return action["id"]


def load_context() -> str:
    parts = []
    for fname in ("me.md", "work.md", "priorities.md"):
        path = BASE / "context" / fname
        if path.exists():
            parts.append(path.read_text().strip()[:800])
    return "\n\n".join(parts)


def main():
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print results, don't push or queue")
    args = parser.parse_args()

    if not TOKEN_FILE.exists():
        print("[email_monitor] Google token not found — cannot run", file=sys.stderr)
        sys.exit(1)

    try:
        gmail = gmail_client()
    except Exception as e:
        print(f"[email_monitor] Gmail auth failed: {e}", file=sys.stderr)
        sys.exit(1)

    seen = load_seen()
    messages = fetch_recent_unread(gmail, minutes=35)

    if not messages:
        print("[email_monitor] No new unread emails.")
        return

    context = load_context()
    processed = 0
    alerted = 0

    for m in messages:
        msg_id = m["id"]
        if msg_id in seen:
            continue

        try:
            msg = read_message(gmail, msg_id)
            seen.add(msg_id)

            # Skip emails from self
            if USER_EMAIL in msg["from"].lower():
                continue

            classification = classify_and_draft(msg, context)

            print(f"[email_monitor] {msg['from'][:40]} — {classification['priority']} — {classification['reason'][:60]}")
            processed += 1

            if classification.get("actionable") and classification.get("reply_body"):
                action_id = queue_send_action(msg, classification)
                push_telegram(msg, classification, dry_run=args.dry_run)
                alerted += 1
                print(f"  → Queued action {action_id}, Telegram alert sent")
                try:
                    from tools.actions_log import log_action
                    log_action(
                        "email_reply_queued",
                        {"from": msg["from"], "subject": msg["subject"]},
                        f"action_id={action_id}",
                        source="email_monitor",
                        note=f"Reply queued for: {msg['subject'][:60]}",
                    )
                except Exception:
                    pass

        except Exception as e:
            print(f"[email_monitor] Error on {msg_id}: {e}", file=sys.stderr)

    save_seen(seen)
    print(f"[email_monitor] Done. {processed} emails checked, {alerted} alerts sent.")


if __name__ == "__main__":
    main()
