#!/usr/bin/env python3
"""
log_entry.py — Append a reflexion entry to data/task-log.json.

Usage:
  python3 tools/log_entry.py --skill SKILL_NAME --action ACTION --note "free text"

Each entry:
  {
    "timestamp": "ISO-8601",
    "skill": "morning-brief",
    "action": "view",
    "note": "Generated morning brief. 3 urgent tasks, 2 pipeline flags."
  }
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "data" / "task-log.json"


def load_log() -> list:
    if not LOG_PATH.exists():
        return []
    text = LOG_PATH.read_text().strip()
    if text in ("", "[]"):
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        bak = LOG_PATH.with_suffix(".json.bak")
        LOG_PATH.rename(bak)
        print(f"[log] WARNING: task-log.json was corrupt, backed up to {bak.name}", file=sys.stderr)
        return []


def append_entry(skill: str, action: str, note: str) -> None:
    log = load_log()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": skill,
        "action": action,
        "note": note,
    }
    log.append(entry)
    LOG_PATH.write_text(json.dumps(log, indent=2))
    print(f"[log] {skill}/{action}: {note}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    append_entry(args.skill, args.action, args.note)


if __name__ == "__main__":
    main()
