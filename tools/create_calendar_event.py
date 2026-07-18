#!/usr/bin/env python3
"""
create_calendar_event.py — Create a Google Calendar event via OAuth2.

Uses the same auth pattern as fetch_calendar.py (tokens from ~/.google-mcp/).
Creates event on user@example.com's primary calendar.

Usage:
  python3 tools/create_calendar_event.py \
      --title "Call with Client" \
      --date 2026-03-27 \
      --time 15:00 \
      --duration 30 \
      [--description "Discuss phase 2 scope"]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

TOKEN_FILE = Path.home() / ".google-mcp" / "tokens" / "acmestudio.json"
CREDENTIALS_FILE = Path.home() / ".google-mcp" / "credentials.json"
IST = timezone(timedelta(hours=5, minutes=30))


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


def create_event(title: str, date: str, time: str, duration: int, description: str = "") -> str:
    """Create a calendar event. Returns the event ID."""
    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("[create_calendar_event] google-api-python-client not installed.", file=sys.stderr)
        sys.exit(1)

    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)

    # Parse start datetime in IST
    start_naive = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    start_ist = start_naive.replace(tzinfo=IST)
    end_ist = start_ist + timedelta(minutes=duration)

    event_body = {
        "summary": title,
        "start": {
            "dateTime": start_ist.isoformat(),
            "timeZone": "Asia/Kolkata",
        },
        "end": {
            "dateTime": end_ist.isoformat(),
            "timeZone": "Asia/Kolkata",
        },
    }
    if description:
        event_body["description"] = description

    event = service.events().insert(calendarId="primary", body=event_body).execute()
    return event.get("id", "?")


def main():
    load_env()

    parser = argparse.ArgumentParser(description="Create a Google Calendar event")
    parser.add_argument("--title", required=True, help="Event title")
    parser.add_argument("--date", required=True, help="Date in YYYY-MM-DD format")
    parser.add_argument("--time", required=True, help="Start time in HH:MM format (IST)")
    parser.add_argument("--duration", type=int, default=60, help="Duration in minutes (default: 60)")
    parser.add_argument("--description", default="", help="Event description (optional)")
    args = parser.parse_args()

    try:
        event_id = create_event(args.title, args.date, args.time, args.duration, args.description)
        print(f"Calendar event created (id: {event_id})")
        print(f"  Title: {args.title}")
        print(f"  Date: {args.date} at {args.time} IST ({args.duration} min)")
        if args.description:
            print(f"  Description: {args.description}")
    except Exception as e:
        print(f"Error creating event: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
