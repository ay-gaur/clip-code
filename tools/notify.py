#!/usr/bin/env python3
"""
notify.py — CLIP Telegram push notification primitive.

Sends proactive alerts to Alex's phone via Telegram Bot API.
Handles deduplication via data/push-log.json to prevent spam.

Usage:
  python3 tools/notify.py --test               # send "CLIP online" test message
  python3 tools/notify.py --test --urgent      # test with urgent flag (bypasses DND)

Called by:
  heartbeat.py         — when LLM synthesis fires (≥2 signals)
  heartbeat_email.py   — when unanswered client threads found
  calendar_watch.py    — 30 min before a meeting starts

Requires in .env:
  TELEGRAM_BOT_TOKEN  — from @BotFather on Telegram
  TELEGRAM_CHAT_ID    — your personal chat_id (get from /getUpdates)
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.credits import get_credits_line

BASE = Path(__file__).parent.parent
DATA = BASE / "data"
PUSH_LOG = DATA / "push-log.json"

# Cooldown windows per signal type (hours)
COOLDOWNS = {
    "heartbeat_digest": 6,
    "email_alert": 4,
    "meeting_prep": 24,   # dedup key includes event+date, so once per event per day
    "pipeline_alert": 12,
    "default": 6,
}

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


# ── Env loading ────────────────────────────────────────────────────────────────

def load_env():
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


# ── Dedup ──────────────────────────────────────────────────────────────────────

def _load_push_log() -> list:
    if not PUSH_LOG.exists():
        return []
    try:
        return json.loads(PUSH_LOG.read_text())
    except Exception:
        return []


def _save_push_log(entries: list) -> None:
    DATA.mkdir(exist_ok=True)
    # Keep last 200 entries
    PUSH_LOG.write_text(json.dumps(entries[-200:], indent=2))


def _already_sent(signal: str, key: str) -> bool:
    """Return True if this signal+key was sent within its cooldown window."""
    cooldown_h = COOLDOWNS.get(signal, COOLDOWNS["default"])
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_h)
    entries = _load_push_log()
    for e in entries:
        if e.get("signal") == signal and e.get("key") == key:
            try:
                sent_at = datetime.fromisoformat(e["sent_at"])
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)
                if sent_at > cutoff:
                    return True
            except Exception:
                continue
    return False


def _log_sent(signal: str, key: str) -> None:
    entries = _load_push_log()
    entries.append({
        "signal": signal,
        "key": key,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    })
    _save_push_log(entries)


# ── Core sender ────────────────────────────────────────────────────────────────

def send_telegram(message: str, urgency: str = "normal") -> bool:
    """
    Push a message to Alex's Telegram.

    urgency:
      "normal"  — standard notification
      "urgent"  — disable_notification=False, forces sound even in DND
      "silent"  — disable_notification=True, no sound (info only)

    Returns True on success.
    """
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        print("[notify] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — skipping push.", file=sys.stderr)
        return False

    disable_notification = (urgency == "silent")
    url = TELEGRAM_API.format(token=token)

    full_message = f"{message}\n\n{get_credits_line()}"

    payload = {
        "chat_id": chat_id,
        "text": full_message,
        "parse_mode": "Markdown",
        "disable_notification": disable_notification,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True
        print(f"[notify] Telegram API error {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
        return False
    except requests.exceptions.RequestException as e:
        print(f"[notify] Network error: {e}", file=sys.stderr)
        return False


# ── Formatted senders ──────────────────────────────────────────────────────────

def send_heartbeat_digest(signals: list, insight: str) -> bool:
    """
    Push heartbeat synthesis to Telegram. Deduped on insight content hash (6h window).
    signals: list of signal dicts from heartbeat.py (each has "label" and "summary")
    insight: LLM-generated synthesis string
    """
    # Dedup key: hash of the insight text (catches identical re-runs)
    key = hashlib.md5(insight.encode()).hexdigest()[:12]
    if _already_sent("heartbeat_digest", key):
        print("[notify] heartbeat_digest already sent recently — skipping.")
        return False

    signal_lines = "\n".join(f"• *{s['label']}:* {s['summary'][:120]}" for s in signals)
    message = (
        f"*CLIP — Heartbeat*\n\n"
        f"{signal_lines}\n\n"
        f"_{insight[:400]}_"
    )

    ok = send_telegram(message, urgency="normal")
    if ok:
        _log_sent("heartbeat_digest", key)
        print(f"[notify] Heartbeat digest pushed to Telegram.")
    return ok


def send_email_alert(subject: str, contact: str, hours_old: int, from_email: str = "") -> bool:
    """
    Push unanswered email alert. Deduped on contact+subject hash (4h window).
    """
    key = hashlib.md5(f"{contact}:{subject}".encode()).hexdigest()[:12]
    if _already_sent("email_alert", key):
        return False

    message = (
        f"*CLIP — Email*\n"
        f"{contact} hasn't replied in {hours_old}h\n"
        f"_{subject[:80]}_\n"
        f"→ Follow up or mark done"
    )

    ok = send_telegram(message, urgency="normal")
    if ok:
        _log_sent("email_alert", key)
        print(f"[notify] Email alert pushed for: {contact}")
    return ok


def send_meeting_prep(event_title: str, brief_summary: str, minutes_away: int) -> bool:
    """
    Push meeting prep alert 30min before a calendar event.
    Deduped once per event per day.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    key = hashlib.md5(f"{event_title}:{today}".encode()).hexdigest()[:12]
    if _already_sent("meeting_prep", key):
        return False

    message = (
        f"*CLIP — Meeting in {minutes_away}min*\n"
        f"_{event_title}_\n\n"
        f"{brief_summary[:300]}"
    )

    ok = send_telegram(message, urgency="urgent")
    if ok:
        _log_sent("meeting_prep", key)
        print(f"[notify] Meeting prep pushed for: {event_title}")
    return ok


