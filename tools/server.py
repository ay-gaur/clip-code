#!/usr/bin/env python3
"""
server.py — CLIP OS entry point for Railway.

Runs two things in parallel:
  1. APScheduler — all background jobs (heartbeat, briefs)
  2. Telegram bot — always-on long-polling in the main thread

Usage:
  python3 tools/server.py

All jobs use IST (Asia/Kolkata = UTC+5:30).
"""

import os
import sys
import threading
import subprocess
import logging
from pathlib import Path
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# ── Setup ─────────────────────────────────────────────────────────────────────

BASE = Path(__file__).parent.parent
IST = pytz.timezone("Asia/Kolkata")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [server] %(message)s",
    datefmt="%Y-%m-%d %H:%M IST",
)
log = logging.getLogger(__name__)

# ── Google token bootstrap ─────────────────────────────────────────────────────

def bootstrap_google_token():
    """Write Google OAuth token from env var to disk on startup."""
    import base64, json
    token_b64 = os.environ.get("GOOGLE_TOKEN_B64")
    if not token_b64:
        log.warning("GOOGLE_TOKEN_B64 not set — Gmail/Calendar features disabled")
        return
    try:
        token_data = base64.b64decode(token_b64).decode("utf-8")
        token_dir = Path.home() / ".google-mcp" / "tokens"
        token_dir.mkdir(parents=True, exist_ok=True)
        token_path = token_dir / "acmestudio.json"
        token_path.write_text(token_data)
        log.info(f"Google token written to {token_path}")
    except Exception as e:
        log.error(f"Failed to bootstrap Google token: {e}")

# ── Job runners ───────────────────────────────────────────────────────────────

def run_script(label: str, *cmd):
    """Run a Python script, log stdout/stderr, send Telegram alert on failure."""
    log.info(f"[{label}] starting")
    result = subprocess.run(
        cmd,
        cwd=str(BASE),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(BASE)},
    )
    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            log.info(f"[{label}] {line}")
    if result.returncode != 0:
        err = result.stderr.strip() or "no stderr"
        log.error(f"[{label}] FAILED (exit {result.returncode}): {err}")
        _telegram_alert(f"CLIP cron FAILED: {label}\n{err[:1500]}")
    else:
        log.info(f"[{label}] done")

_last_alert_time: float = 0
_ALERT_COOLDOWN_SECS = 300  # max 1 alert per 5 minutes

def _telegram_alert(message: str):
    """Send a failure alert to Telegram (rate-limited to 1 per 5 min)."""
    global _last_alert_time
    import time as _time
    now = _time.time()
    if now - _last_alert_time < _ALERT_COOLDOWN_SECS:
        log.warning(f"[telegram_alert] Suppressed (cooldown): {message[:80]}")
        return
    _last_alert_time = now
    try:
        import requests
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            return
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": f"⚠️ {message}"},
            timeout=10,
        )
    except Exception as e:
        log.error(f"[telegram_alert] Failed to send alert: {e}")

# ── Scheduled jobs ────────────────────────────────────────────────────────────

def job_heartbeat():
    run_script("heartbeat", sys.executable, "tools/heartbeat.py")

def job_morning_brief():
    run_script("morning_brief", sys.executable, "tools/send_morning_brief.py")

def job_lead_reminder():
    run_script("lead_reminder", sys.executable, "tools/lead_reminder.py")

def job_weekly_brief():
    run_script("weekly_brief", sys.executable, "tools/send_weekly_brief.py")

def job_data_sync():
    """Push data/ to git."""
    result = subprocess.run(
        "git add data/ && git diff --cached --quiet || "
        "(git commit -m 'auto: sync data' && git push)",
        shell=True, cwd=str(BASE), capture_output=True, text=True,
    )
    if result.returncode == 0:
        log.info("[data_sync] done")
    else:
        log.error(f"[data_sync] failed: {result.stderr.strip()}")

def job_weekly_feedback():
    if Path(BASE / "tools" / "weekly_feedback.py").exists():
        run_script("weekly_feedback", sys.executable, "tools/weekly_feedback.py")

def job_email_watch():
    run_script("heartbeat_email", sys.executable, "tools/heartbeat_email.py")

def job_email_monitor():
    run_script("email_monitor", sys.executable, "tools/email_monitor.py")

def job_reddit_intel():
    run_script("reddit_intel", sys.executable, "tools/reddit_intel.py")

def job_content_draft():
    run_script("content_draft", sys.executable, "tools/content_draft.py")

# ── Scheduler setup ───────────────────────────────────────────────────────────

def start_scheduler():
    scheduler = BackgroundScheduler(timezone=IST)

    # Heartbeat — every 6 hours
    scheduler.add_job(job_heartbeat, CronTrigger(hour="5,11,17,23", minute=30, timezone=IST))

    # Morning brief — daily 9:00am IST
    scheduler.add_job(job_morning_brief, CronTrigger(hour=9, minute=0, timezone=IST))

    # CRM lead follow-up reminder — daily 8:30am IST (just before the morning brief)
    scheduler.add_job(job_lead_reminder, CronTrigger(hour=8, minute=30, timezone=IST))

    # Weekly full brief — Monday 9:00am IST
    scheduler.add_job(job_weekly_brief, CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=IST))

    # Weekly feedback — Monday 9:30am IST
    scheduler.add_job(job_weekly_feedback, CronTrigger(day_of_week="mon", hour=9, minute=30, timezone=IST))

    # Data sync — every 1 hour
    scheduler.add_job(job_data_sync, CronTrigger(minute=0, timezone=IST))

    # Email watch (stale thread alerts) — every 6 hours
    scheduler.add_job(job_email_watch, CronTrigger(hour="3,9,15,21", minute=0, timezone=IST))

    # Email monitor (new inbound classifier + reply draft) — every 30 minutes
    scheduler.add_job(job_email_monitor, CronTrigger(minute="15,45", timezone=IST))

    # Reddit intel — Monday 8:00am IST
    scheduler.add_job(job_reddit_intel, CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=IST))

    # LinkedIn content drafts — Monday 8:30am IST (after reddit intel)
    scheduler.add_job(job_content_draft, CronTrigger(day_of_week="mon", hour=8, minute=30, timezone=IST))

    scheduler.start()
    log.info("Scheduler started. Jobs:")
    for job in scheduler.get_jobs():
        log.info(f"  {job.id}: next run {job.next_run_time}")
    return scheduler

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info(f"CLIP OS server starting — {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}")

    # 1. Bootstrap Google token from env
    bootstrap_google_token()

    # 2. Start APScheduler in background thread
    scheduler = start_scheduler()

    # 3. Run Telegram bot in main thread (blocks)
    log.info("Starting Telegram bot...")
    try:
        # Import and run bot directly (avoids subprocess overhead)
        sys.path.insert(0, str(BASE))
        bot_path = BASE / "bot" / "telegram_bot_server.py"
        exec(open(bot_path).read(), {"__file__": str(bot_path), "__name__": "__main__"})
    except KeyboardInterrupt:
        log.info("Shutting down...")
    except Exception as e:
        log.error(f"Bot crashed: {e}", exc_info=True)
        _telegram_alert(f"CLIP bot crashed: {e}")
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
