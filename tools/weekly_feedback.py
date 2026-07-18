#!/usr/bin/env python3
"""
weekly_feedback.py — CLIP feedback loop analyzer.

Reads task-log.json, outreach_drafts.json, pipeline.json, and tasks.md
to understand what worked, what was ignored, and what needs attention.
Calls Claude (Haiku) to synthesize a short insight.
Pushes result to Telegram and appends to data/ai-updates.md.

Run: python3 tools/weekly_feedback.py
Schedule: every Monday 9:30am IST via APScheduler (server.py)
"""

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))


def load_env():
    env_path = BASE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def load_json(path: Path):
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def analyze_task_log(entries: list, since: datetime) -> dict:
    """Analyze skill usage over the past week."""
    recent = [e for e in entries if _parse_ts(e.get("timestamp", "")) >= since]

    skill_counts = Counter(e.get("skill", "unknown") for e in recent)
    action_counts = Counter(e.get("action", "unknown") for e in recent)

    # Skills not used in last 7 days
    all_skills = {
        "task-check", "pipeline-status", "morning-brief", "lead-scan",
        "opportunity-scan", "outreach-draft", "draft-proposal",
        "prep-meeting", "log-meeting", "clean-inbox", "notifications",
        "project-agent", "ceo", "heartbeat"
    }
    unused = sorted(all_skills - set(skill_counts.keys()))

    return {
        "total_actions": len(recent),
        "skill_usage": dict(skill_counts.most_common()),
        "unused_skills": unused,
        "top_skill": skill_counts.most_common(1)[0][0] if skill_counts else None,
    }


def analyze_outreach(drafts: list) -> dict:
    """Check outreach draft outcomes."""
    by_status = Counter(d.get("status", "unknown") for d in drafts)
    stuck_drafts = [
        d for d in drafts
        if d.get("status") == "draft" and d.get("created")
        and (datetime.now() - datetime.fromisoformat(d["created"])).days > 3
    ]
    return {
        "total_drafts": len(drafts),
        "by_status": dict(by_status),
        "stuck_unsent": len(stuck_drafts),
        "stuck_companies": [d.get("lead_company", "?")[:40] for d in stuck_drafts[:3]],
    }


def analyze_pipeline(pipeline: list) -> dict:
    """Check pipeline health."""
    if not isinstance(pipeline, list):
        pipeline = pipeline.get("contacts", []) if isinstance(pipeline, dict) else []

    stale = []
    for c in pipeline:
        last = c.get("last_contact") or c.get("last_contacted")
        if last:
            try:
                days = (datetime.now() - datetime.fromisoformat(last)).days
                if days > 7:
                    stale.append({"name": c.get("name", "?"), "days": days})
            except Exception:
                pass

    stages = Counter(c.get("stage", "unknown") for c in pipeline)
    return {
        "total_contacts": len(pipeline),
        "stage_breakdown": dict(stages),
        "stale_count": len(stale),
        "stale_contacts": sorted(stale, key=lambda x: x["days"], reverse=True)[:3],
    }


def analyze_tasks(tasks_path: Path) -> dict:
    """Check task completion signals."""
    if not tasks_path.exists():
        return {"status": "tasks.md not found"}

    content = tasks_path.read_text()
    urgent = content.count("- [ ]")
    done = content.count("- [x]")
    return {
        "open_tasks": urgent,
        "completed_tasks": done,
        "completion_rate": f"{round(done / (done + urgent) * 100)}%" if (done + urgent) > 0 else "no tasks",
    }


def call_llm(summary: dict) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    prompt = f"""You are CLIP, Alex's executive assistant. Give a short weekly feedback digest (3-4 lines max).
Be direct and specific. Highlight what's working, what's stale, and one action to take.

Data from the past 7 days:
- Skill usage: {summary['task_log']['skill_usage']}
- Unused skills: {summary['task_log']['unused_skills']}
- Outreach drafts stuck unsent: {summary['outreach']['stuck_unsent']} ({summary['outreach']['stuck_companies']})
- Pipeline contacts stale >7 days: {summary['pipeline']['stale_count']} ({[c['name'] for c in summary['pipeline']['stale_contacts']]})
- Open tasks: {summary['tasks']['open_tasks']}, Completed: {summary['tasks']['completed_tasks']}

Keep it punchy. No headers. Just the insight."""

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    from tools.credits import track_usage
    track_usage("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens)
    return resp.content[0].text.strip()


def push_to_telegram(message: str):
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": f"📊 Weekly Feedback\n\n{message}"},
        timeout=10,
    )


def write_to_updates(insight: str):
    path = BASE / "data" / "ai-updates.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n---\n## Weekly Feedback — {now}\n\n{insight}\n"
    current = path.read_text() if path.exists() else ""
    path.write_text(entry + current)


def _parse_ts(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return datetime.min


def main():
    load_env()
    since = datetime.utcnow() - timedelta(days=7)

    print("[weekly_feedback] Running...")

    task_log = load_json(BASE / "data" / "task-log.json")
    outreach = load_json(BASE / "data" / "outreach_drafts.json")
    pipeline_raw = load_json(BASE / "data" / "pipeline.json")

    pipeline = pipeline_raw if isinstance(pipeline_raw, list) else pipeline_raw.get("contacts", [])

    summary = {
        "task_log": analyze_task_log(task_log, since),
        "outreach": analyze_outreach(outreach),
        "pipeline": analyze_pipeline(pipeline),
        "tasks": analyze_tasks(BASE / "data" / "tasks.md"),
    }

    print(f"[weekly_feedback] Task actions this week: {summary['task_log']['total_actions']}")
    print(f"[weekly_feedback] Stuck drafts: {summary['outreach']['stuck_unsent']}")
    print(f"[weekly_feedback] Stale pipeline contacts: {summary['pipeline']['stale_count']}")

    insight = call_llm(summary)
    print(f"[weekly_feedback] Insight: {insight}")

    write_to_updates(insight)
    push_to_telegram(insight)

    # Log the run
    import subprocess
    subprocess.run(
        [sys.executable, "tools/log_entry.py", "--skill", "weekly_feedback",
         "--action", "run", "--note", f"feedback loop: {summary['task_log']['total_actions']} actions, "
                                      f"{summary['outreach']['stuck_unsent']} stuck drafts"],
        cwd=str(BASE)
    )

    print("[weekly_feedback] Done.")


if __name__ == "__main__":
    main()
