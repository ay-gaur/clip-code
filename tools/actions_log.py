#!/usr/bin/env python3
"""
actions_log.py — CLIP autonomous action audit log.

Every action CLIP takes (send email, add task, move pipeline, etc.) is
logged here. Provides accountability and enables /undo.

Usage (as a library):
  from tools.actions_log import log_action, get_recent

Usage (CLI — view log):
  python3 tools/actions_log.py
  python3 tools/actions_log.py --last 10
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
LOG_FILE = BASE / "data" / "actions-taken.json"


def log_action(action_type: str, params: dict, result: str, source: str = "bot", note: str = "") -> dict:
    """
    Log an action taken by CLIP. Call this immediately after executing any action.

    Args:
        action_type: e.g. 'send_email', 'add_task', 'move_pipeline_stage'
        params: the parameters used (to, subject, body, etc.)
        result: stdout result from the tool, or 'success'/'failed'
        source: who triggered it ('bot', 'heartbeat', 'email_monitor', etc.)
        note: human-readable summary for /undo display
    """
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        log = json.loads(LOG_FILE.read_text()) if LOG_FILE.exists() else []
    except Exception:
        log = []

    entry = {
        "id": f"{int(datetime.now(timezone.utc).timestamp())}",
        "action": action_type,
        "params": params,
        "result": result[:500] if result else "",
        "source": source,
        "note": note,
        "status": "done",
        "taken_at": datetime.now(timezone.utc).isoformat(),
    }

    log.append(entry)
    # Keep last 200 entries
    if len(log) > 200:
        log = log[-200:]

    LOG_FILE.write_text(json.dumps(log, indent=2))
    return entry


def get_recent(n: int = 10) -> list:
    """Return the N most recent log entries."""
    if not LOG_FILE.exists():
        return []
    try:
        return json.loads(LOG_FILE.read_text())[-n:]
    except Exception:
        return []


def main():
    import argparse
    parser = argparse.ArgumentParser(description="View CLIP action log")
    parser.add_argument("--last", type=int, default=10, help="Show last N actions")
    args = parser.parse_args()

    entries = get_recent(args.last)
    if not entries:
        print("No actions logged yet.")
        return

    print(f"Last {len(entries)} CLIP actions:\n")
    for e in reversed(entries):
        taken = e.get("taken_at", "")[:16].replace("T", " ")
        status = "✓" if e.get("status") == "done" else "✗" if e.get("status") == "undone" else "?"
        note = e.get("note") or e.get("action")
        source = e.get("source", "?")
        print(f"  {status} [{taken}] [{source}] {note}")


if __name__ == "__main__":
    main()
