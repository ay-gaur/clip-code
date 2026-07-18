#!/usr/bin/env python3
"""
send_morning_brief.py — CLIP automated daily morning brief.

Runs every morning at 9am IST via cron.
Reads live data files + latest heartbeat insight, composes a tight HTML email,
and sends it to user@example.com via Gmail SMTP.

Usage:
  python3 tools/send_morning_brief.py          # full run + send
  python3 tools/send_morning_brief.py --dry-run  # print email body, no send
"""

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from tools.morning_brief import parse_tasks, parse_pipeline, parse_schedule, fetch_live_schedule
from tools.send_email import load_env, send_email as gmail_send_email

DATA = BASE / "data"
RECIPIENT = "user@example.com"


def read_heartbeat_signals() -> str:
    """Read the latest insight from data/ai-updates.md. Return empty string if nothing fresh."""
    path = DATA / "ai-updates.md"
    if not path.exists():
        return ""
    text = path.read_text().strip()
    if not text or "no signals detected" in text.lower():
        return ""
    # Extract the synthesis block
    lines = text.splitlines()
    signals = []
    synthesis = []
    in_synthesis = False
    for line in lines:
        if line.startswith("**Synthesis:**"):
            in_synthesis = True
        elif line.startswith("**") and ":**" in line and not in_synthesis:
            signals.append(line)
        elif in_synthesis and line.strip() and not line.startswith("---"):
            synthesis.append(line)
    result_parts = []
    if signals:
        result_parts.extend(signals)
    if synthesis:
        result_parts.append("")
        result_parts.extend(synthesis)
    return "\n".join(result_parts).strip()


def build_subject(tasks: dict, pipeline: dict, heartbeat: str) -> str:
    today = date.today().strftime("%a %b %-d")
    urgent_count = len(tasks["urgent"])
    week_count = len(tasks["week"])
    task_count = urgent_count + week_count
    signal_count = len([l for l in heartbeat.splitlines() if l.startswith("**") and ":" in l]) if heartbeat else 0

    parts = []
    if urgent_count:
        parts.append(f"{urgent_count} urgent")
    elif task_count:
        parts.append(f"{task_count} task{'s' if task_count != 1 else ''}")

    hot = pipeline["hot"]
    stale = pipeline["stale"]
    if hot:
        parts.append(f"{len(hot)} deal{'s' if len(hot) != 1 else ''} need action")
    elif stale:
        parts.append(f"{len(stale)} contact{'s' if len(stale) != 1 else ''} stale")

    if signal_count:
        parts.append(f"{signal_count} signal{'s' if signal_count != 1 else ''}")

    if not parts:
        parts.append("all clear")

    return f"CLIP · {today} — {' · '.join(parts)}"


def build_html(tasks: dict, pipeline: dict, schedule: dict, heartbeat: str) -> str:
    today = date.today()
    day_str = today.strftime("%A, %B %-d, %Y")

    # ── helpers ──────────────────────────────────────────────────────────────
    def pill(text: str, color: str) -> str:
        colors = {
            "red":    ("ffe0e0", "8b0000"),
            "yellow": ("fff3cd", "856404"),
            "green":  ("d4f5d4", "1a6e1a"),
            "grey":   ("f0f0f0", "555555"),
        }
        bg, fg = colors.get(color, colors["grey"])
        return f'<span style="display:inline-block;background:#{bg};color:#{fg};border-radius:3px;padding:1px 7px;font-size:11px;font-weight:600;">{text}</span>'

    def section(title: str, content: str) -> str:
        return f"""
<div style="margin-top:24px;">
  <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;border-bottom:1px solid #eee;padding-bottom:4px;margin-bottom:10px;">{title}</div>
  {content}
</div>"""

    def row(icon: str, text: str) -> str:
        return f'<div style="margin:5px 0;font-size:14px;">{icon} {text}</div>'

    # ── tasks section ─────────────────────────────────────────────────────────
    task_rows = []
    for t in tasks["urgent"]:
        task_rows.append(row("🔴", f"<strong>{t}</strong>"))
    for t in tasks["week"]:
        task_rows.append(row("🟡", t))
    if not task_rows:
        task_rows.append(row("✅", "Nothing urgent or due this week."))
    tasks_html = "\n".join(task_rows)

    # ── schedule section ──────────────────────────────────────────────────────
    sched_rows = []
    for m in schedule["meetings"]:
        sched_rows.append(row("📅", m))
    for f in schedule["focus"]:
        sched_rows.append(row("🎯", f))
    if sched_rows:
        schedule_block = section("Today's Schedule", "\n".join(sched_rows))
    else:
        schedule_block = ""

    # ── pipeline section ──────────────────────────────────────────────────────
    pip_rows = []
    for c in pipeline["hot"]:
        ds = f"{c['days_since']}d ago" if c["days_since"] is not None else "no contact yet"
        pip_rows.append(row("🔥", f"<strong>{c['name']}</strong> ({c['company']}) — {c['stage'].capitalize()} · last contact {ds}"))
    for c in pipeline["stale"]:
        pip_rows.append(row("⏰", f"{c['name']} ({c['company']}) — {c['stage'].capitalize()} · {c['days_since']}d stale"))
    for c in pipeline["follow_up"]:
        pip_rows.append(row("📭", f"{c['name']} ({c['company']}) — never contacted"))
    if not pip_rows:
        pip_rows.append(row("✅", "Pipeline looks healthy."))
    pipeline_html = "\n".join(pip_rows)

    # ── heartbeat section ─────────────────────────────────────────────────────
    if heartbeat:
        hb_lines = heartbeat.splitlines()
        hb_rows = []
        for line in hb_lines:
            if line.startswith("**") and ":" in line:
                # Bold signal line
                label, _, rest = line.partition(":**")
                label_clean = label.lstrip("*")
                hb_rows.append(f'<div style="margin:5px 0;font-size:14px;">⚡ <strong>{label_clean}:</strong> {rest.strip()}</div>')
            elif line.strip():
                hb_rows.append(f'<div style="margin:6px 0;font-size:13px;color:#444;font-style:italic;">{line}</div>')
        heartbeat_block = section("Heartbeat Signals", "\n".join(hb_rows))
    else:
        heartbeat_block = ""

    # ── top action ────────────────────────────────────────────────────────────
    top_action = None
    if tasks["urgent"]:
        top_action = f"Start with: {tasks['urgent'][0]}"
    elif pipeline["hot"]:
        c = pipeline["hot"][0]
        top_action = f"Follow up on {c['name']} ({c['company']}) — {c['stage'].capitalize()}"
    elif pipeline["stale"]:
        c = pipeline["stale"][0]
        top_action = f"Re-engage {c['name']} ({c['company']}) — {c['days_since']}d stale"
    elif pipeline["follow_up"]:
        c = pipeline["follow_up"][0]
        top_action = f"First contact: {c['name']} ({c['company']})"

    action_block = ""
    if top_action:
        action_block = f"""
<div style="margin-top:24px;background:#1a1a1a;color:#fff;border-radius:6px;padding:12px 16px;font-size:14px;">
  <strong>→ {top_action}</strong>
</div>"""

    # ── full HTML ─────────────────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#1a1a1a;line-height:1.5;">

