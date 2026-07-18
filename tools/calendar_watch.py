#!/usr/bin/env python3
"""
calendar_watch.py — CLIP 30-minute calendar meeting prep watcher.

Checks today's calendar events. If any event starts in 25–35 minutes,
pushes a meeting prep brief to Telegram. Deduped once per event per day.

Runs every 30 min via cron. Auto-triggered prep — no manual /prep-meeting needed.

Usage:
  python3 tools/calendar_watch.py             # full run
  python3 tools/calendar_watch.py --dry-run   # print upcoming events, no push

Requires in .env:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  Google OAuth tokens at ~/.google-mcp/tokens/acmestudio.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
DATA = BASE / "data"
sys.path.insert(0, str(BASE))

IST = timezone(timedelta(hours=5, minutes=30))

# Fire prep brief if event starts within this window (minutes)
TRIGGER_WINDOW_MIN = 25
TRIGGER_WINDOW_MAX = 35


def load_env():
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def minutes_until(start_iso: str) -> int | None:
    """Return minutes until a calendar event starts. None if unparseable."""
    if not start_iso:
        return None
    try:
        dt = datetime.fromisoformat(start_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        now = datetime.now(timezone.utc)
        delta = (dt.astimezone(timezone.utc) - now).total_seconds() / 60
        return int(delta)
    except Exception:
        return None


def find_contact_for_event(event_title: str, contacts: list) -> dict | None:
    """Fuzzy-match event title against known contact names."""
    title_lower = event_title.lower()
    for c in contacts:
        name = c.get("name", "").lower()
        company = c.get("company", "").lower()
        if name and name in title_lower:
            return c
        if company and company in title_lower:
            return c
    return None


def build_compact_brief(contact: dict, pipeline: list) -> str:
    """Build a compact prep summary for Telegram (under 300 chars)."""
    from tools.prep_meeting import find_in_pipeline, build_brief

    pipeline_record = find_in_pipeline(
        contact.get("name", ""),
        contact.get("company", ""),
        pipeline,
    )
    full_brief = build_brief(contact, pipeline_record)

    # Extract just the key sections for Telegram
    lines = []
    in_section = False
    for line in full_brief.splitlines():
        if line.startswith("## Open Items") or line.startswith("## Pipeline"):
            in_section = True
            lines.append(line.replace("## ", "*") + "*")
        elif line.startswith("## Suggested Talking"):
            in_section = True
            lines.append("*Talking Points*")
        elif line.startswith("## "):
            in_section = False
        elif in_section and line.strip():
            lines.append(line.strip())
        if len("\n".join(lines)) > 400:
            break

    return "\n".join(lines) if lines else f"No notes on {contact.get('name', 'this contact')} yet."


def main():
    parser = argparse.ArgumentParser(description="CLIP 30-min calendar meeting prep watcher")
    parser.add_argument("--dry-run", action="store_true", help="Print upcoming events, no push")
    args = parser.parse_args()

    load_env()
    print(f"[cal-watch] Running — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Fetch today's events
    try:
        from tools.fetch_calendar import fetch_events
        events = fetch_events(days=1)
    except Exception as e:
        print(f"[cal-watch] Calendar fetch failed: {e}", file=sys.stderr)
        return

    if not events:
        print("[cal-watch] No events today.")
        return

    # Load contacts + pipeline for prep brief
    contacts = []
    pipeline = []
    contacts_path = DATA / "contacts.json"
    pipeline_path = DATA / "pipeline.json"

    if contacts_path.exists():
        try:
            contacts = json.loads(contacts_path.read_text())
        except Exception:
            pass

    if pipeline_path.exists():
        try:
            pipeline = json.loads(pipeline_path.read_text())
        except Exception:
            pass

    # Check each event for the trigger window
    triggered = []
    for event in events:
        if event.get("all_day"):
            continue

        mins = minutes_until(event.get("start_iso"))
        if mins is None:
            continue

        print(f"[cal-watch] '{event['title']}' starts in {mins}min")

        if TRIGGER_WINDOW_MIN <= mins <= TRIGGER_WINDOW_MAX:
            triggered.append((event, mins))

    if not triggered:
        print("[cal-watch] No events in prep window.")
        return

    if args.dry_run:
        print(f"[cal-watch] Dry run — {len(triggered)} event(s) in window, no push.")
        return

    from tools.notify import send_meeting_prep

    for event, mins in triggered:
        title = event["title"]
        contact = find_contact_for_event(title, contacts)

        if contact:
            brief = build_compact_brief(contact, pipeline)
        else:
            meet_info = " (Google Meet)" if event.get("meet_link") else ""
            brief = f"No contact notes found.\n{event.get('description', '')}".strip() or f"Meeting{meet_info}"

        send_meeting_prep(
            event_title=title,
            brief_summary=brief,
            minutes_away=mins,
        )


if __name__ == "__main__":
    main()
