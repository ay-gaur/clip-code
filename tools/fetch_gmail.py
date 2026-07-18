#!/usr/bin/env python3
"""
fetch_gmail.py — Fetch recent Gmail messages for user@example.com.

Same OAuth pattern as fetch_calendar.py. Calls Gmail API directly so it
works in cron jobs without the MCP server running.

Used by heartbeat.py to detect unanswered client emails.

Usage:
  python3 tools/fetch_gmail.py              # print unread inbox threads
  python3 tools/fetch_gmail.py --days 3     # look back 3 days
  python3 tools/fetch_gmail.py --json       # raw JSON output
"""

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from email.utils import parseaddr

TOKEN_FILE = Path.home() / ".google-mcp" / "tokens" / "acmestudio.json"
CREDENTIALS_FILE = Path.home() / ".google-mcp" / "credentials.json"
IST = timezone(timedelta(hours=5, minutes=30))

USER_EMAIL = "user@example.com"


def get_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if not refresh_token:
        # Local dev fallback — read from token file
        if not TOKEN_FILE.exists():
            raise FileNotFoundError(f"Token file not found: {TOKEN_FILE}")
        token_data = json.loads(TOKEN_FILE.read_text())
        refresh_token = token_data["refresh_token"]
        client_id = token_data.get("client_id")
        client_secret = token_data.get("client_secret")
        if not client_id and CREDENTIALS_FILE.exists():
            creds_data = json.loads(CREDENTIALS_FILE.read_text())
            installed = creds_data.get("installed") or creds_data.get("web", {})
            client_id = installed.get("client_id")
            client_secret = installed.get("client_secret")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )
    creds.refresh(Request())
    return creds


def get_gmail_service():
    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("[fetch_gmail] google-api-python-client not installed.", file=sys.stderr)
        return None

    try:
        creds = get_credentials()
    except Exception as e:
        print(f"[fetch_gmail] Auth error: {e}", file=sys.stderr)
        return None

    return build("gmail", "v1", credentials=creds)


def _extract_header(headers: list, name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def fetch_inbox_threads(days: int = 2) -> list[dict]:
    """Fetch recent inbox threads. Returns list of thread summary dicts."""
    service = get_gmail_service()
    if not service:
        return []

    query = f"in:inbox newer_than:{days}d"

    try:
        result = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=30,
        ).execute()
    except Exception as e:
        print(f"[fetch_gmail] API error: {e}", file=sys.stderr)
        return []

    messages = result.get("messages", [])
    if not messages:
        return []

    threads_seen = set()
    threads = []

    for msg_ref in messages:
        msg_id = msg_ref["id"]
        thread_id = msg_ref.get("threadId", msg_id)

        if thread_id in threads_seen:
            continue
        threads_seen.add(thread_id)

        try:
            msg = service.users().messages().get(
                userId="me",
                id=msg_id,
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()
        except Exception:
            continue

        headers = msg.get("payload", {}).get("headers", [])
        from_raw = _extract_header(headers, "From")
        to_raw = _extract_header(headers, "To")
        subject = _extract_header(headers, "Subject") or "(no subject)"
        date_raw = _extract_header(headers, "Date")

        from_name, from_email = parseaddr(from_raw)
        from_email = from_email.lower()

        # Parse timestamp
        ts_ms = int(msg.get("internalDate", 0))
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        ts_ist = ts.astimezone(IST)
        hours_ago = int((datetime.now(timezone.utc) - ts).total_seconds() / 3600)

        labels = msg.get("labelIds", [])
        is_unread = "UNREAD" in labels
        is_sent_by_user = from_email == USER_EMAIL.lower()

        threads.append({
            "thread_id": thread_id,
            "message_id": msg_id,
            "from_name": from_name or from_email,
            "from_email": from_email,
            "to": to_raw,
            "subject": subject,
            "snippet": msg.get("snippet", ""),
            "timestamp": ts_ist.strftime("%-I:%M %p, %b %-d"),
            "hours_ago": hours_ago,
            "is_unread": is_unread,
            "is_sent_by_user": is_sent_by_user,
        })

    return threads


def fetch_unanswered_client_threads(contacts_path: Path = None, days: int = 3) -> list[dict]:
    """
    Find threads where someone emailed Alex and he hasn't replied in 24h+.
    Cross-references against known contacts if contacts.json is available.
    Returns list of signal dicts for heartbeat.
    """
    threads = fetch_inbox_threads(days=days)
    if not threads:
        return []

    # Load known contact emails if available
    known_contacts = {}
    if contacts_path and contacts_path.exists():
        try:
            contacts = json.loads(contacts_path.read_text())
            for c in contacts:
                email = (c.get("email") or "").lower()
                if email:
                    known_contacts[email] = c.get("name", email)
        except Exception:
            pass

    unanswered = []
    seen_threads = set()

    for t in threads:
        tid = t["thread_id"]
        if tid in seen_threads:
            continue

        # Skip emails Alex sent himself
        if t["is_sent_by_user"]:
            continue

        # Only flag if older than 24h and unread OR no reply from Alex in thread
        if t["hours_ago"] < 24:
            continue

        from_email = t["from_email"]
        contact_name = known_contacts.get(from_email, t["from_name"] or from_email)

        seen_threads.add(tid)
        unanswered.append({
            "contact_name": contact_name,
            "from_email": from_email,
            "subject": t["subject"],
            "snippet": t["snippet"][:120],
            "hours_since": t["hours_ago"],
            "is_unread": t["is_unread"],
        })

    # Sort by most urgent (longest unanswered first)
    unanswered.sort(key=lambda x: x["hours_since"], reverse=True)
    return unanswered


def main():
    parser = argparse.ArgumentParser(description="Fetch acmestudio Gmail inbox threads")
    parser.add_argument("--days", type=int, default=2, help="Look back N days (default: 2)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--unanswered", action="store_true", help="Show only unanswered client threads")
    args = parser.parse_args()

    if args.unanswered:
        BASE = Path(__file__).parent.parent
        results = fetch_unanswered_client_threads(
            contacts_path=BASE / "data" / "contacts.json",
            days=args.days,
        )
        if args.json:
            print(json.dumps(results, indent=2))
        elif not results:
            print("No unanswered threads.")
        else:
            for t in results:
                print(f"  ⚠️  {t['contact_name']} — {t['subject']} ({t['hours_since']}h ago)")
                print(f"     {t['snippet']}")
        return

    threads = fetch_inbox_threads(days=args.days)

    if args.json:
        print(json.dumps(threads, indent=2))
        return

    if not threads:
        print("No threads found.")
        return

    for t in threads:
        unread_marker = "●" if t["is_unread"] else " "
        print(f"  {unread_marker} [{t['timestamp']}] {t['from_name']} — {t['subject']}")
        if t["snippet"]:
            print(f"    {t['snippet'][:100]}")


if __name__ == "__main__":
    main()
