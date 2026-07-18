#!/usr/bin/env python3
"""
morning_brief.py — Generate Alex's daily morning briefing.

Reads:
  data/tasks.md        — urgent + this week tasks
  data/pipeline.json   — follow-up needs, stale contacts
  data/schedule.md     — today's meetings and focus blocks

Output: structured text briefing to stdout
"""

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).parent.parent / "data"
STALE_DAYS = 3  # contacts not touched in 3+ days flagged for follow-up


def fetch_live_schedule() -> dict:
    """Fetch today's events from Google Calendar API. Falls back to schedule.md."""
    try:
        tools_dir = Path(__file__).parent
        sys.path.insert(0, str(tools_dir.parent))
        from tools.fetch_calendar import fetch_events, format_events
        events = fetch_events(days=1)
        lines = format_events(events)
        return {"meetings": lines, "focus": []}
    except Exception:
        return None


def parse_tasks(path: Path) -> dict:
    if not path.exists():
        return {"urgent": [], "week": [], "backlog": []}
    text = path.read_text()
    sections = {"urgent": [], "week": [], "backlog": []}
    current = None
    for line in text.splitlines():
        lower = line.lower().strip()
        if lower.startswith("## urgent"):
            current = "urgent"
        elif lower.startswith("## this week"):
            current = "week"
        elif lower.startswith("## backlog"):
            current = "backlog"
        elif line.strip().startswith("- ") and current:
            sections[current].append(line.strip()[2:].strip())
    return sections


def parse_pipeline(path: Path) -> dict:
    if not path.exists():
        return {"follow_up": [], "hot": [], "stale": []}
    contacts = json.loads(path.read_text())
    today = date.today()
    follow_up = []
    hot = []
    stale = []

    for c in contacts:
        stage = c.get("stage", "")
        last = c.get("last_contact")
        name = c.get("name", "?")
        company = c.get("company", "?")
        value = c.get("value", 0)

        # Hot: proposal or negotiation — these need attention
        if stage in ("proposal", "negotiation"):
            days_since = None
            if last:
                days_since = (today - date.fromisoformat(last)).days
            hot.append({
                "name": name,
                "company": company,
                "stage": stage,
                "value": value,
                "days_since": days_since,
            })

        # Stale: active (non-client, non-hot) contacts not touched in STALE_DAYS+
        if stage not in ("client", "proposal", "negotiation") and last:
            days = (today - date.fromisoformat(last)).days
            if days >= STALE_DAYS:
                stale.append({
                    "name": name,
                    "company": company,
                    "stage": stage,
                    "days_since": days,
                })
        elif stage not in ("client", "proposal", "negotiation") and not last:
            # Never contacted — flag it
            follow_up.append({
                "name": name,
                "company": company,
                "stage": stage,
                "note": "never contacted",
            })

    return {"follow_up": follow_up, "hot": hot, "stale": stale}


def parse_schedule(path: Path) -> dict:
    if not path.exists():
        return {"meetings": [], "focus": []}
    text = path.read_text()
    result = {"meetings": [], "focus": []}
    current = None
    for line in text.splitlines():
        lower = line.lower().strip()
        if "## meeting" in lower:
            current = "meetings"
        elif "## focus" in lower:
            current = "focus"
        elif line.strip().startswith("- ") and current:
            item = line.strip()[2:].strip()
            if item.lower() not in ("none scheduled", "none"):
                result[current].append(item)
        elif line.strip().startswith("_") and current:
            # italicized placeholders like _none scheduled_
            pass
    return result


def render_brief(tasks: dict, pipeline: dict, schedule: dict) -> str:
    today_str = date.today().strftime("%A, %B %d")
    lines = [f"# Morning Brief — {today_str}", ""]

    # --- SCHEDULE ---
    has_meetings = bool(schedule["meetings"])
    has_focus = bool(schedule["focus"])
    if has_meetings or has_focus:
        lines.append("## Today")
        if has_meetings:
            for m in schedule["meetings"]:
                lines.append(f"  📅 {m}")
        if has_focus:
            for f in schedule["focus"]:
                lines.append(f"  🎯 {f}")
        lines.append("")
    else:
        lines.append("## Today")
        lines.append("  No meetings or focus blocks scheduled.")
        lines.append("")

    # --- TASKS ---
    has_urgent = bool(tasks["urgent"])
    has_week = bool(tasks["week"])

    lines.append("## Tasks")
    if has_urgent:
        lines.append("  🔴 Urgent")
        for t in tasks["urgent"]:
            lines.append(f"    • {t}")
    if has_week:
        lines.append("  🟡 This Week")
        for t in tasks["week"]:
            lines.append(f"    • {t}")
    if not has_urgent and not has_week:
        lines.append("  ✅ Nothing urgent or due this week.")
    lines.append("")

    # --- PIPELINE ---
    lines.append("## Pipeline")
    hot = pipeline["hot"]
    stale = pipeline["stale"]
    follow_up = pipeline["follow_up"]

    if hot:
        lines.append("  🔥 Needs action")
        for c in hot:
            ds = f"{c['days_since']}d ago" if c["days_since"] is not None else "no contact yet"
            lines.append(f"    • {c['name']} ({c['company']}) — {c['stage'].capitalize()}, ₹{c['value']:,} — last contact {ds}")

    if stale:
        lines.append("  ⏰ Going stale")
        for c in stale:
            lines.append(f"    • {c['name']} ({c['company']}) — {c['stage'].capitalize()}, {c['days_since']}d since last contact")

    if follow_up:
        lines.append("  📭 Never contacted")
        for c in follow_up:
            lines.append(f"    • {c['name']} ({c['company']}) — {c['stage'].capitalize()}")

    if not hot and not stale and not follow_up:
        lines.append("  ✅ Pipeline looks healthy.")

    lines.append("")

    # --- FOCUS SUGGESTION ---
    top_action = None
    if tasks["urgent"]:
        top_action = f"Start with: {tasks['urgent'][0]}"
    elif hot:
        top_action = f"Follow up on {hot[0]['name']} ({hot[0]['company']}) — {hot[0]['stage']}"
    elif stale:
        top_action = f"Re-engage {stale[0]['name']} ({stale[0]['company']}) — {stale[0]['days_since']}d stale"

    if top_action:
        lines.append(f"**→ {top_action}**")
        lines.append("")

    return "\n".join(lines)


def main():
    tasks = parse_tasks(BASE / "tasks.md")
    pipeline = parse_pipeline(BASE / "pipeline.json")
    schedule = fetch_live_schedule() or parse_schedule(BASE / "schedule.md")
    brief = render_brief(tasks, pipeline, schedule)
    print(brief)


if __name__ == "__main__":
    main()
