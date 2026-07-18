#!/usr/bin/env python3
"""
send_email.py — Send an email via Gmail API (OAuth2).

Used by the Telegram bot /ok handler when action type = send_email.
Sends from user@example.com via Gmail API (not SMTP).

Usage:
  python3 tools/send_email.py --to "someone@example.com" \
      --subject "Hello" --body "Message text" [--thread-id THREAD_ID]
"""

import argparse
import base64
import email.mime.text
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
TOKEN_FILE = Path.home() / ".google-mcp" / "tokens" / "acmestudio.json"
CREDENTIALS_FILE = Path.home() / ".google-mcp" / "credentials.json"
SENDER = "user@example.com"


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
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )
    creds.refresh(Request())
    return creds


def send_email(to: str, subject: str, body: str, thread_id: str = "", html: bool = False) -> str:
    """Send an email via Gmail API. Returns message ID on success."""
    from googleapiclient.discovery import build

    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    msg = email.mime.text.MIMEText(body, "html" if html else "plain")
    msg["to"] = to
    msg["from"] = SENDER
    msg["subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    payload = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id

    result = service.users().messages().send(userId="me", body=payload).execute()
    return result.get("id", "?")


def main():
    load_env()
    parser = argparse.ArgumentParser(description="Send email via Gmail API")
    parser.add_argument("--to", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--thread-id", default="", help="Optional Gmail thread ID for replies")
    args = parser.parse_args()

    try:
        msg_id = send_email(args.to, args.subject, args.body, args.thread_id)
        print(f"Email sent (id: {msg_id})")
        print(f"  To: {args.to}")
        print(f"  Subject: {args.subject}")
    except Exception as e:
        print(f"Error sending email: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
