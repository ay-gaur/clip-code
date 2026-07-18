#!/usr/bin/env python3
"""
send_digest.py — Shared email sender for CLIP scheduled tools.

Uses Gmail SMTP with an App Password (not OAuth).
Requires in .env:
  GMAIL_FROM=user@example.com
  GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx  (16-char Google App Password)

Usage (as a library):
  from tools.send_digest import send_email
  send_email(subject="Lead Scan", body="...")

Usage (CLI):
  python3 tools/send_digest.py --subject "Test" --body "Hello"
"""

import argparse
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Load .env manually (no dependency on python-dotenv)
def load_env():
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

load_env()

GMAIL_FROM = os.environ.get("GMAIL_FROM", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
GMAIL_TO = os.environ.get("GMAIL_TO", GMAIL_FROM)  # send to self by default


def send_email(subject: str, body: str, to: str = None, html: bool = False) -> bool:
    """
    Send an email via Gmail SMTP.
    Set html=True to send an HTML email. Defaults to plain text.
    Returns True on success, False on failure (prints error, does not raise).
    """
    if not GMAIL_FROM or not GMAIL_APP_PASSWORD:
        print(
            "[send_digest] ERROR: GMAIL_FROM or GMAIL_APP_PASSWORD not set in .env. "
            "See SETUP.md for instructions.",
            file=sys.stderr,
        )
        return False

    recipient = to or GMAIL_TO or GMAIL_FROM

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_FROM
    msg["To"] = recipient
    content_type = "html" if html else "plain"
    msg.attach(MIMEText(body, content_type))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_FROM, [recipient], msg.as_string())
        print(f"[send_digest] Sent: '{subject}' → {recipient}")
        return True
    except smtplib.SMTPAuthenticationError:
        print(
            "[send_digest] ERROR: Gmail auth failed. Check GMAIL_APP_PASSWORD in .env.",
            file=sys.stderr,
        )
        return False
    except Exception as e:
        print(f"[send_digest] ERROR: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Send an email via Gmail SMTP")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--to", help="Recipient email (defaults to GMAIL_TO in .env)")
    parser.add_argument("--html", action="store_true", help="Send as HTML email")
    args = parser.parse_args()
    ok = send_email(args.subject, args.body, args.to, html=args.html)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
