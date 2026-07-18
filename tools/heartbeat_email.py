#!/usr/bin/env python3
"""
heartbeat_email.py — CLIP 30-minute email signal watcher.

Lightweight email-only heartbeat. Checks for unanswered client threads
and pushes a Telegram alert if any are older than 24h. No LLM call.

Runs every 30 min via cron. One job, one signal, no noise.

Usage:
  python3 tools/heartbeat_email.py             # full run
  python3 tools/heartbeat_email.py --dry-run   # print threads, no push

Requires in .env:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  Google OAuth tokens at ~/.google-mcp/tokens/acmestudio.json
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
DATA = BASE / "data"
sys.path.insert(0, str(BASE))


def load_env():
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def main():
    parser = argparse.ArgumentParser(description="CLIP 30-min email heartbeat")
    parser.add_argument("--dry-run", action="store_true", help="Print threads, no Telegram push")
    args = parser.parse_args()

    load_env()
    print(f"[email-watch] Running — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Fetch unanswered threads
    try:
        from tools.fetch_gmail import fetch_unanswered_client_threads
        threads = fetch_unanswered_client_threads(
            contacts_path=DATA / "contacts.json",
            days=3,
        )
    except Exception as e:
        print(f"[email-watch] Gmail fetch failed: {e}", file=sys.stderr)
        return

    if not threads:
        print("[email-watch] No unanswered threads. All clear.")
        return

    print(f"[email-watch] {len(threads)} unanswered thread(s):")
    for t in threads:
        print(f"  • {t['contact_name']} ({t['hours_since']}h): {t['subject'][:60]}")

    if args.dry_run:
        print("[email-watch] Dry run — skipping Telegram push.")
        return

    # Push the most urgent thread (longest unanswered)
    # threads are already sorted by hours_since desc
    from tools.notify import send_email_alert

    top = threads[0]
    sent = send_email_alert(
        subject=top["subject"],
        contact=top["contact_name"],
        hours_old=top["hours_since"],
        from_email=top["from_email"],
    )

    # If there are more, push a summary line appended to the same message
    if not sent:
        print("[email-watch] Push skipped (dedup or error).")
    elif len(threads) > 1:
        # Additional threads — push a quiet summary
        from tools.notify import send_telegram
        extras = threads[1:3]
        extra_lines = "\n".join(
            f"• {t['contact_name']} ({t['hours_since']}h): _{t['subject'][:50]}_"
            for t in extras
        )
        suffix = f" (+{len(threads) - 3} more)" if len(threads) > 3 else ""
        send_telegram(
            f"*CLIP — {len(threads) - 1} more unanswered*\n{extra_lines}{suffix}",
            urgency="silent",
        )


if __name__ == "__main__":
    main()