def send_pipeline_alert(contact_name: str, company: str, days_stale: int, stage: str) -> bool:
    """
    Push pipeline staleness alert. Deduped on contact (12h window).
    """
    key = hashlib.md5(f"pipeline:{contact_name}".encode()).hexdigest()[:12]
    if _already_sent("pipeline_alert", key):
        return False

    message = (
        f"*CLIP — Pipeline*\n"
        f"{contact_name} ({company}) — {stage}, {days_stale}d no contact\n"
        f"→ One message today keeps the deal warm"
    )

    ok = send_telegram(message, urgency="normal")
    if ok:
        _log_sent("pipeline_alert", key)
        print(f"[notify] Pipeline alert pushed for: {contact_name}")
    return ok


# ── CLI ────────────────────────────────────────────────────────────────────────

def show_status():
    """Print last 20 push-log entries in human-readable form."""
    load_env()
    path = BASE / "data" / "push-log.json"
    if not path.exists():
        print("[notify] No pushes sent yet (data/push-log.json not found).")
        return
    try:
        log = json.loads(path.read_text())
    except Exception:
        print("[notify] Could not read push-log.json")
        return

    if not log:
        print("[notify] Push log is empty.")
        return

    # Sort by sent_at descending
    log_sorted = sorted(log, key=lambda x: x.get("sent_at", ""), reverse=True)
    print(f"{'Signal':<18} {'Key':<14} {'Sent At (UTC)'}")
    print("-" * 60)
    for entry in log_sorted[:20]:
        sig = entry.get("signal", "?")[:17]
        key = entry.get("key", "?")[:13]
        sent = entry.get("sent_at", "?")[:19]
        print(f"{sig:<18} {key:<14} {sent}")
    if len(log) > 20:
        print(f"... (+{len(log)-20} older entries)")


def main():
    parser = argparse.ArgumentParser(description="CLIP Telegram push notification tool")
    parser.add_argument("--test", action="store_true", help="Send a test message to verify connectivity")
    parser.add_argument("--urgent", action="store_true", help="Use urgent urgency (bypasses DND)")
    parser.add_argument("--status", action="store_true", help="Show last 20 push-log entries")
    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.test:
        load_env()
        urgency = "urgent" if args.urgent else "normal"
        ok = send_telegram(
            "*CLIP is online* ✓\nTelegram push is working.\n_Phase 4b — Jarvis mode active_",
            urgency=urgency,
        )
        if ok:
            print("[notify] Test message sent successfully.")
        else:
            print("[notify] Test failed — check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
