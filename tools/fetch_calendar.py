#!/usr/bin/env python3
"""
fetch_calendar.py — Fetch today's Google Calendar events for user@example.com.

Reads OAuth tokens from ~/.google-mcp/tokens/acmestudio.json and calls
Google Calendar API directly. Used by morning_brief.py and send_morning_brief.py.

Usage:
  python3 tools/fetch_calendar.py              # prints today's events
  python3 tools/fetch_calendar.py --days 3     # prints next 3 days of events
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


def get_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    # Try env vars first (Railway / cloud deployment)
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


def fetch_events(days: int = 1) -> list[dict]:
    """Fetch calendar events for the next `days` days. Returns list of event dicts."""
    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("[fetch_calendar] google-api-python-client not installed.", file=sys.stderr)
        return []

    try:
        creds = get_credentials()
    except Exception as e:
        print(f"[fetch_calendar] Auth error: {e}", file=sys.stderr)
        return []

    service = build("calendar", "v3", credentials=creds)

    now_ist = datetime.now(IST)
    start_of_day = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_range = start_of_day + timedelta(days=days)

    time_min = start_of_day.isoformat()
    time_max = end_of_range.isoformat()

    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=20,
        )
        .execute()
    )

    events = []
    for item in result.get("items", []):
        start = item.get("start", {})
        end = item.get("end", {})

        # Parse start time
        start_dt = start.get("dateTime") or start.get("date")
        end_dt = end.get("dateTime") or end.get("date")
        all_day = "date" in start and "dateTime" not in start

        time_str = "All day"
        if not all_day and start_dt:
            try:
                dt = datetime.fromisoformat(start_dt)
                dt_ist = dt.astimezone(IST)
                time_str = dt_ist.strftime("%-I:%M %p")
            except Exception:
                time_str = start_dt

        events.append(
            {
                "title": item.get("summary", "Untitled"),
                "time": time_str,
                "all_day": all_day,
                "location": item.get("location", ""),
                "description": item.get("description", "")[:100] if item.get("description") else "",
                "attendees": len(item.get("attendees", [])),
                "meet_link": item.get("hangoutLink", ""),
                "start_iso": start_dt,
            }
        )

    return events


def format_events(events: list[dict]) -> list[str]:
    """Format events into display strings for the morning brief."""
    lines = []
    for e in events:
        time_prefix = "All day" if e["all_day"] else e["time"]
        line = f"{time_prefix} — {e['title']}"
        if e["location"]:
            line += f" @ {e['location']}"
        elif e["meet_link"]:
            line += " (Google Meet)"
        if e["attendees"] > 1:
            line += f" · {e['attendees']} attendees"
        lines.append(line)
    return lines


def main():
    parser = argparse.ArgumentParser(description="Fetch today's Google Calendar events")
    parser.add_argument("--days", type=int, default=1, help="Number of days ahead to fetch (default: 1)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    events = fetch_events(days=args.days)

    if args.json:
        print(json.dumps(events, indent=2))
        return

    if not events:
        print("No events today.")
        return

    for line in format_events(events):
        print(f"  📅 {line}")


if __name__ == "__main__":
    main()
