#!/usr/bin/env python3
"""
write_tasks.py — Deterministic tool for reading/writing data/tasks.md

Usage:
  python tools/write_tasks.py --action add --task "description" --priority urgent|week|backlog
  python tools/write_tasks.py --action remove --task "description"
  python tools/write_tasks.py --action list

Part of the CLIP WAT framework. AI agents call this; never edit tasks.md directly.
"""

import argparse
import os
import sys
from pathlib import Path

# Paths
ROOT = Path(__file__).parent.parent
TASKS_FILE = ROOT / "data" / "tasks.md"

SECTION_MAP = {
    "urgent": "Urgent",
    "week": "This Week",
    "backlog": "Backlog",
}

TEMPLATE = """# Tasks

## Urgent
_none_

## This Week
_none_

## Backlog
_none_
"""


def read_tasks():
    if not TASKS_FILE.exists():
        return {}

    content = TASKS_FILE.read_text()
    sections = {"Urgent": [], "This Week": [], "Backlog": []}
    current = None

    for line in content.splitlines():
        line = line.strip()
        if line == "## Urgent":
            current = "Urgent"
        elif line == "## This Week":
            current = "This Week"
        elif line == "## Backlog":
            current = "Backlog"
        elif line.startswith("- ") and current:
            task = line[2:].strip()
            if task:
                sections[current].append(task)

    return sections


def write_tasks(sections):
    lines = ["# Tasks", ""]
    for section_name in ["Urgent", "This Week", "Backlog"]:
        lines.append(f"## {section_name}")
        tasks = sections.get(section_name, [])
        if tasks:
            for task in tasks:
                lines.append(f"- {task}")
        else:
            lines.append("_none_")
        lines.append("")

    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text("\n".join(lines).rstrip() + "\n")


def fuzzy_match(query, candidates):
    """Find the task matching the query. Exact/substring match wins;
    otherwise require most of the query's words to appear in the task."""
    q = query.lower().strip()
    for candidate in candidates:
        if q == candidate.lower().strip() or q in candidate.lower():
            return candidate

    query_words = set(q.split())
    best_match = None
    best_score = 0
    for candidate in candidates:
        candidate_words = set(candidate.lower().split())
        overlap = len(query_words & candidate_words)
        if overlap > best_score:
            best_score = overlap
            best_match = candidate

    # Guard against stopword-only matches: need >=60% of query words present
    threshold = max(1, int(len(query_words) * 0.6))
    return best_match if best_score >= threshold else None


def action_add(task, priority):
    section = SECTION_MAP.get(priority, "This Week")
    sections = read_tasks()

    # Check for duplicate (case-insensitive)
    existing = sections.get(section, [])
    if any(t.lower() == task.lower() for t in existing):
        print(f"DUPLICATE: '{task}' is already in {section}.")
        sys.exit(1)

    sections[section] = existing + [task]
    write_tasks(sections)
    print(f"ADDED: '{task}' → {section}")


def action_remove(task):
    sections = read_tasks()

    # Pass 1: exact/substring match anywhere beats a fuzzy match in an earlier section
    q = task.lower().strip()
    for section_name, tasks in sections.items():
        for t in tasks:
            if q == t.lower().strip() or q in t.lower():
                sections[section_name] = [x for x in tasks if x != t]
                write_tasks(sections)
                print(f"REMOVED: '{t}' from {section_name}")
                return

    # Pass 2: best fuzzy match across ALL sections, not first-section-wins
    best = None  # (score, section_name, task)
    query_words = set(q.split())
    for section_name, tasks in sections.items():
        for t in tasks:
            overlap = len(query_words & set(t.lower().split()))
            if best is None or overlap > best[0]:
                best = (overlap, section_name, t)

    threshold = max(1, int(len(query_words) * 0.6))
    if best and best[0] >= threshold:
        _, section_name, t = best
        sections[section_name] = [x for x in sections[section_name] if x != t]
        write_tasks(sections)
        print(f"REMOVED: '{t}' from {section_name}")
        return

    print(f"NOT_FOUND: No task matching '{task}' found.")
    sys.exit(1)


def action_list():
    sections = read_tasks()
    for section_name in ["Urgent", "This Week", "Backlog"]:
        tasks = sections.get(section_name, [])
        print(f"\n## {section_name}")
        if tasks:
            for t in tasks:
                print(f"  - {t}")
        else:
            print("  (empty)")


def main():
    parser = argparse.ArgumentParser(description="Manage data/tasks.md")
    parser.add_argument("--action", choices=["add", "remove", "list"], required=True)
    parser.add_argument("--task", type=str, help="Task description")
    parser.add_argument("--priority", choices=["urgent", "week", "backlog"], default="week")
    args = parser.parse_args()

    if args.action == "add":
        if not args.task:
            print("ERROR: --task is required for add action")
            sys.exit(1)
        action_add(args.task, args.priority)

    elif args.action == "remove":
        if not args.task:
            print("ERROR: --task is required for remove action")
            sys.exit(1)
        action_remove(args.task)

    elif args.action == "list":
        action_list()


if __name__ == "__main__":
    main()
