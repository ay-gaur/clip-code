#!/usr/bin/env python3
"""
create_gmail_draft.py — Create a Gmail draft via Google API (OAuth2).

Uses the same auth pattern as fetch_calendar.py (tokens from ~/.google-mcp/).
Draft appears in user@example.com's Gmail drafts — Alex reviews before sending.

Usage:
  python3 tools/create_gmail_draft.py \
      --to "contact@example.com" \
      --subject "Following up" \
      --body "Hi, ..."
"""

import argparse
import base64
import email.mime.text
import json
import os
import sys
from pathlib import Path

TOKEN_FILE = Path.home() / ".google-mcp" / "tokens" / "acmestudio.json"
CREDENTIALS_FILE = Path.home() / ".google-mcp" / "credentials.json"
SENDER = "user@example.com"


def load_env():
    env_path = Path(__file__).parent.parent / ".env"
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


def create_draft(to: str, subject: str, body: str) -> str:
    """Create a Gmail draft. Returns the draft ID on success."""
    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("[create_gmail_draft] google-api-python-client not installed.", file=sys.stderr)
        sys.exit(1)

    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    # Build the MIME message
    msg = email.mime.text.MIMEText(body, "plain")
    msg["to"] = to
    msg["from"] = SENDER
    msg["subject"] = subject

    # Encode as base64url
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    draft = service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}},
    ).execute()

    return draft.get("id", "?")


def main():
    load_env()

    parser = argparse.ArgumentParser(description="Create a Gmail draft")
    parser.add_argument("--to", required=True, help="Recipient email address")
    parser.add_argument("--subject", required=True, help="Email subject")
    parser.add_argument("--body", required=True, help="Email body (plain text)")
    args = parser.parse_args()

    try:
        draft_id = create_draft(args.to, args.subject, args.body)
        print(f"Gmail draft created (id: {draft_id})")
        print(f"  To: {args.to}")
        print(f"  Subject: {args.subject}")
        print(f"  → Open Gmail to review and send.")
    except Exception as e:
        print(f"Error creating draft: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
