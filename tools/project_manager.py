#!/usr/bin/env python3
"""
project_manager.py — CLIP project state manager.

Reads and writes data/projects/<slug>/ for client project tracking.
Used by the project-agent skill and CEO agent.

Usage:
  python3 tools/project_manager.py --action status --project my-client
  python3 tools/project_manager.py --action log-decision --project my-client --decision "X" --context "why"
  python3 tools/project_manager.py --action add-milestone --project my-client --milestone "X" --deadline 2026-06-01
  python3 tools/project_manager.py --action get-context --project my-client
  python3 tools/project_manager.py --action init --project acme-co --client "Acme Co"
  python3 tools/project_manager.py --action list
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
DATA = BASE / "data"
PROJECTS_DIR = DATA / "projects"


def load_project(slug: str) -> dict:
    path = PROJECTS_DIR / slug / "project.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_project(slug: str, data: dict):
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    (PROJECTS_DIR / slug).mkdir(exist_ok=True)
    path = PROJECTS_DIR / slug / "project.json"
    path.write_text(json.dumps(data, indent=2))


def action_status(slug: str) -> str:
    project = load_project(slug)
    if not project:
        return f"Project '{slug}' not found. Run: python3 tools/project_manager.py --action init --project {slug}"

    lines = [
        f"**{project.get('client', slug)}** — Phase {project.get('phase', '?')} [{project.get('status', '?')}]",
        "",
    ]

    milestones = project.get("milestones", [])
    if milestones:
        lines.append("**Milestones:**")
        for m in milestones:
            status = "✓" if m.get("done") else "○"
            deadline = m.get("deadline", "")
            overdue = ""
            if deadline and not m.get("done"):
                try:
                    d = datetime.strptime(deadline, "%Y-%m-%d")
                    if d < datetime.now():
                        overdue = " ⚠ OVERDUE"
                except Exception:
                    pass
            lines.append(f"  {status} {m.get('name', '?')} — {deadline}{overdue}")
        lines.append("")

    decisions = project.get("decisions", [])
    if decisions:
        lines.append(f"**Recent decisions ({len(decisions)} total):**")
        for d in decisions[-3:]:
            lines.append(f"  [{d.get('date','?')}] {d.get('decision','?')[:100]}")
        lines.append("")

    # Also check decisions.md for file-based log
    decisions_md = PROJECTS_DIR / slug / "decisions.md"
    if decisions_md.exists():
        content = decisions_md.read_text().strip()
        if len(content) > 50:
            lines.append("_decisions.md has additional context_")

    return "\n".join(lines)


def action_log_decision(slug: str, decision: str, context: str) -> str:
    project = load_project(slug)
    if not project:
        return f"Project '{slug}' not found."

    entry = {
        "date": datetime.now().isoformat()[:10],
        "decision": decision,
        "context": context,
        "logged_at": datetime.now().isoformat(),
    }

    if "decisions" not in project:
        project["decisions"] = []
    project["decisions"].append(entry)
    save_project(slug, project)

    # Also append to decisions.md
    decisions_md = PROJECTS_DIR / slug / "decisions.md"
    with open(decisions_md, "a") as f:
        f.write(f"\n## {entry['date']}\n**Decision:** {decision}\n**Why:** {context}\n")

    return f"Decision logged for {slug}: {decision}"


def action_add_milestone(slug: str, milestone: str, deadline: str) -> str:
    project = load_project(slug)
    if not project:
        return f"Project '{slug}' not found."

    if "milestones" not in project:
        project["milestones"] = []
    project["milestones"].append({
        "name": milestone,
        "deadline": deadline,
        "done": False,
        "added": datetime.now().isoformat()[:10],
    })
    save_project(slug, project)
    return f"Milestone added: {milestone} (deadline: {deadline})"


def action_get_context(slug: str) -> str:
    """Return full project context for the CEO/project agent to load."""
    project_dir = PROJECTS_DIR / slug
    if not project_dir.exists():
        return f"Project '{slug}' not found."

    parts = []

    # project.json summary
    project = load_project(slug)
    if project:
        parts.append(f"# {project.get('client', slug)} — Project Context")
        parts.append(f"Status: {project.get('status','?')} | Phase: {project.get('phase','?')}")

        milestones = project.get("milestones", [])
        if milestones:
            open_m = [m for m in milestones if not m.get("done")]
            parts.append(f"\nOpen milestones ({len(open_m)}):")
            for m in open_m:
                parts.append(f"  - {m['name']} by {m.get('deadline','?')}")

        decisions = project.get("decisions", [])
        if decisions:
            parts.append(f"\nKey decisions ({len(decisions)}):")
            for d in decisions[-5:]:
                parts.append(f"  [{d['date']}] {d['decision']}")

    # decisions.md
    decisions_md = project_dir / "decisions.md"
    if decisions_md.exists():
        content = decisions_md.read_text().strip()
        if len(content) > 100:
            parts.append(f"\n# Decision Log\n{content[:3000]}")

    # requirements.md
    req_md = project_dir / "requirements.md"
    if req_md.exists():
        content = req_md.read_text().strip()
        if len(content) > 100:
            parts.append(f"\n# Requirements\n{content[:2000]}")

    # architecture.md (first 2000 chars)
    arch_md = project_dir / "architecture.md"
    if arch_md.exists():
        content = arch_md.read_text().strip()
        if len(content) > 100:
            parts.append(f"\n# Architecture (summary)\n{content[:2000]}")

    return "\n\n".join(parts)


def action_init(slug: str, client_name: str) -> str:
    project_dir = PROJECTS_DIR / slug
    if project_dir.exists():
        return f"Project '{slug}' already exists at {project_dir}"

    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "ingested").mkdir(exist_ok=True)

    project_data = {
        "slug": slug,
        "client": client_name,
        "status": "active",
        "created": datetime.now().isoformat()[:10],
        "milestones": [],
        "decisions": [],
        "contacts": [],
        "phase": 1,
    }
    save_project(slug, project_data)

    for fname, content in [
        ("decisions.md", f"# Decisions\n*{client_name} — created {datetime.now().isoformat()[:10]}*\n\n"),
        ("requirements.md", f"# Requirements\n*{client_name}*\n\n"),
        ("architecture.md", f"# Architecture\n*{client_name}*\n\n"),
        ("comms-log.md", f"# Communications Log\n*{client_name}*\n\n"),
    ]:
        (project_dir / fname).write_text(content)

    return f"Project '{slug}' ({client_name}) initialized at {project_dir}"


def action_list() -> str:
    if not PROJECTS_DIR.exists():
        return "No projects found."
    slugs = [d.name for d in PROJECTS_DIR.iterdir() if d.is_dir()]
    if not slugs:
        return "No projects found."
    lines = ["**Active projects:**"]
    for slug in sorted(slugs):
        project = load_project(slug)
        client = project.get("client", slug)
        status = project.get("status", "?")
        phase = project.get("phase", "?")
        lines.append(f"  {slug} — {client} [{status}, phase {phase}]")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="CLIP project manager")
    parser.add_argument("--action", required=True,
                        choices=["status", "log-decision", "add-milestone", "get-context", "init", "list"],
                        help="Action to perform")
    parser.add_argument("--project", default="", help="Project slug (e.g., my-client)")
    parser.add_argument("--decision", default="", help="Decision text (for log-decision)")
    parser.add_argument("--context", default="", help="Why this decision was made (for log-decision)")
    parser.add_argument("--milestone", default="", help="Milestone name (for add-milestone)")
    parser.add_argument("--deadline", default="", help="Deadline in YYYY-MM-DD (for add-milestone)")
    parser.add_argument("--client", default="", help="Client name (for init)")
    args = parser.parse_args()

    if args.action == "list":
        print(action_list())
    elif args.action == "status":
        if not args.project:
            print("--project required", file=sys.stderr)
            sys.exit(1)
        print(action_status(args.project))
    elif args.action == "log-decision":
        if not args.project or not args.decision:
            print("--project and --decision required", file=sys.stderr)
            sys.exit(1)
        print(action_log_decision(args.project, args.decision, args.context))
    elif args.action == "add-milestone":
        if not args.project or not args.milestone:
            print("--project and --milestone required", file=sys.stderr)
            sys.exit(1)
        print(action_add_milestone(args.project, args.milestone, args.deadline))
    elif args.action == "get-context":
        if not args.project:
            print("--project required", file=sys.stderr)
            sys.exit(1)
        print(action_get_context(args.project))
    elif args.action == "init":
        if not args.project or not args.client:
            print("--project and --client required", file=sys.stderr)
            sys.exit(1)
        print(action_init(args.project, args.client))


if __name__ == "__main__":
    main()