<div style="font-size:20px;font-weight:700;border-bottom:3px solid #000;padding-bottom:8px;">CLIP Morning Brief</div>
<div style="font-size:13px;color:#888;margin-top:4px;margin-bottom:0;">{day_str}</div>

{schedule_block}
{section("Tasks", tasks_html)}
{section("Pipeline", pipeline_html)}
{heartbeat_block}
{action_block}

<div style="margin-top:32px;font-size:11px;color:#bbb;">
  Generated by CLIP OS · user@example.com<br>
  Reply or open Claude Code to act on anything above.
</div>
</body>
</html>"""


def build_telegram_brief(tasks: dict, pipeline: dict, schedule: dict, heartbeat: str) -> str:
    """Build a tight Telegram morning message with 3 actionable items."""
    today = date.today().strftime("%A, %b %-d")
    lines = [f"*Good morning — {today}*\n"]

    # Today's meetings
    if schedule.get("meetings"):
        lines.append("📅 *Today*")
        for m in schedule["meetings"][:2]:
            lines.append(f"  {m}")
        lines.append("")

    # Build top 3 actions
    actions = []

    # Urgent tasks first
    for t in tasks["urgent"][:2]:
        actions.append(f"🔴 {t}")

    # Hot pipeline deals
    for c in pipeline["hot"]:
        if len(actions) >= 3:
            break
        ds = f"{c['days_since']}d ago" if c.get("days_since") is not None else "no contact yet"
        actions.append(f"🔥 Follow up: *{c['name']}* ({c['company']}) — last contact {ds}")

    # Stale contacts
    for c in pipeline["stale"]:
        if len(actions) >= 3:
            break
        actions.append(f"⏰ Re-engage: *{c['name']}* ({c['company']}) — {c['days_since']}d stale")

    # This week tasks as fallback
    for t in tasks["week"]:
        if len(actions) >= 3:
            break
        actions.append(f"🟡 {t}")

    if actions:
        lines.append("*3 things today:*")
        for i, a in enumerate(actions[:3], 1):
            lines.append(f"{i}. {a}")
        lines.append("")

    # One-line heartbeat signal if fresh
    if heartbeat:
        hb_lines = [l for l in heartbeat.splitlines() if l.strip() and not l.startswith("**Synthesis")]
        if hb_lines:
            lines.append(f"⚡ _{hb_lines[0].strip().lstrip('*').strip()}_")

    lines.append("\n_Reply or use /tasks /pipeline /ok_")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="CLIP daily morning brief sender")
    parser.add_argument("--dry-run", action="store_true", help="Print output, don't send")
    args = parser.parse_args()

    load_env()

    tasks = parse_tasks(DATA / "tasks.md")
    pipeline = parse_pipeline(DATA / "pipeline.json")
    schedule = fetch_live_schedule() or parse_schedule(DATA / "schedule.md")
    heartbeat = read_heartbeat_signals()

    # 1. Send email brief
    subject = build_subject(tasks, pipeline, heartbeat)
    body = build_html(tasks, pipeline, schedule, heartbeat)

    if args.dry_run:
        print(f"Subject: {subject}")
        print("─" * 60)
        print(body)
        print("\n── Telegram push ──")
        print(build_telegram_brief(tasks, pipeline, schedule, heartbeat))
        return

    print(f"[morning-brief] Sending email: '{subject}' → {RECIPIENT}")
    try:
        msg_id = gmail_send_email(to=RECIPIENT, subject=subject, body=body, html=True)
        print(f"[morning-brief] Email sent (id: {msg_id}).")
    except Exception as e:
        print(f"[morning-brief] Email send failed: {e}", file=sys.stderr)

    # 2. Push Telegram brief with 3 actions
    try:
        from tools.notify import send_telegram
        tg_msg = build_telegram_brief(tasks, pipeline, schedule, heartbeat)
        send_telegram(tg_msg)
        print(f"[morning-brief] Telegram push sent.")
    except Exception as e:
        print(f"[morning-brief] Telegram push failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
