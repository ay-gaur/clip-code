#!/usr/bin/env python3
"""
send_weekly_brief.py — CLIP automated weekly full brief.

Runs every Monday at 9am IST via cron.
Generates a comprehensive business brief covering: pipeline, tasks, business status,
AI updates, opportunity ideas, and open loops. Sends to user@example.com.

Usage:
  python3 tools/send_weekly_brief.py            # full run + send
  python3 tools/send_weekly_brief.py --dry-run  # print, no send
"""

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from tools.morning_brief import parse_tasks, parse_pipeline, parse_schedule
from tools.send_digest import load_env, send_email

DATA = BASE / "data"
RECIPIENT = "user@example.com"


# ── Data readers ──────────────────────────────────────────────────────────────

def read_ai_updates() -> dict:
    """Parse data/ai-updates.md into signals + synthesis."""
    path = DATA / "ai-updates.md"
    if not path.exists():
        return {"signals": [], "synthesis": ""}
    text = path.read_text()
    signals = []
    synthesis_lines = []
    in_synthesis = False
    for line in text.splitlines():
        if line.startswith("**Synthesis:**"):
            in_synthesis = True
        elif line.startswith("**") and ":**" in line and not in_synthesis:
            signals.append(line)
        elif in_synthesis and line.strip() and not line.startswith("---") and not line.startswith("#"):
            synthesis_lines.append(line)
    return {"signals": signals, "synthesis": " ".join(synthesis_lines).strip()}


def read_opportunities(limit: int = 5) -> list:
    """Read top N opportunities from data/opportunities.json."""
    path = DATA / "opportunities.json"
    if not path.exists():
        return []
    try:
        ops = json.loads(path.read_text())
    except Exception:
        return []
    # Return first N with status=new, prefer ones with real product names
    new_ops = [o for o in ops if o.get("status") == "new" and len(o.get("product", "")) > 5]
    return new_ops[:limit]


def read_pipeline_full() -> list:
    """Read full pipeline contacts."""
    path = DATA / "pipeline.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def read_contacts() -> list:
    path = DATA / "contacts.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def read_subscriptions() -> list:
    path = DATA / "subscriptions.json"
    if not path.exists():
        return []
    try:
        subs = json.loads(path.read_text())
        today = date.today()
        due = []
        for s in subs:
            if s.get("status") != "active":
                continue
            nb = s.get("next_billing")
            if nb:
                try:
                    days = (date.fromisoformat(nb) - today).days
                    if 0 <= days <= 14:
                        due.append({**s, "days_until": days})
                except ValueError:
                    pass
        return due
    except Exception:
        return []


# ── HTML builders ─────────────────────────────────────────────────────────────

def section(title: str, body: str, accent: str = "#000") -> str:
    return f"""
<div style="margin-top:28px;">
  <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#777;
              border-bottom:2px solid {accent};padding-bottom:4px;margin-bottom:12px;">
    {title}
  </div>
  {body}
</div>"""


def pill(text: str, color: str) -> str:
    colors = {
        "red":    ("ffe0e0", "8b0000"),
        "yellow": ("fff3cd", "856404"),
        "green":  ("d4f5d4", "1a6e1a"),
        "blue":   ("dce8ff", "1a3a8b"),
        "purple": ("ede9ff", "4c1d95"),
        "grey":   ("f0f0f0", "555555"),
    }
    bg, fg = colors.get(color, colors["grey"])
    return (f'<span style="display:inline-block;background:#{bg};color:#{fg};'
            f'border-radius:3px;padding:2px 8px;font-size:11px;font-weight:600;">{text}</span>')


def row(icon: str, text: str, sub: str = "") -> str:
    sub_html = f'<div style="font-size:12px;color:#888;margin-top:1px;">{sub}</div>' if sub else ""
    return f'<div style="margin:7px 0;font-size:14px;">{icon} {text}{sub_html}</div>'


def callout(text: str, color: str = "#f0a500", bg: str = "#fffdf0") -> str:
    return (f'<div style="border-left:3px solid {color};background:{bg};'
            f'padding:10px 14px;border-radius:4px;font-size:13px;margin:10px 0;">'
            f'{text}</div>')


