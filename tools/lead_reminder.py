#!/usr/bin/env python3
"""
lead_reminder.py — daily CRM follow-up nudge.

Queries Supabase for leads whose next_followup is due today or overdue (and not
won/lost/archived), groups them by source, and pushes a Markdown summary to Alex's
Telegram via the existing notify.send_telegram. Wired into server.py's APScheduler
to run each morning (8:30 IST). Skips silently when nothing is due.

Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (same as crm_import.py).
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import pytz
import requests

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
from tools.utils.llm_rest import load_env
from tools.notify import send_telegram

IST = pytz.timezone("Asia/Kolkata")
SOURCE_LABEL = {"interior": "Interior designers", "service": "Service businesses", "d2c": "D2C (archived)"}


def fetch_due(base, key, today):
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    params = (
        f"?select=business_name,source,next_followup,phone,linkedin,stage"
        f"&next_followup=lte.{today}"
        f"&stage=not.in.(won,lost,not_now)"
        f"&order=source,next_followup"
    )
    r = requests.get(f"{base}/rest/v1/leads{params}", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def days_overdue(next_followup, today):
    try:
        d = (datetime.strptime(today, "%Y-%m-%d").date()
             - datetime.strptime(next_followup, "%Y-%m-%d").date()).days
    except Exception:
        return 0
    return d


def build_message(rows, today):
    total = len(rows)
    lines = [f"*CRM — Follow-ups due today ({total})*", ""]
    by_source = {}
    for r in rows:
        by_source.setdefault(r["source"], []).append(r)
    for source in ("interior", "service", "d2c"):
        group = by_source.get(source)
        if not group:
            continue
        lines.append(f"*{SOURCE_LABEL.get(source, source)} ({len(group)})*")
        for r in group[:15]:
            od = days_overdue(r.get("next_followup", ""), today)
            when = "due today" if od == 0 else (f"overdue {od}d" if od > 0 else "")
            contact = ""
            if r.get("phone"):
                contact = f"  📞 {r['phone']}"
            elif r.get("linkedin"):
                contact = "  🔗 linkedin"
            lines.append(f"• {r['business_name']} — {when}{contact}")
        if len(group) > 15:
            lines.append(f"  …and {len(group) - 15} more")
        lines.append("")
    return "\n".join(lines).strip()


def main():
    load_env()
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not base or not key:
        print("[lead_reminder] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — skipping.", file=sys.stderr)
        return
    today = datetime.now(IST).strftime("%Y-%m-%d")
    try:
        rows = fetch_due(base, key, today)
    except Exception as e:
        print(f"[lead_reminder] query failed: {e}", file=sys.stderr)
        sys.exit(1)
    if not rows:
        print("[lead_reminder] no follow-ups due today — skipping push.")
        return
    msg = build_message(rows, today)
    ok = send_telegram(msg, urgency="normal")
    print(f"[lead_reminder] pushed {len(rows)} due follow-ups (telegram ok={ok})")


if __name__ == "__main__":
    main()