def build_html(
    tasks: dict,
    pipeline_parsed: dict,
    pipeline_full: list,
    schedule: dict,
    ai: dict,
    opportunities: list,
    subscriptions: list,
) -> str:
    today = date.today()
    day_str = today.strftime("%A, %B %-d, %Y")
    week_num = today.isocalendar()[1]

    # ── 1. Tasks ──────────────────────────────────────────────────────────────
    task_rows = []
    for t in tasks["urgent"]:
        task_rows.append(row("🔴", f"<strong>{t}</strong>"))
    for t in tasks["week"]:
        task_rows.append(row("🟡", t))
    for t in tasks["backlog"][:3]:
        task_rows.append(row("⚪", f'<span style="color:#888;">{t}</span>'))
    if not task_rows:
        task_rows.append(row("✅", "Task board is clear. Consider adding this week's priorities."))
    tasks_section = section("Tasks", "\n".join(task_rows))

    # ── 2. Pipeline ───────────────────────────────────────────────────────────
    pip_rows = []
    stage_order = {"negotiation": 0, "proposal": 1, "qualified": 2, "contacted": 3, "prospect": 4, "client": 5}
    sorted_pipeline = sorted(pipeline_full, key=lambda c: stage_order.get(c.get("stage", ""), 99))
    for c in sorted_pipeline:
        stage = c.get("stage", "?")
        name = c.get("name", "?")
        company = c.get("company", "?")
        last = c.get("last_contact")
        notes = c.get("notes", "")

        stage_color = {
            "client": "green", "proposal": "yellow", "negotiation": "red",
            "qualified": "blue", "contacted": "grey", "prospect": "grey"
        }.get(stage, "grey")

        last_str = ""
        if last:
            days = (today - date.fromisoformat(last)).days
            last_str = f"Last contact: {days}d ago"
        elif stage != "client":
            last_str = "Never contacted"

        sub = last_str
        if notes:
            sub += f" · {notes[:80]}{'...' if len(notes) > 80 else ''}" if last_str else notes[:80]

        icon = {"client": "💼", "proposal": "📄", "negotiation": "🤝", "qualified": "⭐"}.get(stage, "👤")
        pip_rows.append(row(icon, f"<strong>{name}</strong> / {company} {pill(stage.capitalize(), stage_color)}", sub))

    if not pip_rows:
        pip_rows.append(row("📭", "No contacts in pipeline yet."))
    pipeline_section = section("Pipeline", "\n".join(pip_rows))

    # ── 3. Business Status ────────────────────────────────────────────────────
    # Hardcoded known priorities from context/priorities.md
    biz_rows = [
        row("🌐", f"<strong>Agency Website</strong> {pill('Not Started', 'red')}",
            "Chris owns build · Alex owns brief + direction"),
        row("🏢", f"<strong>Business Registration</strong> {pill('Not Started', 'red')}",
            "March goal — confirm status or push to April"),
    ]
    biz_section = section("Business Status", "\n".join(biz_rows), accent="#6366f1")

    # ── 4. AI Updates / Heartbeat ─────────────────────────────────────────────
    ai_rows = []
    for sig in ai["signals"]:
        if sig.startswith("**") and ":**" in sig:
            label, _, rest = sig.partition(":**")
            label_clean = label.lstrip("*")
            ai_rows.append(f'<div style="margin:6px 0;font-size:14px;">⚡ <strong>{label_clean}:</strong> {rest.strip()}</div>')
    if ai["synthesis"]:
        ai_rows.append(f'<div style="margin:10px 0;font-size:13px;color:#444;font-style:italic;'
                       f'background:#f8f8f8;padding:10px;border-radius:4px;">{ai["synthesis"]}</div>')
    if not ai_rows:
        ai_rows.append(row("💤", "No signals detected in last heartbeat run."))
    if subscriptions:
        for s in subscriptions:
            name = s.get("name", "?")
            amt = s.get("amount") or s.get("amount_inr") or "?"
            currency = "$" if s.get("amount") else "₹"
            days_until = s.get("days_until", "?")
            ai_rows.append(row("💳", f"<strong>{name}</strong> renews in {days_until}d ({currency}{amt})"))
    ai_section = section("Heartbeat + AI Updates", "\n".join(ai_rows), accent="#f0a500")

    # ── 5. Opportunities ──────────────────────────────────────────────────────
    if opportunities:
        opp_rows = []
        for i, op in enumerate(opportunities[:5], 1):
            product = op.get("product", "Unknown")
            gap = op.get("india_gap", "")
            source = op.get("source", "")
            domain = source.split("/")[2] if source.startswith("http") else source
            opp_rows.append(
                f'<div style="margin:10px 0;padding:10px;background:#f5f5ff;border-radius:4px;border-left:3px solid #6366f1;">'
                f'<div style="font-size:13px;font-weight:600;">#{i} {product[:80]}</div>'
                f'<div style="font-size:12px;color:#666;margin-top:3px;">{gap}</div>'
                f'<div style="font-size:11px;color:#aaa;margin-top:2px;">Source: {domain}</div>'
                f'</div>'
            )
        opp_html = "\n".join(opp_rows)
        opp_html += f'<div style="font-size:12px;color:#aaa;margin-top:8px;">{len(opportunities)} opportunities in queue · run /opportunity-scan to refresh</div>'
        opp_section = section("West → India Opportunities", opp_html, accent="#6366f1")
    else:
        opp_section = section("West → India Opportunities",
                              callout("No opportunities scanned yet. Run /opportunity-scan to populate this section.", "#6366f1", "#f5f5ff"))

    # ── 6. Open Loops ─────────────────────────────────────────────────────────
    open_rows = [
        row("🗑️", "<strong>Lead pipeline cleanup</strong> — 58 leads are LinkedIn job listings (data entry roles). Are you pitching RPA to these companies? If not, kill the signal."),
        row("📅", "<strong>Business registration</strong> — March goal. Start process or formally push to April."),
        row("🌐", "<strong>Agency website brief</strong> — Give Chris a direction so he's unblocked."),
        row("📊", "<strong>Google Calendar integration</strong> — Connect Google Workspace MCP to auto-populate schedule.md. Currently manual."),
        row("🔍", "<strong>Lead signals</strong> — Replace job listing queries with real intent signals (hiring sprees, funding rounds, new CXO hires, etc.)."),
    ]
    if subscriptions:
        for s in subscriptions:
            open_rows.insert(0, row("💳", f"<strong>{s.get('name')} renewal</strong> — {s.get('days_until')}d away. Renew, pause, or switch?"))
    open_section = section("Open Loops — Decisions Needed", "\n".join(open_rows), accent="#e53e3e")

    # ── 7. Q1 Scorecard ───────────────────────────────────────────────────────
    days_left = (date(2026, 3, 31) - today).days
    scorecard_rows = [
        row("🏗️", f"Ship Trend Engine MVP — {pill('In progress', 'yellow')} · {days_left}d left"),
        row("🌐", f"Register business + website live — {pill('Not started', 'red')}"),
        row("🤝", f"Close automations deal OR land new client — {pill('Proposal out', 'blue')}"),
    ]
    scorecard_section = section(f"Q1 2026 Scorecard ({days_left}d left)", "\n".join(scorecard_rows), accent="#2a9d2a")

    # ── assemble ──────────────────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:620px;margin:0 auto;padding:24px;color:#1a1a1a;line-height:1.6;">

<div style="font-size:22px;font-weight:700;border-bottom:3px solid #000;padding-bottom:8px;">
  CLIP Weekly Brief
</div>
<div style="font-size:13px;color:#888;margin-top:4px;">
  {day_str} &nbsp;·&nbsp; Week {week_num}
</div>

{scorecard_section}
{biz_section}
{tasks_section}
{pipeline_section}
{ai_section}
{opp_section}
{open_section}

<div style="margin-top:36px;padding-top:16px;border-top:1px solid #eee;font-size:11px;color:#bbb;">
  Generated by CLIP OS · user@example.com<br>
  Daily brief arrives every morning at 9am IST. This full brief arrives every Monday.
</div>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="CLIP weekly full brief sender")
    parser.add_argument("--dry-run", action="store_true", help="Print HTML, don't send")
    args = parser.parse_args()

    load_env()

    tasks = parse_tasks(DATA / "tasks.md")
    pipeline_parsed = parse_pipeline(DATA / "pipeline.json")
    pipeline_full = read_pipeline_full()
    schedule = parse_schedule(DATA / "schedule.md")
    ai = read_ai_updates()
    opportunities = read_opportunities(limit=5)
    subscriptions = read_subscriptions()

    today = date.today()
    week_str = today.strftime("%b %-d")
    subject = f"CLIP Weekly · {week_str} — Business Brief"

    body = build_html(tasks, pipeline_parsed, pipeline_full, schedule, ai, opportunities, subscriptions)

    if args.dry_run:
        print(f"Subject: {subject}")
        print("─" * 60)
        print(body)
        return

    print(f"[weekly-brief] Sending: '{subject}' → {RECIPIENT}")
    ok = send_email(subject=subject, body=body, to=RECIPIENT, html=True)
    if ok:
        print(f"[weekly-brief] Sent successfully.")
    else:
        print(f"[weekly-brief] Send failed — check .env credentials.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
